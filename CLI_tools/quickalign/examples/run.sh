#!/bin/sh
# Edit these defaults, or override them with exported environment variables.
# This script does not load .env. Requires Docker and a POSIX shell.

# Absolute HOST directories. Use output/work roots separate from an active UI.
QUICKALIGN_INPUTS="${QUICKALIGN_INPUTS:-/absolute/path/to/inputs}"
QUICKALIGN_OUTPUTS="${QUICKALIGN_OUTPUTS:-/absolute/path/to/cli-outputs}"
QUICKALIGN_WORK="${QUICKALIGN_WORK:-/absolute/path/to/cli-work}"

# CONTAINER paths: copy the edited reads.tsv into QUICKALIGN_INPUTS.
# Paths within the TSV are relative to the TSV, or absolute container paths.
REFERENCE="${REFERENCE:-/inputs/reference.fasta}"
ANNOTATION="${ANNOTATION:-/inputs/annotation.gff3}"
READS_MANIFEST="${READS_MANIFEST:-/inputs/reads.tsv}"
RUN_NAME="${RUN_NAME:-example-run}" # /outputs/<RUN_NAME> must not already exist.

THREADS="${THREADS:-32}" # Total alignment + sorting budget, not BWA alone.
QUICKALIGN_CPUS="$THREADS" # Match Docker's CPU allowance to the job request.
QUICKALIGN_MEMORY="${QUICKALIGN_MEMORY:-256g}" # Container limit, not reservation.
SORT_MEMORY="${SORT_MEMORY:-512M}" # Per sort worker.
QUICKALIGN_IMAGE="${QUICKALIGN_IMAGE:-quickalign:0.1.0}"

set -eu
project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
if [ ! -d "$QUICKALIGN_INPUTS" ]; then
    printf 'Set QUICKALIGN_INPUTS to an existing input directory: %s\n' "$QUICKALIGN_INPUTS" >&2
    exit 1
fi
mkdir -p "$QUICKALIGN_OUTPUTS" "$QUICKALIGN_WORK"
export QUICKALIGN_INPUTS QUICKALIGN_OUTPUTS QUICKALIGN_WORK
export QUICKALIGN_CPUS QUICKALIGN_MEMORY QUICKALIGN_IMAGE

# The existing wrapper builds QUICKALIGN_IMAGE from this repo only if missing,
# then runs as your UID/GID with read-only inputs and writable output/work mounts.
exec sh "$project_dir/run_quickalign.sh" build "$REFERENCE" "$ANNOTATION" \
    --reads-manifest "$READS_MANIFEST" \
    --outdir "/outputs/$RUN_NAME" --workdir /work --name "$RUN_NAME" \
    --threads "$THREADS" --sort-memory "$SORT_MEMORY" --zip
