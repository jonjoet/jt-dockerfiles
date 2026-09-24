#!/bin/sh
# Transparent convenience wrapper. Paths inside CLI arguments use /inputs, /outputs, /work.
set -eu
: "${QUICKALIGN_INPUTS:?Set an existing input directory}"
: "${QUICKALIGN_OUTPUTS:?Set an existing CLI-only output directory}"
: "${QUICKALIGN_WORK:?Set an existing CLI-only work directory}"
for directory in "$QUICKALIGN_INPUTS" "$QUICKALIGN_OUTPUTS" "$QUICKALIGN_WORK"; do
    [ -d "$directory" ] || { printf 'Missing directory: %s\n' "$directory" >&2; exit 1; }
done
image=${QUICKALIGN_IMAGE:-quickalign:0.1.0}
if ! docker image inspect "$image" >/dev/null 2>&1; then
    docker build -t "$image" "$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
fi
set -x
exec docker run --rm --init --user "$(id -u):$(id -g)" \
    --read-only --cap-drop ALL --security-opt no-new-privileges \
    --memory "${QUICKALIGN_MEMORY:-256g}" --cpus "${QUICKALIGN_CPUS:-4}" --pids-limit 512 \
    --tmpfs /tmp:rw,nosuid,nodev,size=512m,mode=1777 \
    --env "QUICKALIGN_MEMORY=${QUICKALIGN_MEMORY:-256g}" \
    --env "QUICKALIGN_IMAGE_REFERENCE=$image" \
    --mount "type=bind,source=$QUICKALIGN_INPUTS,target=/inputs,readonly" \
    --mount "type=bind,source=$QUICKALIGN_OUTPUTS,target=/outputs" \
    --mount "type=bind,source=$QUICKALIGN_WORK,target=/work" \
    "$image" "$@"
