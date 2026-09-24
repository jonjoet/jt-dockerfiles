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
mkdir -p "$run/tmp" "$run/source"
# Keep the exact source tested, including any uncommitted fixes, with its run.
tar --exclude=.git --exclude=.claude --exclude=.verification --exclude=__pycache__ \
  --exclude=.pytest_cache --exclude='*.egg-info' --exclude=.env \
  -cf - . | tar -xf - -C "$run/source"
export BUILDX_CONFIG="$run/buildx"
docker build -t quickalign:0.1.0 "$run/source" > "$run/image-build.log" 2>&1
docker build -f "$run/source/tests/resolver/Dockerfile" --build-arg QUICKALIGN_TEST_IMAGE=quickalign:0.1.0 -t quickalign:resolver-test "$run/source" > "$run/resolver-build.log" 2>&1
docker image inspect quickalign:0.1.0 quickalign:resolver-test > "$run/images.json"
docker run --rm --network none --read-only --user "$(id -u):$(id -g)" \
  --memory 4g --cpus 4 --pids-limit 512 --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,size=256m,mode=1777 \
  --env QUICKALIGN_MEMORY=4g --env PYTHONPATH=/opt/quickalign/src --env TMPDIR=/results/tmp \
  --mount "type=bind,source=$run/source,target=/opt/quickalign,readonly" \
  --mount "type=bind,source=$run,target=/results" \
  --entrypoint /opt/conda/bin/python quickalign:resolver-test \
  -m pytest /opt/quickalign/tests -q -p no:cacheprovider --basetemp /results/pytest \
  --junitxml /results/junit.xml > "$run/pytest.log" 2>&1

# Exercise the package and Streamlit launcher installed in the runtime image.
# Only fixture/evidence directories are mounted; /opt/quickalign is untouched.
mkdir -p "$run/installed/inputs" "$run/installed/cli-outputs" \
  "$run/installed/ui-outputs" "$run/installed/work" "$run/installed/scripts"
cp "$run/source/tests/fixtures/make_fixture.py" "$run/installed/scripts/"
cp "$run/source/tests/integration/installed_image_smoke.py" "$run/installed/scripts/"
runtime=(docker run --rm --network none --read-only --user "$(id -u):$(id -g)"
  --memory 4g --cpus 4 --pids-limit 512 --cap-drop ALL --security-opt no-new-privileges
  --tmpfs /tmp:rw,size=256m,mode=1777 --env QUICKALIGN_MEMORY=4g)
"${runtime[@]}" --mount "type=bind,source=$run/installed,target=/evidence" \
  --entrypoint /opt/conda/bin/python quickalign:0.1.0 \
  /evidence/scripts/make_fixture.py /evidence/inputs > "$run/fixture.log" 2>&1
printf '@' >> "$run/installed/inputs/single.fastq"
"${runtime[@]}" \
  --mount "type=bind,source=$run/installed/inputs,target=/inputs,readonly" \
  --mount "type=bind,source=$run/installed/cli-outputs,target=/outputs" \
  --mount "type=bind,source=$run/installed/work,target=/work" \
  quickalign:0.1.0 build /inputs/reference.fasta /inputs/annotation.gff3 \
  --reads-manifest /inputs/read-groups.tsv --outdir /outputs/mixed \
  --workdir /work --threads 4 --sort-memory 256M --zip > "$run/installed-cli.log" 2>&1
"${runtime[@]}" \
  --mount "type=bind,source=$run/installed/inputs,target=/inputs,readonly" \
  --mount "type=bind,source=$run/installed/ui-outputs,target=/outputs" \
  --mount "type=bind,source=$run/installed/work,target=/work" \
  --mount "type=bind,source=$run/installed/scripts,target=/evidence,readonly" \
  --entrypoint /opt/conda/bin/python quickalign:0.1.0 \
  /evidence/installed_image_smoke.py > "$run/installed-ui.log" 2>&1
printf 'Verification artifacts: %s\n' "$run"
