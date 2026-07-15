#!/usr/bin/env bash
set -euo pipefail
#
# One-shot runner for the treejson_to_xlsx Docker CLI.
# The only thing you need installed on the host is Docker.
# Edit the variables below, then:  ./run.sh
#
# =========================== FILL THESE IN ===========================

# Path to your ASKCOS Tree Builder export (host path; relative or absolute).
INPUT_JSON="treeResults.json"

# Output workbook name. It is written NEXT TO the input file.
OUTPUT_XLSX="routes.xlsx"

# --- Content toggles ---
INCLUDE_REACTIONS=true      # add a unique-Reactions sheet
INCLUDE_STRUCTURES=true     # include the 'structures pathway' column (route images)
CHEM_THUMBNAILS=false       # embed a structure thumbnail per compound (Chemicals sheet)
ALSO_CSVS=false             # also write one CSV per sheet, into <input dir>/csv

# --- Name/CAS lookup ---
# false  = fully offline; nothing leaves the container (runs with --network none).
# true   = look up names + CAS from PubChem by InChIKey.
#          !! Sends InChIKeys to PubChem. NEVER enable for proprietary structures. !!
ONLINE_NAMES_CAS=false

# Docker image tag to build/use.
IMAGE_NAME="treejson2xlsx"

# =====================================================================
# (You normally don't need to edit below this line.)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$INPUT_JSON" ]; then
    echo "ERROR: input file not found: $INPUT_JSON" >&2
    exit 1
fi
INPUT_DIR="$(cd "$(dirname "$INPUT_JSON")" && pwd)"
INPUT_BASE="$(basename "$INPUT_JSON")"

# Build the image once (skipped if it already exists).
if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    echo "Building image '$IMAGE_NAME' ..."
    docker build -t "$IMAGE_NAME" "$SCRIPT_DIR"
fi

# Assemble the CLI arguments.
ARGS=("/data/$INPUT_BASE" -o "/data/$OUTPUT_XLSX")
[ "$INCLUDE_REACTIONS" = true ]  && ARGS+=(--reactions)
[ "$INCLUDE_STRUCTURES" = false ] && ARGS+=(--no-structures)
[ "$CHEM_THUMBNAILS" = true ]    && ARGS+=(--chem-images)
[ "$ALSO_CSVS" = true ]          && ARGS+=(--csv-dir /data/csv)

# Network policy: isolate the container unless online lookup is explicitly requested.
NET=(--network none)
if [ "$ONLINE_NAMES_CAS" = true ]; then
    NET=()
    ARGS+=(--online)
    echo "WARNING: online name/CAS lookup enabled — InChIKeys will be sent to PubChem."
    echo "         Do NOT use this for proprietary structures."
fi

echo "Running:"
echo "  docker run --rm ${NET[*]} -v \"$INPUT_DIR:/data\" $IMAGE_NAME ${ARGS[*]}"
echo
docker run --rm "${NET[@]}" -v "$INPUT_DIR:/data" "$IMAGE_NAME" "${ARGS[@]}"

echo
echo "Done. Output written to: $INPUT_DIR/$OUTPUT_XLSX"
[ "$ALSO_CSVS" = true ] && echo "CSVs written to:        $INPUT_DIR/csv/"
