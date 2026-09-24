# quickalign implementation plan

## Status

The version 1 implementation, container, tests, and synthetic fixture recipe
are now present. This document retains the governing scope and acceptance
contract. Run `tests/verify.sh` for Docker-only automated verification; native
Windows launcher execution and visual JBrowse Desktop checks remain manual
release gates as described below.

## Goal

Build a Docker-first command-line tool with a thin Streamlit interface that:

1. accepts one reference FASTA;
2. accepts one matching GFF/GFF3 annotation;
3. accepts any number of Illumina and Nanopore read groups;
4. aligns each read group with technology-appropriate tools and settings;
5. produces one sorted, indexed BAM track per read group; and
6. emits a portable JBrowse 2 bundle containing the reference, annotation, and
   all BAM tracks.

The CLI is the primary product surface. Streamlit calls the same Python core
directly and adds safe mounted-file browsing, uploads for smaller inputs, job
history, and access to completed bundles.

## Repository models reviewed

### `CLI_tools/gb2gff_fna`

Reuse its overall product shape:

- one image supports both CLI and Streamlit;
- the image defaults to the CLI while Compose overrides the entrypoint to start
  Streamlit;
- Compose publishes port 8501, has a Streamlit health check, and uses
  environment-configurable limits;
- CLI and web code call shared Python logic rather than the web layer invoking
  a shell wrapper; and
- the README documents both surfaces and makes the browser interface optional.

quickalign will differ because alignment jobs require durable input, output,
and work mounts rather than keeping all data in memory.

### MMSeek `origin/ui/streamlit`

Local reference checkout: `~/qbk-code/mmseek`. The UI is on
`origin/ui/streamlit`, inspected at commit
`14cd7af758cc2a6dc9b001bdbe70d802ec188256`, rather than the checked-out `main`.
Use `src/mmseek/ui/app.py` (`_render_server_browser` and the separate Run
button) plus `src/mmseek/ui/paths.py` as concrete implementation references.
The browser stores root-relative selections in session state and uses ordinary
buttons with `st.rerun()` for navigation and selection changes, outside forms.

Reuse its mounted-file and service-safety patterns:

- expose only configured roots beneath `/inputs`;
- represent browser selections as a configured root plus a relative path;
- resolve and re-check every selected path before execution;
- reject traversal, hidden paths, and symlinks escaping the configured root;
- mount inputs read-only and keep `/outputs` and `/work` separate;
- run the container as a non-root UID with a read-only root filesystem,
  dropped capabilities, `no-new-privileges`, resource limits, and tmpfs
  scratch space;
- bind Streamlit to localhost by default;
- create unique durable job directories and never overwrite prior jobs;
- allow only one synchronous job per Streamlit process; and
- discover prior jobs from validated, size-bounded metadata rather than
  trusting paths stored in metadata.

The MMSeek browser implementation should be adapted conceptually, not copied
wholesale. quickalign needs file-type-specific selectors and read-group rows
rather than query/target selection.

### `cc_gcev`

Reuse the relevant JBrowse and read-alignment design:

- stage reference FASTA plus FAI;
- sort GFF3 feature rows, remove an embedded FASTA tail, bgzip the result, and
  create a tabix index;
- use relative locations throughout `config.json`;
- configure annotation with `Gff3TabixAdapter`;
- configure BAM tracks with `BamAdapter` and BAI indexes;
- run the JBrowse text index over useful annotation attributes;
- include a bundle manifest, human-readable instructions, and JBrowse Desktop
  local-path resolver files;
- use minimap2 `map-ont` plus coordinate-sorted/indexed BAM output for Nanopore
  reads; and
- divide the thread budget between alignment and `samtools sort` rather than
  assigning the full thread count to both concurrent processes.

quickalign does not need cc_gcev's synteny, variant, coverage, donor, or
multi-assembly behavior.

## Product decisions

### Unified read-group model

Use one repeatable read-group model in the shared core and Streamlit UI. Each
row has:

- a user-visible label, defaulted from the selected filename(s);
- technology: `Illumina` or `Nanopore`;
- layout;
- read file 1; and
- optional read file 2.

Allowed layouts:

| Technology | Layout | Files | Behavior |
| --- | --- | ---: | --- |
| Illumina | Single/unpaired | 1 | Align as single-end Illumina reads |
| Illumina | Paired, separate files | 2 | File 1 is R1 and file 2 is R2 |
| Illumina | Paired, interleaved | 1 | One FASTQ contains alternating mates |
| Nanopore | Single/unpaired | 1 | Align as Oxford Nanopore reads |

The Streamlit row begins with a technology selector. For Illumina, it then
shows a single/paired layout selector. A paired row shows an R1 selector and an
R2 selector plus an **Interleaved pairs in one file** checkbox beside the R2
area. Enabling the checkbox disables and clears R2. Nanopore rows expose one
file selector and no paired layout.

This is clearer and more extensible than maintaining separate global
"unpaired" and "paired" sections. It also fulfills the requirement that
technology is selected independently for each read input while making the
Illumina-only paired constraint explicit.

Each row becomes one BAM track. quickalign will not merge unrelated read groups
by default.

### Technology-specific alignment

- **Illumina:** pinned BWA-MEM2, using `bwa-mem2 mem`.
  - Single/unpaired: one FASTQ argument.
  - Separate paired files: R1 and R2 arguments.
  - Interleaved paired reads: `-p` with one FASTQ.
