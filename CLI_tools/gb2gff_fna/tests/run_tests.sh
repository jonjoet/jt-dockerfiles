#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL_DIR="$(cd "$TEST_DIR/.." && pwd)"
RUN_ROOT="$TEST_DIR/runs"
RUN_DIR="$RUN_ROOT/run_$(date -u +%Y%m%dT%H%M%SZ)"
IMAGE="gb2gff_fna:test"
WEB_CONTAINER="gb2gff-fna-web-test-$(date -u +%Y%m%d%H%M%S)"

if [[ -n "$(git -C "$TOOL_DIR" status --porcelain)" ]]; then
    DIRTY="yes"
else
    DIRTY="no"
fi

mkdir -p "$RUN_DIR"
{
    echo "commit:  $(git -C "$TOOL_DIR" rev-parse HEAD)   dirty: $DIRTY"
    echo "started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "purpose: unit"
    echo ""
    echo "Tool directory: $TOOL_DIR"
    echo "Image: $IMAGE"
    echo "Host mount policy: only $TOOL_DIR is mounted"
    echo "Commands:"
    echo "  docker compose -f $TOOL_DIR/compose.yaml config"
    echo "  docker build -t $IMAGE $TOOL_DIR"
    echo "  docker run --rm -v $TOOL_DIR:/work:ro --entrypoint /usr/local/bin/_entrypoint.sh $IMAGE python3 -m unittest discover -s /work/tests -v"
    echo "  docker run --rm --user $(id -u):$(id -g) -v $TOOL_DIR:/work --entrypoint /usr/local/bin/_entrypoint.sh $IMAGE python3 /opt/gb2gff_fna.py /work/example/plasmid_benchling.gb -o /work/tests/runs/$(basename "$RUN_DIR")/smoke --validate"
    echo "  start Streamlit in a temporary container and probe /_stcore/health"
    echo "  inspect pinned runtime/dependencies and assert AGAT/BioPerl/BCBio are absent"
} >"$RUN_DIR/RUN.txt"

docker compose -f "$TOOL_DIR/compose.yaml" config >"$RUN_DIR/compose-config.yaml"
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

cleanup_web_container() {
    docker rm -f "$WEB_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup_web_container EXIT

docker run -d \
    --name "$WEB_CONTAINER" \
    --tmpfs /data/tmp:mode=1777 \
    -e GB2GFF_FNA_TMPDIR=/data/tmp \
    --entrypoint /usr/local/bin/_entrypoint.sh \
    "$IMAGE" \
    python3 -m streamlit run /opt/gb2gff_fna_web.py \
    --server.address=0.0.0.0 \
    --server.port=8501 \
    --browser.gatherUsageStats=false \
    >"$RUN_DIR/web-container-id.txt"

WEB_READY=0
for _ in $(seq 1 20); do
    if docker exec "$WEB_CONTAINER" /opt/conda/bin/python3 -c \
        "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).read().decode())" \
        >"$RUN_DIR/web-health.log" 2>&1; then
        WEB_READY=1
        break
    fi
    sleep 1
done
docker logs "$WEB_CONTAINER" >"$RUN_DIR/web.log" 2>&1
if [[ "$WEB_READY" != "1" ]]; then
    echo "Streamlit health check failed" >&2
    cat "$RUN_DIR/web.log" >&2
    exit 1
fi
cleanup_web_container
trap - EXIT

docker run --rm \
    --entrypoint /usr/local/bin/_entrypoint.sh \
    "$IMAGE" \
    python3 -c \
    "import Bio, gffutils, importlib.util, shutil, streamlit, sys; print('Python', sys.version.split()[0]); print('Biopython', Bio.__version__); print('gffutils', gffutils.__version__); print('Streamlit', streamlit.__version__); assert shutil.which('agat_convert_sp_gxf2gxf.pl') is None; assert shutil.which('bp_genbank2gff3') is None; assert importlib.util.find_spec('BCBio') is None; print('AGAT/BioPerl/BCBio absent')" \
    2>&1 | tee "$RUN_DIR/versions.log"

sha256sum "$RUN_DIR"/smoke/*.fna "$RUN_DIR"/smoke/*.gff3 >"$RUN_DIR/hashes.sha256"
docker image inspect "$IMAGE" --format \
    'Image ID={{.Id}} Size={{.Size}} bytes' >"$RUN_DIR/image.txt"

{
    echo "UTC finish: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    grep "^Ran " "$RUN_DIR/unittest.log"
    echo "Web health: $(cat "$RUN_DIR/web-health.log")"
    cat "$RUN_DIR/versions.log"
    cat "$RUN_DIR/hashes.sha256"
    cat "$RUN_DIR/image.txt"
} >>"$RUN_DIR/RUN.txt"
echo "Test evidence: $RUN_DIR"
