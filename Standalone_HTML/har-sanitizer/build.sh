#!/usr/bin/env bash
#
# Build har_sanitizer.html from cloudflare/har-sanitizer as a single, self-contained
# HTML file. The whole build runs inside an ephemeral Node container, so nothing is
# installed on the host. Only this folder is mounted into the container, and the
# output is written back as the calling user (not root).
#
# Usage:
#   ./build.sh            # build from the latest upstream commit (main)
#   ./build.sh <ref>      # build from a specific commit SHA, tag, or branch
#
set -euo pipefail

REF="${1:-main}"
NODE_IMAGE="node:22-bookworm"          # non-slim: ships with git, so no apt needed
SINGLEFILE_VERSION="0.13.5"            # vite-plugin-singlefile, pinned; supports upstream's Vite 4
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Building har_sanitizer.html from cloudflare/har-sanitizer @ ${REF} ..."

docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -v "${SCRIPT_DIR}:/out" \
  "${NODE_IMAGE}" \
  bash -euo pipefail -c '
    git clone https://github.com/cloudflare/har-sanitizer.git /tmp/build
    cd /tmp/build
    git checkout '"${REF}"'
    SHA=$(git rev-parse --short HEAD)
    npm ci
    npm install -D vite-plugin-singlefile@'"${SINGLEFILE_VERSION}"'
    cp /out/vite.singlefile.config.ts .
    npx vite build --config vite.singlefile.config.ts
    {
      echo "<!-- Built from cloudflare/har-sanitizer @ ${SHA} on $(date -u +%Y-%m-%d) via vite-plugin-singlefile -->"
      cat dist/index.html
    } > /out/har_sanitizer.html
  '

echo "Wrote ${SCRIPT_DIR}/har_sanitizer.html"