- **Nanopore:** pinned minimap2, using `-ax map-ont`.
- Both paths add a unique read group containing a sanitized ID, sample name,
  and platform (`ILLUMINA` or `ONT`).
- Both paths stream SAM directly into `samtools sort`, then create a BAI with
  `samtools index`.
- Published BAMs remain unfiltered. quickalign will not silently discard
  secondary, supplementary, duplicate, QC-fail, or unmapped records.

BWA-MEM2 and minimap2 versions, exact commands, effective thread allocation,
and input-to-track mapping will be recorded in run metadata.

### JBrowse Desktop bundle only

The initial product emits a portable bundle for download and use with JBrowse
Desktop. Streamlit will not iframe JBrowse, host JBrowse Web, or run a second
web service. It will expose the durable bundle location and offer a ZIP
download only when the bundle is below a configurable browser-download
threshold.

Every bundle will include:

- portable relative locations in `config.json`;
- `local.template.jbrowse`;
- `resolve-local.sh`;
- `resolve-local.ps1`;
- `resolve-local.cmd`; and
- instructions to run the platform resolver and open the generated
  `SAMPLE.local.jbrowse` file in JBrowse Desktop.

The Windows `.cmd` file is a thin launcher for the PowerShell resolver using
`-NoProfile -ExecutionPolicy Bypass` and a script path based on `%~dp0`. The
README will explain why the launcher exists and note that browser-downloaded
archives may carry Windows Mark-of-the-Web restrictions.

The complete bundle directory remains relocatable. Resolver tests must move it
to a different path, including spaces and shell-sensitive characters, before
generating and validating the local JBrowse configuration.

## Proposed command-line interface

Primary command:

```text
quickalign build REFERENCE_FASTA ANNOTATION_GFF \
  --outdir OUTPUT_DIR \
  [--name SAMPLE] \
  [READ OPTIONS...] \
  [--threads N] \
  [--workdir WORK_ROOT] \
  [--keep-work] \
  [--zip]
```

For CLI runs, `--workdir` defaults to `OUTPUT_DIR/.quickalign-work-root`.
Callers may point it at a separate writable filesystem. Large sort temporary
files must never fall back to the container's size-limited `/tmp`.

Direct read options are repeatable:

```text
--illumina-single READS.fastq[.gz]
--illumina-paired R1.fastq[.gz] R2.fastq[.gz]
--illumina-interleaved READS.fastq[.gz]
--nanopore READS.fastq[.gz]
```

For labeled or programmatically generated jobs, also support:

```text
--reads-manifest read-groups.tsv
```

The direct read options and `--reads-manifest` will be mutually exclusive to
keep ordering and provenance unambiguous.

The manifest schema will be:

```text
label<TAB>technology<TAB>layout<TAB>read1<TAB>read2
```

Valid values:

- `technology`: `illumina` or `nanopore`;
- `layout`: `single`, `paired`, or `interleaved`;
- `read2`: required only for `illumina + paired`, otherwise empty.

The Streamlit adapter will create the same typed read-group objects directly;
it does not need to invoke the CLI or serialize an internal manifest before
calling the core.

### Shared job lifecycle

CLI and Streamlit use the same lifecycle API rather than independently
creating output directories:

```text
reserve_job(job_id, output_dir, work_root, run_spec) -> ReservedJob
run_job(reserved_job, prepared_inputs) -> JobResult
```

`reserve_job`:

- atomically creates the absent durable output directory;
- writes the initial `job.json` with `job_id`, `status=running`, origin
  (`cli` or `streamlit`), and `keep_work`;
- creates `work_root/<job-id>` exclusively; and
- returns the resolved, contained paths needed by later stages.

`run_job` accepts only a `ReservedJob`; it never attempts to reserve the same
directory again. The CLI calls `reserve_job` and then `run_job` directly. The
Streamlit service acquires the execution gate, selects its job ID, calls
`reserve_job`, stages any uploads beneath the reserved work directory, and
then calls `run_job`.

Both surfaces generate a job ID before reservation. `ReservedJob` and
`job.json` retain that ID, and all scoped work is keyed by it rather than by an
output basename.

Reservation ordering is deliberate: create the output directory, write the
initial running metadata, then create the scoped work directory. Any failure
after output creation while the job is still running, including work-directory
creation, validation, or upload staging, updates it to `status=failed`.
Failure handlers must preserve existing terminal statuses. All `job.json`
replacements use a temporary file in the same directory, flush and `fsync`,
then `os.replace`, so job discovery never observes a partially written JSON
document.

Additional CLI behavior:

- require at least one read group;
- accept plain or gzip-compressed FASTQ;
- require `OUTPUT_DIR` not to exist, then reserve it immediately;
- write `job.json` with `status=running` before validation or alignment begins;
- create all work beneath a selected work root;
- build the bundle as `SAMPLE.jbrowse.partial` on the output filesystem and
  rename it to `SAMPLE.jbrowse` only after all required bundle files validate;
- return non-zero on validation, alignment, indexing, bundle, or finalization
  failure;
- return zero for a completed bundle with recoverable input warnings, printing
  a prominent warning summary identifying the affected read groups;
