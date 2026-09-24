#!/usr/bin/env bash
# Optional argument: tests/verify.sh artifact directory at the current SHA.
# Set BROWSER_TEST_IMAGE to reuse cc_gcev/browser-test:4.3.0.
set -euo pipefail
project=$(cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project"
sha=$(git rev-parse HEAD)
evidence=''
if [[ $# -gt 0 ]]; then
  evidence=$(realpath "$1")
  case "$evidence" in "$project/.verification/"*) ;; *) exit 2 ;; esac
  rg -q "^commit: +$sha +dirty:" "$evidence/RUN.txt"
fi
run="$project/.verification/jbrowse-$(date -u +%Y%m%dT%H%M%SZ)-${sha:0:7}"
mkdir -p "$run"
dirty=no
if [[ -n $(git status --porcelain) ]]; then dirty=yes; fi
printf 'commit: %s   dirty: %s\nstarted: %s\npurpose: rendered JBrowse and resolver acceptance\n' \
  "$sha" "$dirty" "$(date -u +%FT%TZ)" > "$run/RUN.txt"
# Source stays alongside evidence even if the checkout changes later.
mkdir -p "$run/source/tests" "$run/fixture-run"
cp -R src "$run/source/"
cp -R tests/unit tests/integration tests/browser "$run/source/tests/"
browser_image=${BROWSER_TEST_IMAGE:-quickalign:browser-test-4.3.0}
if ! docker image inspect "$browser_image" > /dev/null 2>&1; then
  export BUILDX_CONFIG="$run/buildx"
  docker build -f tests/browser/Dockerfile -t "$browser_image" . > "$run/image-build.log" 2>&1
fi
docker image inspect "$browser_image" quickalign:resolver-test > "$run/images.json"
if [[ -n "$evidence" ]]; then
  bundle="$evidence/installed/cli-outputs/mixed/reference.jbrowse"
  [[ -f "$bundle/manifest.json" ]]
  printf '%s\n' "$evidence" > "$run/installed-evidence.txt"
else
  docker run --rm --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$run,target=/results" \
  --env PYTHONPATH=/results/source/src --entrypoint python \
  -w /results/source quickalign:resolver-test -m pytest \
  tests/unit/test_bundle.py tests/integration/test_resolvers.py -q -p no:cacheprovider \
  --basetemp /results/fixture-run/pytest --junitxml /results/junit.xml > "$run/pytest.log" 2>&1
  bundle="$run/fixture-run/pytest/test_relocated_resolver_comple0/source/fixture.jbrowse"
fi
cp -R "$bundle" "$run/windows-test.jbrowse"
docker run --rm --user "$(id -u):$(id -g)" --network none --shm-size 1g \
  --mount "type=bind,source=$run,target=/results" \
  "$browser_image" node /results/source/tests/browser/jbrowse_smoke.mjs \
  /results/windows-test.jbrowse /results > "$run/browser.log" 2>&1
printf 'Verification artifacts: %s\nWindows test bundle: %s/windows-test.jbrowse\n' "$run" "$run"
