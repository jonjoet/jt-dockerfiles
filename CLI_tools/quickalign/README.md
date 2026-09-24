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
  --outdir /outputs/experiment-1 \
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
The `--outdir` job directory must not already exist; its mounted parent does.
Keep CLI output/work roots separate from a running UI service. Without the
wrapper, a direct Docker invocation is:

```sh
docker run --rm --init --user "$(id -u):$(id -g)" \
  --memory 256g --env QUICKALIGN_MEMORY=256g \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,size=512m,mode=1777 \
  --mount "type=bind,source=$QUICKALIGN_INPUTS,target=/inputs,readonly" \
  --mount "type=bind,source=$QUICKALIGN_OUTPUTS,target=/outputs" \
  --mount "type=bind,source=$QUICKALIGN_WORK,target=/work" \
  quickalign:0.1.0 build /inputs/reference.fasta /inputs/annotation.gff3 \
  --outdir /outputs/another-run --workdir /work --nanopore /inputs/reads.fastq
```

The reference must be plain FASTA; compressed FASTQ and GFF/GFF3 are supported.
BAI/TBI indexes support contigs up to 536,870,912 bases (2^29) each. The limit is
per contig, not whole-genome size; GRCh38 fits. Longer contigs fail before
alignment or BWA indexing. CSI indexes are outside version 1.

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

Manifest source paths are used to open the reads. Portable metadata and warnings
use their basenames; explicit track labels are preserved.

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
128 MiB per file, and 512 MiB total. Browser ZIP downloads default to 128 MiB.
Small ZIPs are loaded only when Download ZIP is clicked, with the size limit
checked again at that time. Large bundles and ZIPs remain accessible in the
output mount; the results show their relative paths. Use CLI `--zip` for a
disk-based export of a large bundle. Configure the limits with
`QUICKALIGN_MAX_UPLOAD_FILES`, `QUICKALIGN_MAX_UPLOAD_MIB`,
`QUICKALIGN_MAX_UPLOAD_TOTAL_MIB`, and `QUICKALIGN_MAX_DOWNLOAD_MIB`.
`QUICKALIGN_INPUT_ROOTS` may contain platform-path-separator-delimited roots
beneath `/inputs`, and `QUICKALIGN_MAX_THREADS` caps UI submissions.

Compose and the CLI wrapper default `QUICKALIGN_MEMORY` to `256g`, an upper
ceiling intended for large real datasets rather than a reservation. Set a
smaller value for development and synthetic tests, for example
`QUICKALIGN_MEMORY=4g`. Also size `--sort-memory` with its worker count in mind.
BWA-MEM2 reference indexing can require substantially more memory than using
the index. The environment variable records the configured ceiling; Docker
enforces it. It does not constrain directly launched Python processes.

The service executes one synchronous job at a time. Job history uses bounded
metadata and required-file existence/size checks under `/outputs`; warnings and
zero-mapped tracks remain visible. Listing results, restarting the service, and
requesting export do not rehash BAMs. Extra files such as `.DS_Store` or generated
local configurations do not invalidate a completed result. These availability
checks do not detect same-size payload corruption.

A recoverably truncated unpaired FASTQ can complete with prominent
warnings and only its complete decoded records. Malformed records, paired-read
problems, compressed-data corruption, and tool/index failures remain fatal.
Warnings travel in `job.json`, the bundle manifest and README files, CLI
diagnostics, and current/previous UI results: **Some input reads could not be
processed; these alignments may be incomplete.** Truncated gzip additionally
warns that its final checksum was unavailable and recovered reads have not
passed that integrity check. CRC mismatch, invalid trailers, and DEFLATE errors
are fatal even when earlier reads produced valid BAM records.

A final bare `@` without a newline is an incomplete single-read record: preceding
complete records are retained with a truncation warning. Trailing blank lines at
EOF are accepted for single and paired inputs; blank lines between records are
malformed. Paired and interleaved reads still reject incomplete records, unequal
counts, and incompatible mate identifiers. A complete empty header is invalid,
and an input with no usable complete reads fails.

The service has no authentication. Expose it remotely only through a trusted
private network or an authenticated TLS reverse proxy. One Streamlit process
owns its output/work roots; shared roots across CLI runs or other UI containers
are unsupported. Refreshing or disconnecting the browser does not cancel a
server-side build. Restarted running jobs appear as interrupted, and known
orphan work is reconciled once at startup unless keep-work was selected.

## Open a bundle in JBrowse Desktop

Keep the completed `NAME.jbrowse` directory together. Its `config.json` and all
indexed data locations are relative, so the directory and ZIP can be moved.
Generate a Desktop configuration after every move:

```sh
cd NAME.jbrowse
./resolve-local.sh
# If executable permissions were lost on extraction:
bash resolve-local.sh
# Open NAME.local.jbrowse in JBrowse Desktop.
```

The shell resolver requires Bash, which is available on macOS and commonly on
Linux; no Python installation is needed. On Windows, `resolve-local.cmd` prefers
PowerShell 7 (`pwsh`) and falls back to Windows PowerShell (`powershell.exe`),
using `-NoProfile` and `-ExecutionPolicy Bypass`. You can also run
`resolve-local.ps1` directly. Browser-downloaded archives or scripts may carry
Windows Mark-of-the-Web; use the file's Properties **Unblock** control when
appropriate. If double-clicking the `.cmd` file is restricted by local policy,
open PowerShell, change into the bundle directory, and run the `.ps1` file.

The initial view shows the reference, annotation, and first BAM on the first
contig, bounded to 100,000 bases. Additional BAM tracks remain available in the
track selector. `local.template.jbrowse` contains a bundle-root token, including
in text-index locations; `config.json` retains relative locations.

The generated `.local.jbrowse` contains absolute paths for its current location
and is deliberately excluded from manifest hashing and ZIP export. Resolvers
write through a temporary file and leave `config.json` unchanged. File sizes and
SHA-256 values in `manifest.json` record creation-time provenance; normal
availability checks do not recompute those hashes. ZIP export remains a separate
disk operation, including ZIP CRC verification.

## Tests

Run the complete unit, actual-tool integration, Streamlit AppTest, and shell/
PowerShell resolver suite entirely in Docker:

```sh
./tests/verify.sh
```

The script builds the product and a separate digest-pinned PowerShell test
image, runs as the caller's UID with networking disabled and a 4 GB ceiling,
and preserves the tested source, logs, JUnit XML, fixture outputs, and a provenance
`RUN.txt` under `.verification/`. It also runs the installed CLI and Streamlit
launcher without mounting source over the package, exercising a real build,
visible truncation warnings, and ZIP export. PowerShell is absent from the
product image.

The [browser acceptance recipes](tests/browser/README.md) check actual annotation
and BAM rendering in pinned JBrowse 4.3.0 and a clicked download from the installed
Streamlit service.

`tests/fixtures/make_fixture.py DESTINATION` creates deterministic mixed-
technology inputs for container acceptance runs. Native execution of
`resolve-local.cmd` and visual inspection of the bounded default locus,
annotation search, and BAM tracks in JBrowse Desktop remain manual Windows and
Desktop release gates.