- retain durable logs and failure metadata;
- retain failed run directories with `status=failed`, but never offer a
  `.partial` directory as a completed bundle;
- remove only the current run's scoped work directory unless `--keep-work` is
  selected; and
- make `--zip` opt-in because duplicating large BAMs in an archive can consume
  substantial disk space.

ZIP creation is a separate export step after the bundle has been published.
An archive written to disk is created as `.zip.partial`, validated, and renamed
only when the export succeeds. Track export status separately in `job.json`
(`not_requested`, `running`, `completed`, or `failed`); an export failure never
changes the completed bundle's job status or removes the bundle. Explicit CLI
`--zip` export failure returns non-zero and reports both the export error and
the usable bundle location. Streamlit reports the export failure while keeping
the completed bundle accessible, and never offers a `.zip.partial` download.
After interruption, an export left `running` is shown as interrupted without
invalidating the completed bundle. ZIP metadata must preserve the executable
bit for `resolve-local.sh`; the README will also show `sh resolve-local.sh` as
a portable fallback.

`--name` defaults to a sanitized reference FASTA stem. For CLI runs,
`OUTPUT_DIR` is the durable run directory and `SAMPLE.jbrowse` is the finished
bundle beneath it. For Streamlit, `/outputs/<job-id>` is the durable run
directory and the user-supplied sample name controls only the bundle basename
and JBrowse labels.

## Input validation

### Reference FASTA

- Require a regular, readable FASTA file.
- Reject duplicate sequence identifiers.
- Reject empty records.
- Copy the reference into the bundle without changing sequence IDs or bases.
- Build a fresh `.fai` with pinned samtools.
- Record contig names and lengths for annotation validation.
- Before alignment or BWA-MEM2 indexing, reject any contig longer than
  536,870,912 bases (2^29), naming the contig and the supported limit. Version 1
  uses BAI and TBI indexes; this is a per-contig limit, not a total reference
  size or BAM file-size limit. CSI support is deferred.

Compressed reference input is out of scope for the first version. Requiring a
plain FASTA avoids ambiguous random-access and bundle-copy behavior.

