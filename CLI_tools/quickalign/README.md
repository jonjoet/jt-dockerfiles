# quickalign

quickalign aligns Illumina and Oxford Nanopore reads to one reference and builds
one portable JBrowse 2 Desktop bundle. Each read group becomes a coordinate-
sorted, indexed BAM track. The command line is the primary interface; the same
image also provides a Streamlit interface for mounted files and smaller uploads.

## Build the image

```sh
docker build -t quickalign:0.1.0 .
```

The image pins Python 3.12.12, Node.js 22.23.2, minimap2 2.31, samtools and
htslib 1.22.1, JBrowse CLI 4.3.0, and the Bioconda `bwa-mem2` package 2.3.
`bwa-mem2 version` reports the upstream program version 2.2.1; this difference
between package and program versions is expected.

## Command line

Create separate input, output, and work directories. Inputs are mounted read-
only; output and work must be writable by the UID running the container.

```sh
export QUICKALIGN_INPUTS="$PWD/example-inputs"
export QUICKALIGN_OUTPUTS="$PWD/quickalign-output"
export QUICKALIGN_WORK="$PWD/quickalign-work"
mkdir -p "$QUICKALIGN_OUTPUTS" "$QUICKALIGN_WORK"

./run_quickalign.sh build /inputs/reference.fasta /inputs/annotation.gff3 \
  --outdir /outputs \
  --workdir /work \
  --name experiment-1 \
  --illumina-single /inputs/single.fastq.gz \
  --illumina-paired /inputs/R1.fastq.gz /inputs/R2.fastq.gz \
  --illumina-interleaved /inputs/interleaved.fastq.gz \
  --nanopore /inputs/nanopore.fastq.gz \
  --threads 8 --sort-memory 512M --zip
```

`run_quickalign.sh` builds the image if needed, runs as the caller's UID/GID,
and applies the same read-only-root and resource restrictions as Compose. Paths
in arguments are container paths under `/inputs`, `/outputs`, and `/work`.
Without the wrapper, use equivalent `docker run` mounts and run
`quickalign build ...` through the image entrypoint.

Direct read options may be repeated. They are mutually exclusive with
`--reads-manifest`. A manifest is a tab-separated UTF-8 file whose paths are
absolute or relative to the manifest:

```text
label	technology	layout	read1	read2
Short reads	illumina	single	single.fastq.gz	
Paired reads	illumina	paired	R1.fastq.gz	R2.fastq.gz
Interleaved	illumina	interleaved	interleaved.fastq.gz	
Long reads	nanopore	single	nanopore.fastq.gz	
```

Use `--keep-work` only when intermediate files are needed for diagnosis.
Otherwise job-scoped work is removed after success or failure. The output job
directory, logs, status metadata, and failed partial bundle remain available
for inspection. A ZIP export happens after bundle publication: export failure
does not invalidate a completed directory bundle.

At least two threads are required. quickalign divides the requested ceiling
between the aligner, the main `samtools sort` thread, and sort worker threads;
it never gives the full count to both concurrent programs. `--sort-memory` is
the limit per sort worker, not the process or container limit. Requested and
effective thread counts, the per-worker sort budget, configured container
memory, and the detected cgroup memory ceiling are recorded in the manifest.

## Streamlit service

Set three existing host directories and start Compose:

```sh
export QUICKALIGN_INPUTS=/absolute/path/to/inputs
export QUICKALIGN_OUTPUTS=/absolute/path/to/outputs
export QUICKALIGN_WORK=/absolute/path/to/work
export QUICKALIGN_UID="$(id -u)"
export QUICKALIGN_GID="$(id -g)"
docker compose up --build
```

Open <http://127.0.0.1:8501>. The default bind is loopback. Compose runs as a
non-root UID, drops all capabilities, enables `no-new-privileges`, uses a read-
only root filesystem and bounded tmpfs, and keeps input, output, and work mounts
separate. Do not make `/outputs` or `/work` a child of the input mount.

The mounted browser exposes only roots under `/inputs`, rejects hidden paths,
traversal, and escaping symlinks, and revalidates selections before a job.
Mounted files are preferred for large data. Upload defaults are 16 files,
128 MiB per file, and 512 MiB total. Browser ZIP downloads default to 128 MiB;
larger completed bundles remain in the output mount. Configure these with
`QUICKALIGN_MAX_UPLOAD_FILES`, `QUICKALIGN_MAX_UPLOAD_MIB`,
`QUICKALIGN_MAX_UPLOAD_TOTAL_MIB`, and `QUICKALIGN_MAX_DOWNLOAD_MIB`.
`QUICKALIGN_INPUT_ROOTS` may contain platform-path-separator-delimited roots
beneath `/inputs`, and `QUICKALIGN_MAX_THREADS` caps UI submissions.

Compose and the CLI wrapper default `QUICKALIGN_MEMORY` to `256g`, an upper
ceiling intended for large real datasets rather than a reservation. Set a
smaller value for development and synthetic tests, for example
`QUICKALIGN_MEMORY=4g`. Also size `--sort-memory` with its worker count in mind.

The service executes one synchronous job at a time. Job history comes from
validated metadata under `/outputs`; warnings and zero-mapped tracks remain
visible. A recoverably truncated unpaired FASTQ can complete with prominent
warnings and only its complete decoded records. Malformed records, paired-read
problems, compressed-data corruption, and tool/index failures remain fatal.

## Open a bundle in JBrowse Desktop

Keep the completed `NAME.jbrowse` directory together. Its `config.json` and all
indexed data locations are relative, so the directory and ZIP can be moved.
Generate a Desktop configuration after every move:

```sh
cd NAME.jbrowse
./resolve-local.sh
# Open NAME.local.jbrowse in JBrowse Desktop.
```

The POSIX resolver requires a POSIX shell and Python 3. The PowerShell resolver
uses PowerShell 7 and is launched directly with `resolve-local.ps1`. On Windows,
`resolve-local.cmd` is a convenience launcher using `-NoProfile` and
`-ExecutionPolicy Bypass`. Browser-downloaded archives or scripts may carry
Windows Mark-of-the-Web; use the file's Properties **Unblock** control when
appropriate. If double-clicking the `.cmd` file is restricted by local policy,
open PowerShell, change into the bundle directory, and run the `.ps1` file.

The generated `.local.jbrowse` contains absolute paths for its current location
and is deliberately excluded from manifest hashing and ZIP export. The portable
files remain covered by SHA-256 and size checks in `manifest.json`. Resolver
scripts replace the generated file safely when rerun.

## Tests

Build the normal tools image and run tests entirely in Docker:

```sh
docker build --target tools -t quickalign:tools .
docker run --rm -u "$(id -u):$(id -g)" \
  -v "$PWD:/project" -w /project -e PYTHONPATH=/project/src \
  quickalign:tools pytest -q
```

The Windows resolver suite uses a separate test-only image; PowerShell is not
added to the runtime image. Its Microsoft base is pinned by digest:

```sh
docker build -f tests/resolver/Dockerfile -t quickalign:resolver-test .
docker run --rm --read-only -u "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,nosuid,nodev,size=512m,mode=1777 \
  -v "$PWD:/project" -w /project -e PYTHONPATH=/project/src \
  quickalign:resolver-test pytest -q tests/integration/test_resolvers.py
```

`tests/fixtures/make_fixture.py DESTINATION` creates deterministic mixed-
technology inputs for container acceptance runs. Native execution of
`resolve-local.cmd` and visual inspection of the bounded default locus,
annotation search, and BAM tracks in JBrowse Desktop remain manual Windows and
Desktop release gates.
