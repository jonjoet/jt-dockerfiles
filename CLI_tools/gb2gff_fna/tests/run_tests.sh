#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL_DIR="$(cd "$TEST_DIR/.." && pwd)"
RUN_ROOT="$TEST_DIR/runs"
RUN_DIR="$RUN_ROOT/run_$(date -u +%Y%m%dT%H%M%SZ)"
IMAGE="gb2gff_fna:test"

mkdir -p "$RUN_DIR"
{
    echo "UTC start: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "Tool directory: $TOOL_DIR"
    echo "Image: $IMAGE"
    echo "Host mount policy: only $TOOL_DIR is mounted"
    echo "Commands:"
    echo "  docker build -t $IMAGE $TOOL_DIR"
    echo "  docker run --rm -v $TOOL_DIR:/work:ro --entrypoint /usr/local/bin/_entrypoint.sh $IMAGE python3 -m unittest discover -s /work/tests -v"
    echo "  docker run --rm --user $(id -u):$(id -g) -v $TOOL_DIR:/work --entrypoint /usr/local/bin/_entrypoint.sh $IMAGE python3 /opt/gb2gff_fna.py /work/example/plasmid_benchling.gb -o /work/tests/runs/$(basename "$RUN_DIR")/smoke --validate"
    echo "  inspect pinned runtime/dependencies and assert AGAT/BioPerl/BCBio are absent"
} >"$RUN_DIR/RUN.txt"

docker build -t "$IMAGE" "$TOOL_DIR"
docker run --rm \
    -v "$TOOL_DIR:/work:ro" \
    --entrypoint /usr/local/bin/_entrypoint.sh \
    "$IMAGE" \
    python3 -m unittest discover -s /work/tests -v \
    2>&1 | tee "$RUN_DIR/unittest.log"

mkdir -p "$RUN_DIR/smoke"
docker run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$TOOL_DIR:/work" \
    --entrypoint /usr/local/bin/_entrypoint.sh \
    "$IMAGE" \
    python3 /opt/gb2gff_fna.py \
    /work/example/plasmid_benchling.gb \
    -o "/work/tests/runs/$(basename "$RUN_DIR")/smoke" \
    --validate \
    2>&1 | tee "$RUN_DIR/smoke.log"

docker run --rm \
    --entrypoint /usr/local/bin/_entrypoint.sh \
    "$IMAGE" \
    python3 -c \
    "import Bio, gffutils, importlib.util, shutil, sys; print('Python', sys.version.split()[0]); print('Biopython', Bio.__version__); print('gffutils', gffutils.__version__); assert shutil.which('agat_convert_sp_gxf2gxf.pl') is None; assert shutil.which('bp_genbank2gff3') is None; assert importlib.util.find_spec('BCBio') is None; print('AGAT/BioPerl/BCBio absent')" \
    2>&1 | tee "$RUN_DIR/versions.log"

sha256sum "$RUN_DIR"/smoke/*.fna "$RUN_DIR"/smoke/*.gff3 >"$RUN_DIR/hashes.sha256"
docker image inspect "$IMAGE" --format \
    'Image ID={{.Id}} Size={{.Size}} bytes' >"$RUN_DIR/image.txt"

{
    echo "UTC finish: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    grep "^Ran " "$RUN_DIR/unittest.log"
    cat "$RUN_DIR/versions.log"
    cat "$RUN_DIR/hashes.sha256"
    cat "$RUN_DIR/image.txt"
} >>"$RUN_DIR/RUN.txt"
echo "Test evidence: $RUN_DIR"
