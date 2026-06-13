#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------
# Edit these variables, then run:   ./run_gb2gff_fna.sh
# ------------------------------------------------------------------

INPUT_FILE="./example/plasmid_benchling.gb"  # host path to input GenBank file
OUTPUT_DIR="./gb2gff_fna_output"             # host dir for .fna + .gff3
PREFIX=""                                    # output basename (empty = input name)
VALIDATE=0                                   # 1 = run AGAT standardizer, 0 = skip
SOURCE="GenBank"                             # value for the GFF3 source column

IMAGE="gb2gff_fna:latest"
BUILD_IF_MISSING=1                           # 1 = auto-build if image absent, 0 = never build

# ------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "$INPUT_FILE" ]]; then
    echo "Error: input file not found: $INPUT_FILE" >&2
    exit 1
fi

INPUT_DIR="$(cd "$(dirname "$INPUT_FILE")" && pwd)"
INPUT_NAME="$(basename "$INPUT_FILE")"

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    if [[ "$BUILD_IF_MISSING" == "1" ]]; then
        echo "Image $IMAGE not found — building from $SCRIPT_DIR..."
        docker build -t "$IMAGE" "$SCRIPT_DIR"
    else
        echo "Error: image $IMAGE not found and BUILD_IF_MISSING=0" >&2
        exit 1
    fi
fi

ARGS=(-o /data/output --source "$SOURCE")
[[ -n "$PREFIX" ]] && ARGS+=(--prefix "$PREFIX")
[[ "$VALIDATE" == "1" ]] && ARGS+=(--validate)

docker run --rm \
    -v "$INPUT_DIR:/data/input:ro" \
    -v "$OUTPUT_DIR:/data/output" \
    "$IMAGE" \
    "/data/input/$INPUT_NAME" "${ARGS[@]}"

echo ""
echo "Output written to: $OUTPUT_DIR"
