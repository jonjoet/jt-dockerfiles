#!/usr/bin/env bash
# Use the installed UI result from a successful tests/verify.sh run at this SHA.
set -euo pipefail
project=$(cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project"
evidence=$(realpath "${1:?Pass the artifact directory printed by tests/verify.sh}")
case "$evidence" in "$project/.verification/"*) ;; *) exit 2 ;; esac
sha=$(git rev-parse HEAD)
rg -q "^commit: +$sha +dirty:" "$evidence/RUN.txt"
run="$project/.verification/download-$(date -u +%Y%m%dT%H%M%SZ)-${sha:0:7}"
mkdir -p "$run"
dirty=no
if [[ -n $(git status --porcelain) ]]; then dirty=yes; fi
printf 'commit:  %s   dirty: %s\nstarted: %s\npurpose: installed browser download acceptance\n' \
  "$sha" "$dirty" "$(date -u +%FT%TZ)" > "$run/RUN.txt"
mkdir -p "$run/work"
cp tests/browser/download_smoke.mjs "$run/"
browser_image=${BROWSER_TEST_IMAGE:-quickalign:browser-test-4.3.0}
docker image inspect "$browser_image" quickalign:0.1.0 > "$run/images.json"
job_file=("$evidence"/installed/ui-outputs/*/job.json)
[[ ${#job_file[@]} == 1 && -f ${job_file[0]} ]]
job_id=$(basename "$(dirname "${job_file[0]}")")
container="quickalign-download-smoke-$$"
cleanup() {
  docker logs "$container" > "$run/service.log" 2>&1 || true
  docker rm -f "$container" > "$run/container-cleanup.log" 2>&1 || true
}
trap cleanup EXIT
docker run -d --name "$container" --network none --read-only \
  --user "$(id -u):$(id -g)" --memory 4g --cpus 4 --pids-limit 512 \
  --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,size=256m,mode=1777 --env QUICKALIGN_MEMORY=4g \
  --mount "type=bind,source=$evidence/installed/inputs,target=/inputs,readonly" \
  --mount "type=bind,source=$evidence/installed/ui-outputs,target=/outputs" \
  --mount "type=bind,source=$run/work,target=/work" \
  --entrypoint /opt/conda/bin/streamlit quickalign:0.1.0 \
  run /opt/quickalign/streamlit_app.py --server.address=0.0.0.0 \
  --server.port=8501 --browser.gatherUsageStats=false > "$run/container-id.txt"
docker inspect "$container" > "$run/container.json"
docker exec "$container" /opt/conda/bin/python -c '
import time, urllib.request
for attempt in range(30):
    try:
        urllib.request.urlopen("http://127.0.0.1:8501/_stcore/health", timeout=1)
        break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit("UI did not start")
' > "$run/health.log" 2>&1
docker run --rm --network "container:$container" --user "$(id -u):$(id -g)" \
  --shm-size 1g --mount "type=bind,source=$run,target=/results" \
  "$browser_image" node /results/download_smoke.mjs http://127.0.0.1:8501 \
  "$job_id" /results > "$run/browser.log" 2>&1
download=("$run"/*.jbrowse.zip)
original=("$evidence/installed/ui-outputs/$job_id"/*.jbrowse.zip)
[[ ${#download[@]} == 1 && ${#original[@]} == 1 ]]
cmp "${download[0]}" "${original[0]}"
printf 'Downloaded ZIP matches the completed disk export.\n' > "$run/archive-check.txt"
printf 'Verification artifacts: %s\n' "$run"
