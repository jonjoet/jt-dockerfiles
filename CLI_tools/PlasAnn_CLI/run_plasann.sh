#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------
# Edit these variables, then run:   ./run_plasann.sh
# ------------------------------------------------------------------

INPUT_FILE="./example/my_plasmid.fasta"   # host path to input FASTA
OUTPUT_DIR="./plasann_output"             # host dir for annotations
INPUT_TYPE="fasta"                        # "fasta" or "genbank"

IMAGE="plasann:latest"
VOLUME="plasann-db"                       # named Docker volume for the DB

BUILD_IF_MISSING=1                        # 1 = auto-build if image absent, 0 = never build

# Extra PlasAnn flags (leave empty if none). Example: EXTRA_ARGS=(--uniprot)
EXTRA_ARGS=()

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

docker run --rm \
    -v "$INPUT_DIR:/data/input:ro" \
    -v "$OUTPUT_DIR:/data/output" \
    -v "$VOLUME:/root/.plasann" \
    "$IMAGE" \
    PlasAnn -i "/data/input/$INPUT_NAME" -o /data/output -t "$INPUT_TYPE" "${EXTRA_ARGS[@]}"

echo ""
echo "Output written to: $OUTPUT_DIR"
