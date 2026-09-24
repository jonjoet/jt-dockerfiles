#!/usr/bin/env bash
# Docker-only verification. Every invocation retains its source, logs and outputs.
set -euo pipefail
project=$(cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project"
sha=$(git rev-parse HEAD)
run="$project/.verification/verify-$(date -u +%Y%m%dT%H%M%SZ)-${sha:0:7}"
mkdir -p "$run"
dirty=no
if [[ -n $(git status --porcelain) ]]; then dirty=yes; fi
printf 'commit:  %s   dirty: %s\nstarted: %s\npurpose: capstone\n' "$sha" "$dirty" "$(date -u +%FT%TZ)" > "$run/RUN.txt"
mkdir -p "$run/tmp"
export BUILDX_CONFIG="$run/buildx"
docker build -t quickalign:0.1.0 "$project" > "$run/image-build.log" 2>&1
docker build -f tests/resolver/Dockerfile -t quickalign:resolver-test . > "$run/resolver-build.log" 2>&1
docker image inspect quickalign:0.1.0 quickalign:resolver-test > "$run/images.json"
docker run --rm --network none --read-only --user "$(id -u):$(id -g)" \
  --memory 4g --cpus 4 --pids-limit 512 --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,size=256m,mode=1777 \
  --env QUICKALIGN_MEMORY=4g --env PYTHONPATH=/opt/quickalign/src --env TMPDIR=/results/tmp \
  --mount "type=bind,source=$project,target=/opt/quickalign,readonly" \
  --mount "type=bind,source=$run,target=/results" \
  --entrypoint /opt/conda/bin/python quickalign:resolver-test \
  -m pytest /opt/quickalign/tests -q -p no:cacheprovider --basetemp /results/pytest \
  --junitxml /results/junit.xml > "$run/pytest.log" 2>&1
printf 'Verification artifacts: %s\n' "$run"
