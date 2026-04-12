# PlasAnn_CLI

A containerized wrapper for [PlasAnn](https://github.com/ajlopatkin/PlasAnn), a plasmid annotation tool. Used here to check whether planned sequence edits overlap replication origins (especially on rolling-circle-replication plasmids), by annotating candidate features — oriV, oriT, CDS, replicon/rep genes, transposons, ncRNAs — before committing edits.

Reference: [Islam et al., *NAR* 2026](https://academic.oup.com/nar/article/54/3/gkaf1507/8442276).

## Prerequisites

- Docker

## Quick start

Edit the variables at the top of `run_plasann.sh` (`INPUT_FILE`, `OUTPUT_DIR`, `INPUT_TYPE`, optional `EXTRA_ARGS`), then:

```bash
./run_plasann.sh
```

On first run, `BUILD_IF_MISSING=1` builds `plasann:latest` automatically. The script mounts the input file's parent dir at `/data/input`, `OUTPUT_DIR` at `/data/output`, and the `plasann-db` named volume at `/root/.plasann`, then invokes `PlasAnn -i /data/input/<name> -o /data/output -t <INPUT_TYPE>`.

> Note: the input dir is mounted read-write (not `:ro`) because PlasAnn writes Prodigal's intermediate `.gbk` file next to the input FASTA.

For one-off runs with different PlasAnn options, you can also bypass the script entirely and call `docker run ... plasann:latest PlasAnn ...` directly — the image has no entrypoint, so any PlasAnn invocation (or `bash`) works.

## Database persistence (named Docker volume)

PlasAnn auto-downloads ~several-hundred-MB of databases (DoriC, PlasmidFinder, oriT, TnCentral, Rfam, etc.) from Zenodo into `~/.plasann/Database` on first run. To avoid re-downloading every time, the wrapper mounts a **named Docker volume** `plasann-db` at `/root/.plasann` inside the container.

A named volume is a Docker-managed persistent directory that lives outside the image and outside your project folder. It's created lazily on first use — no setup needed. The relevant pieces of the `docker run` command:

```bash
docker run --rm \
    -v "$INPUT_DIR:/data/input" \         # input FASTA dir (rw; PlasAnn writes .gbk beside input)
    -v "$OUTPUT_DIR:/data/output" \       # where annotations land
    -v plasann-db:/root/.plasann \        # <-- named volume for the DB
    plasann:latest \
    PlasAnn -i /data/input/my.fasta -o /data/output -t fasta
```

The `-v plasann-db:/root/.plasann` syntax (name, not a path, on the left) tells Docker: "create/reuse a named volume called `plasann-db` and mount it at `/root/.plasann` inside the container." On the first run, PlasAnn downloads the databases into that volume. On subsequent runs, its `verify_database()` check sees the files are already present and skips the download.

Useful commands:

```bash
docker volume ls                    # list volumes (should include plasann-db)
docker volume inspect plasann-db    # show the host path Docker chose
docker volume rm plasann-db         # nuke the DB to force a fresh download
```

If you'd prefer a plain host directory instead (easier to inspect/back up), swap the named volume for a bind mount — e.g. `-v /some/host/path/.plasann:/root/.plasann`.

## Output

Files are written to `output_dir/<input_basename>/`:

- `<name>_annotations.csv` — main annotation table: one row per feature, with columns including `Start`, `End`, `Strand`, `Feature_Type`, and `Product`/`Gene`.
- `<name>_genbank.gbk` — annotated GenBank file.
- `<name>_summary_stats.csv` — per-plasmid summary.

### Reading it for origin / rep-gene checks

Filter `_annotations.csv` by `Feature_Type`:

- **`oriV`** — predicted origin of replication. PlasAnn's oriV detection is adapted from [OriV-Finder](https://github.com/doriclab/OriV-Finder): it screens intergenic regions for elevated AT content, BLASTs them against DoriC, and scores hits partly by proximity to annotated rep genes.
- **`replicon`** — rep gene hits against PlasmidFinder (e.g. `RepA`, `Rep_1`, `RCR_1`). These are the most reliable evidence of where replication machinery binds.
- **`oriT`** — origin of transfer (conjugation), separate from replication.

Cross-reference the `Start`/`End` columns with your intended edit coordinates. An edit overlapping either an `oriV` region or a `replicon` CDS is a red flag; overlapping the intergenic region immediately upstream of a replicon is also suspicious on rolling-circle plasmids, since the nick site / double-strand origin typically sits just 5' of the rep gene.

### Optional supplement for rolling-circle plasmids

PlasAnn alone is a reasonable first pass. For extra confidence on RCR plasmids — where the functional DSO can be small, AT-rich, and missed by BLAST against DoriC — run an additional HMMER search against Pfam rep profiles:

- **PF01446** (Rep_1) — RCR Rep proteins, pT181 family
- **PF01719** (Rep_2) — RCR Rep, pC194/pUB110 family
- **PF02486** (Rep_trans) — RCR Rep, IS*91*/pMV158 family (contains the catalytic tyrosine / HUH motif)

```bash
hmmscan --domtblout rep.domtbl Pfam_Rep.hmm <translated_CDS>.faa
```

Hits here pinpoint the Rep protein; the DSO is almost always in the intergenic region immediately upstream.

## Files

- `Dockerfile` — Ubuntu 24.04 + BLAST+, Prodigal, Infernal, `pip install plasann`.
- `run_plasann.sh` — host-side wrapper that handles volume mounts and invokes `docker run`.
- `README.md` — this file.