Human GRCh38 fits this index contract: its longest chromosome is 248,956,422
bases. See the [GRCh38 chromosome lengths](https://www.ncbi.nlm.nih.gov/grc/human/data)
and the [BAI](https://www.htslib.org/doc/samtools-index.html) and
[TBI](https://www.htslib.org/doc/tabix.html) index limits. The README should
explain this distinction so users do not mistake the limit for whole-genome
size.

### GFF/GFF3

- Accept `.gff`, `.gff3`, and optionally gzip-compressed forms.
- Require valid nine-column feature rows.
- Require every feature `seqid` to exist in the reference FASTA.
- Reject coordinates outside the corresponding reference sequence.
- Preserve directives before feature rows.
- Stop at `##FASTA` so embedded sequence data is not copied into the served
  annotation track.
- Sort feature rows by reference contig order, start, end, and stable input
  order.
- bgzip the normalized GFF3 and create a tabix index.
- Preserve original attributes; quickalign is not an annotation converter.

### FASTQ and pairing

- Require supported FASTQ/FASTQ.gz suffixes and readable files.
- Reject duplicate resolved paths within the same read group.
- For separate Illumina pairs, stream both files together before alignment and
  verify equal record counts plus compatible normalized mate identifiers.
- For interleaved Illumina input, verify an even record count and alternating
  compatible mate identifiers.
- Detect malformed or truncated unpaired Illumina/Nanopore FASTQ and gzip
  read errors during the normal input/alignment pass, without a full extra
  validation pass. Do not assume a zero aligner exit code proves complete
  input consumption. Use pinned parser diagnostics only where negative tests
  prove reliable detection and error classification; otherwise use a validating
  streaming reader that feeds complete records to the aligner. Only premature
  EOF/truncation is recoverable, including a partial final FASTQ record.
  Preserve complete decoded records before truncation and record a warning.
- Gzip CRC mismatches, invalid gzip trailers, DEFLATE data errors, other I/O
  errors, and malformed FASTQ not attributable to premature EOF are fatal.
  A late checksum failure may mean earlier decoded bases were wrong, even if
  their FASTQ syntax and resulting BAM are valid. Ensure gzip readers reach
  and check available trailers; do not mask corruption by stopping validation
  early. A missing trailer due to truncation is the recoverable exception.
- Recoverable truncation may produce a completed bundle with warnings
  when the aligner and downstream steps succeed and every BAM/index passes
  validation. Non-zero aligner/sort exits, invalid BAMs, and indexing failures
  remain fatal; do not downgrade arbitrary tool failures to warnings.
- Reject Nanopore paired/interleaved declarations at model validation time.

Pair-name normalization must be narrowly specified and tested for common
`/1`/`/2` and Illumina whitespace mate fields. It must not guess through
ambiguous names.

Pairing validation remains strict: malformed paired inputs, unequal counts,
or incompatible mate identifiers fail rather than guessing how to repair pairs.
Recoverable input warnings identify the read group, input display name, and
problem in `job.json`, the bundle manifest and README files, the CLI summary,
and Streamlit current/previous results. Persist warnings as a structured array;
keep `status=completed` for a verified published bundle and display it as
**Completed with warnings** when that array is non-empty. Input warnings must
include: **Some input reads could not be processed; these alignments may be
incomplete.** Do not claim all remaining reads were recovered or report an
exact lost-read count unless measured. For truncated gzip, also state:
**Gzip integrity could not be verified because the final checksum is missing
or incomplete; recovered reads have not passed that integrity check.** This
warning must travel with the bundle; syntactically complete records are not
proof that their bases are intact. Exported and browser-visible warnings use
display names, not raw absolute server paths.

## Shared Python architecture

The planned package boundaries are:

```text
quickalign/
  cli.py                 # argparse/Typer surface only
  models.py              # immutable typed run and read-group models
  inputs.py              # validation, pairing checks, safe names
  commands.py            # exact argv construction; no shell strings
  alignment.py           # BWA-MEM2/minimap2/samtools orchestration
  annotation.py          # GFF normalization and indexing
  bundle.py              # relative JBrowse config and bundle assembly
  jobs.py                # durable lifecycle, metadata, bundle finalization
  ui/
    app.py               # Streamlit rendering
    config.py            # mounted roots and resource limits
    paths.py             # safe browser helpers
    service.py           # UI submission to shared core
    lifecycle.py         # durable UI jobs and downloads
```

All external tools will be run with argument arrays using `subprocess`, never
through interpolated shell command strings. stdout and stderr for each step
will be written to separate durable log files. A failed step will preserve its
exit code, command, and log paths in metadata.

## Alignment execution

### Reference indexing

Build both indexes once per job:

- `samtools faidx` for JBrowse and BAM coordinate validation;
- `bwa-mem2 index` when at least one Illumina group is present.

Use an explicit BWA-MEM2 `-p` prefix under the reserved job's scoped work
directory (`/work/<job-id>/bwa/reference` in the UI), and pass that same prefix
to `bwa-mem2 mem`. Index files must not land beside read-only input files or
inside the portable bundle. Keep job-local indexing; version 1 adds no shared
index cache or indexing redesign.

minimap2 can align directly to the FASTA for the initial version. If real-data
testing shows repeated Nanopore groups spend material time rebuilding the
minimap2 index, add one job-scoped `.mmi` and reuse it across Nanopore groups.

### Thread allocation

Define one tested helper that allocates the requested job thread ceiling across
the aligner and concurrently running `samtools sort`. Account for:

- the aligner's worker threads;
- the sort process's main thread;
- optional sort workers; and
- the index step after sorting.

Do not pass the full requested thread count independently to both processes.
Record requested and effective values in metadata.

Read groups will run sequentially in version 1. This bounds peak memory and
temporary disk use and makes failures deterministic. Parallel read-group
alignment can be reconsidered after representative profiling.

### Output BAM contract

For every read group:

- assign a deterministic, collision-free track ID;
- write the sorted BAM directly to
  `SAMPLE.jbrowse.partial/alignments/<track-id>.bam`;
- direct `samtools sort -T` temporary files to the scoped work directory;
- set an explicit tested `samtools sort -m` budget per sort worker rather than
  relying on the tool default;
- write `SAMPLE.jbrowse.partial/alignments/<track-id>.bam.bai`;
- verify `samtools quickcheck`;
- verify coordinate sort order from the BAM header;
- verify the expected read-group header is present; and
- retain a count summary from `samtools flagstat` as a separate text artifact.

Do not treat zero mapped reads as a process failure. Report the condition
prominently in metadata and the Streamlit result page while retaining the valid
BAM and track.

## JBrowse bundle contract

Planned directory layout:

```text
OUTPUT_DIR/
  job.json
  read-groups.tsv
  logs/
    reference-index.*
    annotation-index.*
    <track-id>.align.*
    <track-id>.sort.*
    <track-id>.index.*
    jbrowse-text-index.*
  SAMPLE.jbrowse/
    config.json
    manifest.json
    README.html
    README.txt
    local.template.jbrowse
    resolve-local.sh
    resolve-local.ps1
    resolve-local.cmd
    reference/
      assembly.fasta
      assembly.fasta.fai
    annotation/
      features.gff3.gz
      features.gff3.gz.tbi
    alignments/
      <track-id>.bam
      <track-id>.bam.bai
      <track-id>.flagstat.txt
    trix/
      ...
```

### JBrowse configuration

Generate `config.json` deterministically with:

- one assembly using `IndexedFastaAdapter`;
- one feature track using `Gff3TabixAdapter`;
- one alignment track per read group using `BamAdapter`;
- categories grouped by `Alignments / Illumina` and
  `Alignments / Nanopore`;
- track names containing the row label and layout;
- track metadata containing technology, layout, original display names, and
  read-group ID;
- analytics disabled; and
- a default `LinearGenomeView` at a bounded locus on the first reference
  contig, containing the reference sequence, annotation, and first alignment
  track.

All alignment tracks remain configured and available in the track selector,
but only the first is visible initially. This avoids opening many BAM displays
at whole-genome scale while still presenting immediate alignment evidence.
Manual JBrowse Desktop testing must confirm that the bounded default locus and
track visibility are useful on representative data.

Run `jbrowse text-index` for the annotation track with useful attributes such
as `Name`, `ID`, `gene`, `gene_name`, `locus_tag`, and `Alias`.

Select and pin a current JBrowse 2 CLI release during implementation after a
container and resolver smoke test. Do not inherit cc_gcev's JBrowse 4.3.0 pin
without testing a current release. The local template and platform resolver
scripts remain part of the output contract even if the selected Desktop
release later gains direct relative-URI support.

### Bundle manifest

`manifest.json` will record:

- quickalign schema and application version;
- reference and annotation display names;
- sequence names and lengths;
- read-group labels, technology, layout, track IDs, and bundle-relative files;
- external tool versions;
- effective alignment presets and thread allocation;
- structured input warnings identifying affected read groups and any known
  limits on input completeness, also rendered prominently in README files;
- bundle file sizes and SHA-256 hashes; and
- JBrowse compatibility information.

The platform resolvers write `SAMPLE.local.jbrowse` into the bundle root and
replace it on each run. This generated local file is excluded from the
manifest's file/hash inventory because its absolute paths necessarily change
after relocation. Each resolver locates the bundle from its own script path,
not from the caller's current working directory.

No absolute host paths will be written inside the portable bundle. Durable
`job.json` may contain container paths needed for operator diagnostics, but the
Streamlit UI must redact them from browser-visible messages.

### Bundle finalization

Finalization order is:

1. validate every required file and adapter reference inside
   `SAMPLE.jbrowse.partial`;
2. write and validate its manifest and portable `config.json`;
3. rename the partial directory to `SAMPLE.jbrowse` on the same filesystem;
4. `fsync` the output-directory parent; and
5. update `job.json` to `status=completed`.

The CLI and Streamlit expose a bundle only when the job status is `completed`
and `SAMPLE.jbrowse/manifest.json` passes validation. A crash after the rename
but before the terminal metadata update therefore remains interrupted and does
not present an unconfirmed bundle as successful.

Validated completion metadata is the authoritative publication condition;
directory existence alone is insufficient. A handled failure after rename
retains failed metadata where possible, and an abrupt interruption may leave
running metadata. Both may leave a final-named directory containing
`config.json`, but neither is offered as a completed result. Preserve that
directory for inspection. Completion can include the input warnings described
above. Subsequent ZIP export has its own status and failure handling and must
not reverse bundle completion.

## Streamlit interface

### Page flow

Use a single wide page with:

1. **New bundle**
   - reference FASTA selector;
   - annotation GFF selector;
   - repeatable read-group rows;
   - output/sample name;
   - thread and optional advanced resource controls;
   - submit button.
2. **Current result**
   - job status and duration;
   - per-track mapped/read counts;
   - warnings and failure summary;
   - durable bundle location;
   - bounded manifest/read-group preview;
   - bundle ZIP download when within the configured limit.
3. **Previous results**
   - validated discovery of existing job directories beneath `/outputs`;
   - status, summary, and safe artifact access.

### File selection

Each selector supports:

- **Server file:** safe non-recursive navigation beneath configured roots under
  `/inputs`; or
- **Upload:** intended for small references, annotations, and test FASTQs.

The mounted-file browser will:

- list only supported file types for the active selector;
- hide dot entries;
- use root-relative session-state values;
- reject absolute paths and `..`;
- resolve symlinks and reject any target outside the configured root;
- repeat containment checks immediately before execution; and
- never mount or expose the host filesystem root.

Uploads will be copied in bounded chunks under `/work/<job-id>/uploads` using
application-generated filenames. Client filenames are display labels only.
The UI will enforce configured per-file, file-count, and aggregate upload
limits and explain that mounted server files are preferred for large FASTQs.

### Job behavior

- Single-user, one synchronous job at a time.
- Define one module-level, process-global execution gate in an imported module
  such as `ui/service.py`, not in the rerun entry script. It contains a
  non-blocking `threading.Lock` and an `active_job_id`.
- Perform obvious input-only validation, such as missing R2 or an empty sample
  name, before acquiring the gate or reserving a durable job.
- Follow MMSeek's responsive interaction pattern: file browsing, read-row
  add/remove controls, technology/layout selectors, and the interleaved
  checkbox live outside `st.form` and update immediately through session state
  and reruns. Give each row and file selector stable, distinct widget keys.
- Use a separate ordinary `st.button` labeled **Build bundle**. Only an explicit
  click constructs a submission from current widget state and invokes the
  service; navigation and other reruns never submit jobs. A submission must
  acquire the gate before selecting a job ID or reserving output/work paths;
  otherwise it receives a busy message and creates no job.
- The shared core never imports Streamlit or calls `st.*`; it reports progress
  only through durable `job.json` updates and logs.
- Unique job IDs:
  `YYYYMMDDTHHMMSSZ-<12 lowercase UUID hexadecimal characters>`.
- Durable output:
  `/outputs/<job-id>`.
- Scoped work:
  `/work/<job-id>`.
- Set `active_job_id` immediately after generating the ID and before
  `reserve_job` writes running metadata.
- Create the durable output directory and `status=running` metadata before the
  blocking core call begins.
- Run the core synchronously while the submitting Streamlit session displays a
  spinner. Version 1 does not add a background worker.
- Execute reservation, staging, and the core inside `try`/`except`/`finally`.
  Both expected-failure and unexpected-`BaseException` handlers may change
  `status=running` to `failed` only when the durable metadata still reports
  that status. Preserve terminal statuses, including when a Streamlit stop or
  rerun exception arrives after the core has saved `status=completed`.
  Re-raise unexpected `BaseException` instances after the best-effort update
  or terminal-status check. The `finally` block always clears `active_job_id`
  and releases the lock, even when the terminal status must remain unchanged.
- Handle ZIP export separately from core failure handling so export exceptions
  never replace a completed bundle status with `failed`.
- Preserve completed and failed output directories.
- Clean only the current job's work directory unless keep-work is selected.
- Previous-results discovery receives the gate's current `active_job_id`. It
  displays `status=running` as interrupted only when the discovered job ID is
  not the active ID.
- Run orphan-work reconciliation once per Streamlit process through cached
  runtime initialization, before the first submission can acquire the gate.
  Reconciliation skips the active job ID and any job explicitly marked
  keep-work.
- Orphan reconciliation never deletes a work directory without a readable,
  contained, matching `job.json`; an unknown directory is left for operator
  inspection.
- A browser refresh or disconnect is not a cancellation mechanism. If the
  server-side call finishes, the durable job appears under Previous results.
  The UI does not promise uninterrupted browser-session progress reporting.
- On process restart the new process has no active job ID, so prior
  `status=running` jobs display as interrupted. Startup reconciliation may
  safely clean their contained work directories unless keep-work was selected.
- The interrupted label is informational only during normal job discovery.
  Destructive reconciliation runs only during the one-time startup pass.
- One Streamlit process owns its configured output/work roots. Concurrent CLI
  runs or another UI container sharing those roots are unsupported.
- Do not add a queue, database, authentication, TLS, or multi-user scheduling
  in version 1.

The result page must not load a multi-gigabyte ZIP into Streamlit memory. Add a
configurable maximum browser-download size. Larger bundles remain available on
the mounted output directory with clear operator-facing retrieval
instructions.

## Container and Compose design

### Image

Use one pinned micromamba-based image containing:

- Python;
- Streamlit;
- BWA-MEM2;
- minimap2;
- samtools;
- htslib/bgzip/tabix;
- JBrowse 2 CLI and Node runtime; and
- the installed quickalign Python package.

The image defaults to:

```text
quickalign --help
```

Compose overrides the command/entrypoint to:

```text
streamlit run /opt/quickalign/streamlit_app.py
```

Pin the base image by digest and every runtime tool to an exact tested version.
Record the image and tool versions in labels and job metadata.

### Compose service

Follow the stronger MMSeek service contract:

- `restart: unless-stopped`;
- `init: true`;
- explicit non-root UID/GID;
- read-only root filesystem;
- `cap_drop: [ALL]`;
- `no-new-privileges`;
- CPU, memory, and PID limits;
- localhost-only published port by default;
- read-only `/inputs`;
- writable `/outputs`;
- writable `/work`;
- tmpfs `/tmp`;
- writable `HOME` and `XDG_*` locations beneath tmpfs for Streamlit and Node
  runtime state;
- job-scoped `TMPDIR` beneath `/work/<job-id>` for alignment and sort spills;
- no automatic creation of missing host bind paths; and
- Streamlit `/_stcore/health` health check.

Document that the service has no authentication and should be exposed remotely
only through a trusted private network or an authenticated TLS reverse proxy.

### Memory configuration

The intended deployment host has more than 400 GB RAM. Default the configurable
container memory ceiling to `256g`, with `QUICKALIGN_MEMORY` as the operator
parameter. Compose uses `mem_limit: "${QUICKALIGN_MEMORY:-256g}"`; the optional
CLI helper passes the same value to `docker run --memory` and into the container
for metadata. Direct Docker examples show `--memory 256g` and the matching
environment setting. Record the configured ceiling and effective container
limit when available. The environment variable alone does not enforce a limit
for a directly launched Python process.

This is an upper limit, not a reservation or a target allocation. Keep the
explicit per-worker `samtools sort -m` allocation distinct from the whole
container limit and leave room for the aligner, UI, and other runtime memory.
Operators on smaller machines and synthetic CI runs can lower the container
limit without changing the default for the deployment host. The UI must not
claim to change the container ceiling at job submission time.

Document that BWA-MEM2 reference indexing can need substantially more memory
than using the completed index. Human-scale benchmarking and shared index
caching are not version 1 requirements for the current deployment. An index
process killed for exceeding memory is a fatal indexing failure, with durable
diagnostics where possible; if the whole container dies, existing interruption
handling applies. Do not report a memory-related failure as successful output.

### Host-side helper

Add a small `run_quickalign.sh` only if it remains a transparent convenience
wrapper. It may:

- build the image if absent;
- mount explicitly configured input/output/work directories;
- run as the invoking UID/GID; and
- forward CLI arguments.

It must not encode a second independent option model or hide the generated CLI
command. Its documented defaults must not point at the same host output/work
directories used by a running Compose UI service.

## Planned repository contents

Implementation should eventually create:

```text
CLI_tools/quickalign/
  Dockerfile
  README.md
  compose.yaml
  pyproject.toml
  environment.yml or pinned lock files
  streamlit_app.py
  run_quickalign.sh
  src/quickalign/
    ...
  tests/
    fixtures/
    unit/
    integration/
    browser/
```

Do not add quickalign files elsewhere in the repository unless a later
implementation task explicitly includes the root README index update.

## Test and verification plan

All implementation verification should run in Docker rather than installing
packages on the host. Each preserved run directory must begin with the
repository-required `RUN.txt` containing commit, dirty state, timestamp, and
purpose.

### Unit tests

Cover:

- read-group model combinations and rejected combinations;
- manifest parsing, ordering, duplicate labels, and path errors;
- deterministic safe track IDs and collision handling;
- exact BWA-MEM2, minimap2, samtools, bgzip, tabix, and JBrowse argv arrays;
- paired and interleaved mate-name validation;
- FASTA duplicate IDs, empty records, and per-contig length boundaries at
  2^29 and 2^29 + 1 (use synthetic length metadata for boundary unit tests);
- input-warning capture, completed-with-warnings presentation, and independent
  ZIP export status/failure handling;
- GFF field, contig, coordinate, embedded-FASTA, and sorting behavior;
- thread-budget calculations;
- memory configuration defaults/overrides and job-local BWA index prefixes;
- bundle-relative config generation;
- shared `reserve_job`/`run_job` behavior for both CLI and Streamlit;
- durable status transitions, atomic `job.json` replacement,
  same-filesystem bundle finalization, and scoped cleanup;
- reservation failure after output creation produces durable failed metadata;
- unknown orphan work without readable matching metadata is preserved;
- safe browser traversal and symlink-containment cases;
- upload count and size limits;
- durable job rediscovery and artifact allowlisting; and
- browser-visible server-path redaction.

### Container integration fixture

Create a small synthetic fixture with:

- a multi-contig reference FASTA;
- matching GFF3 features;
- one Illumina single-end FASTQ;
- one separate-file Illumina pair;
- one interleaved Illumina pair;
- one Nanopore FASTQ; and
- reads containing both mapped and unmapped examples.

The end-to-end test will:

- run as a non-root UID;
- mount inputs read-only;
- use separate output and work mounts;
- verify BWA index files stay under scoped work and are absent from the bundle;
- verify the configured Docker memory override is applied, using a smaller
  limit suitable for the synthetic fixture rather than allocating 256 GB;
- disable network after image construction where practical;
- exercise all four read-group forms in one job;
- verify input checksums remain unchanged;
- verify every BAM with `samtools quickcheck`;
- verify coordinate order, read-group headers, BAI files, and expected mapped
  records;
- query the indexed GFF with tabix;
- validate every URI in `config.json` resolves inside the bundle;
- confirm the JBrowse text index exists;
- check manifest sizes/hashes;
- confirm a bundle is offered only with validated `status=completed` metadata
  and a valid manifest, regardless of whether a final-named directory exists;
- confirm a failed run remains durable with `status=failed`, logs, and no
  published bundle;
- inject failure and interruption after bundle rename but before completion
  metadata is written; retain the final-named directory for inspection while
  keeping it unavailable as a completed result in CLI and UI discovery;
- inject a bundle-stage failure and confirm the `.partial` directory is never
  offered as a result;
- exercise premature EOF in plain/gzipped FASTQ for each pinned unpaired
  aligner path, preserving complete decoded reads with completeness warnings
  and the additional unverified-integrity warning for truncated gzip;
- test CRC mismatch, a mid-file bit flip in compressed data, and DEFLATE data
  errors separately from truncation; all detected integrity failures must
  prevent publication even if earlier reads produced a valid BAM;
- reject malformed non-truncation FASTQ, preserve strict paired-input
  rejection, and keep tool/BAM/index failures fatal;
- verify warnings survive bundle relocation in the manifest and README files
  and appear in the CLI summary and Streamlit current/previous results;
- inject ZIP export failure after bundle completion; verify the completed
  bundle remains accessible, export failure is reported separately, explicit
  CLI `--zip` returns non-zero, and no partial archive is offered;
- verify normal work cleanup and keep-work behavior; and
- verify a failed aligner/indexing step remains non-zero with durable logs and
  failure metadata.

### Streamlit tests

- Framework-independent tests for configuration, browsing, staging, and job
  lifecycle.
- Streamlit `AppTest` import/render smoke test using the exact launcher shipped
  in the image.
- Live container health check and initial page request.
- UI component tests for adding/removing read rows, changing technology,
  paired R2 behavior, interleaved checkbox behavior, validation messages, and
  submission mapping to shared core models.
- Exercise MMSeek-style directory navigation and file selection before any
  Build click; verify immediate updates, independent row state, and no job
  reservation or execution from navigation, selector changes, or reruns alone.
- Service-layer rerun test proving the execution gate rejects a duplicate
  submission while the synchronous core call is active.
- Service-layer test where the core saves `status=completed` and a subsequent
  Streamlit-style stop/rerun `BaseException` is raised: completion metadata and
  bundle availability survive, the exception propagates, `active_job_id` is
  cleared, and the execution lock is released. Also verify an already failed
  job retains its original failure metadata.
- Two-session discovery test proving an active job remains `running` and its
  work directory is not reconciled while a second session lists prior jobs.
- Two-session test proving both sessions reference the same gate object from
  the imported service module.

### JBrowse Desktop bundle tests

- Move the completed fixture bundle to a second directory whose path exercises
  spaces, double quotes, backslashes, dollar signs, apostrophes, ampersands,
  brackets, parentheses, semicolons, and non-ASCII characters where the host
  filesystem permits them.
- Run `resolve-local.sh` and `resolve-local.ps1` from a different current
  working directory.
- Provide a pinned test-only image or stage containing PowerShell; do not add
  PowerShell to the runtime image.
- Validate the generated `SAMPLE.local.jbrowse` JSON and confirm rerunning the
  resolver after a second relocation safely replaces the prior local file.
- Assert every generated local path resolves to an existing file beneath the
  relocated bundle.
- Validate that the portable `config.json` still contains only relative URIs.
- Assert the resolved file preserves the portable config's assemblies, tracks,
  text-search adapters, and default session while replacing relative URI
  locations with contained local paths.
- Confirm `SAMPLE.local.jbrowse` is excluded from manifest hash verification.
- Treat native `.cmd` execution and visual inspection in JBrowse Desktop as
  documented manual gates when a Windows runner and JBrowse Desktop are not
  available in automated CI.

## Implementation milestones

### Milestone 1: contracts and core models

- Add package skeleton, immutable models, manifest contract, safe naming, and
  CLI parsing.
- Freeze output schema and failure behavior with unit tests.

### Milestone 2: reference, annotation, and alignments

- Add FASTA/GFF validation and indexing.
- Add Illumina and Nanopore command construction.
- Add sequential per-group alignment, BAM verification, logs, and metadata.
- Pass focused container integration tests before adding JBrowse.

### Milestone 3: portable JBrowse bundle

- Add deterministic relative `config.json`.
- Add staged reference, annotation, BAMs, text index, README files, manifest,
  and the required Desktop resolver files.
- Pass config, tabix, BAM, manifest, relocation, and resolver tests.

### Milestone 4: Streamlit adapter

- Add safe mounted-file browser and bounded upload staging.
- Add unified dynamic read-group rows.
- Add single-job lifecycle, current result, previous jobs, and bounded
  downloads.
- Call the shared core directly.

### Milestone 5: hardened container and documentation

- Add pinned Dockerfile, Compose service, health check, limits, and optional
  transparent CLI helper.
- Add README examples for CLI, manifest, Compose, secure mounts, bundle
  download, and JBrowse Desktop.
- Run the full Docker-only unit, integration, UI, and resolver suites.
- Perform implementation self-review, then request the required complementary
  code review and address confirmed findings.

## Acceptance criteria

1. One plain reference FASTA and one matching GFF/GFF3 are required.
   Contigs longer than 2^29 bases fail preflight before alignment or BWA-MEM2
   indexing; version 1 retains BAI/TBI indexes.
2. A job accepts any non-empty mixture of Illumina single, Illumina
   separate-pair, Illumina interleaved-pair, and Nanopore single read groups.
3. Invalid technology/layout combinations fail before an aligner starts.
4. Each read group produces its own verified sorted BAM, BAI, flagstat summary,
   read-group header, and JBrowse track.
5. Illumina uses pinned BWA-MEM2 settings and Nanopore uses pinned minimap2
   `map-ont` settings.
6. The normalized GFF is sorted, bgzip-compressed, tabix-indexed, and
   coordinate-compatible with the reference.
7. The JBrowse bundle uses relative paths only, includes reference,
   annotation, all BAM tracks, text search, instructions, and a validated
   manifest.
8. The bundle remains valid after relocation, and its Linux and PowerShell
   resolvers generate contained local-path configurations accepted as valid
   JBrowse JSON.
9. CLI and Streamlit call the same core and produce the same output contract.
10. Streamlit cannot browse outside configured `/inputs` roots and does not
    expose raw absolute server paths.
11. The Compose service runs healthy as non-root with read-only inputs/root
    filesystem, separate writable output/work mounts, bounded resources, and a
    localhost-only default port. Its `QUICKALIGN_MEMORY` ceiling defaults to
    `256g` and supports explicit deployment/test overrides.
12. Completed and failed jobs retain useful durable metadata and logs.
    Unpaired-input truncation preserves verified BAMs with prominent, portable
    completeness warnings and an unverified-integrity warning for truncated
    gzip. CRC/DEFLATE corruption and other fatal core failures are never
    published as completed bundles. Publication requires validated completion
    metadata and manifest, including after interruption. ZIP export failures
    are reported separately without invalidating a completed bundle.
13. The implementation passes Docker-only unit, integration, Streamlit, and
    Desktop-resolver verification from a clean checkout.

## Future hardening notes

- Revisit deliberate double submission only if needed after the synchronous UI
  exists. A meaningful reproduction requires a live browser test with a slow
  fake core and a second submit interaction while the first call is blocked;
  Streamlit `AppTest` alone cannot model that timing. Decide explicitly whether
  a deliberate second click represents user intent or a duplicate before
  adding submission-nonce/idempotency machinery. This is not a version 1
  acceptance gate.

## Explicitly deferred

- multiple reference assemblies or annotations;
- CRAM output;
- CSI indexes and references with contigs longer than 2^29 bases;
- merging BAMs across read groups;
- read trimming, adapter removal, QC reports, duplicate marking, filtering,
  coverage tracks, and variant calling;
- paired Nanopore reads;
- automatic technology detection;
- automatic R1/R2 filename inference;
- a live embedded JBrowse iframe;
- JBrowse Web hosting or a bundled JBrowse Web application;
- a second JBrowse hosting service in Compose;
- queues, background workers, authentication, TLS, and multi-user isolation;
- cloud/object-storage inputs; and
- recursive server-file discovery.
