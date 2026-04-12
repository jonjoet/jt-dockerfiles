# Plasmid ori Detection Pipeline — Implementation Spec

## Goal

Two files that together detect replication origins in a plasmid FASTA, combining OriV-Finder and HMMER-based Rep protein classification. The output should be a single GFF3 file with all hits properly annotated by source and type — not just "do not edit" zones, but the original hits with their identities.

## File 1: `Dockerfile`

A lightweight Docker image for HMMER3 + Prodigal + the three Pfam HMM profiles needed to classify rolling circle replication (RCR) plasmid Rep proteins.

### What it should contain

- **Base image**: `quay.io/biocontainers/hmmer:3.4--hdbdd923_1`
- **Added tools**: Prodigal (for ORF prediction from the input FASTA)
- **Pfam HMM profiles** — download these three individually from the EBI Pfam API and concatenate + `hmmpress` them:
  - `PF01446` — Rep_1 (pC194/pUB110 family)
  - `PF01719` — Rep_2 (pMV158 family)
  - `PF02486` — Rep_trans (pT181/pC221 family)
- The EBI endpoint for individual HMMs is: `https://www.ebi.ac.uk/interpro/wwwapi//entry/pfam/{ACCESSION}?annotation=hmm`
- Set an env var `REP_HMM_DB` pointing to the pressed HMM database path (e.g. `/opt/rep_hmms/Rep_RCR.hmm`)
- Keep the image minimal — no entrypoint, just `CMD ["bash"]`

## File 2: `find_ori.sh`

A bash script that runs both search steps and merges results into annotated GFF3.

### Pipeline logic

1. **OriV-Finder step** (optional, skippable with a flag):
   - Run the OriV-Finder Docker image on the input FASTA
   - Parse its output into GFF3 features with `source=OriV-Finder`
   - Each feature should carry attributes like `oriV_type`, `RIP_domain`, `score` (whatever OriV-Finder reports)

2. **Rep protein HMMER step**:
   - Run Prodigal on the input FASTA to predict ORFs (use `-p meta` for short sequences)
   - Run `hmmsearch` against the Rep_RCR.hmm database with a configurable E-value threshold (default 1e-5)
   - Parse the `--domtblout` output
   - Map protein-coordinate hits back to nucleotide coordinates using the Prodigal GFF
   - Emit GFF3 features with `source=HMMER_Rep`, attributes including `Name=` (Pfam accession), `pfam_name=` (Rep_1/Rep_2/Rep_trans), `evalue=`, `score=`

3. **Merge step**:
   - Concatenate all GFF3 features into one file with a proper `##gff-version 3` header
   - Optionally apply a user-specified buffer (bp) around each feature, emitting additional `buffer_region` features
   - Print a human-readable summary to stdout showing what was found and where

### CLI interface

```
Usage: find_ori.sh [OPTIONS] <plasmid.fasta>

Options:
  -o FILE    Output GFF3 file           [default: <input>.ori.gff3]
  -b INT     Buffer (bp) around hits    [default: 0]
  -t INT     Threads                    [default: 4]
  -e FLOAT   HMMER E-value threshold    [default: 1e-5]
  -s         Skip OriV-Finder step
  -h         Help

Environment variables:
  ORIV_IMAGE   Docker image for OriV-Finder  [default: oriv-finder:latest]
  REP_IMAGE    Docker image for Rep search   [default: rep-rcr-search:latest]
```

### Important details

- Use `realpath` to resolve the input path before mounting into Docker
- Use a temp working directory, cleaned up on exit via `trap`
- The Rep search runs inside the custom Docker image built from the Dockerfile above
- Prodigal output and hmmsearch output are intermediate files in the temp dir
- The script should work if only one of the two steps produces hits (e.g., OriV-Finder skipped or found nothing)

## Obstacle: OriV-Finder Docker Interface is Undocumented

The OriV-Finder paper (Li & Gao, *Nucleic Acids Research* 2025, PMC12230664) states that a Docker image is freely available at `https://tubic.org/OriV-Finder/`, but:

1. **No Docker Hub or registry tag is published.** The image must be downloaded from the tubic.org website directly. The exact image name/tag is unknown.
2. **The CLI interface is not documented.** The paper describes a web server interface with file upload, not a command-line tool. The Docker image's entrypoint, expected arguments, input mount points, and output file format/structure are all unknown.
3. **The output format is uncertain.** The web server shows interactive visualizations with oriV locations, types (Type 1/2/3), RIP domains, iterons, and AT-rich regions. What the Docker image writes to disk (TSV? JSON? GFF?) is not specified.

### How to handle this

The script should:
- Make the OriV-Finder parsing modular — isolate it in a function like `parse_oriv_output()` that the user can adapt once they inspect the actual Docker image output
- Include a comment block explaining that the `docker run` invocation and output parsing are best-guess placeholders
- Make reasonable assumptions: input mounted at `/data/input.fasta`, output directory at `/data/output/`, tabular results file with columns for sequence name, start, end, type, domain, score
- Work correctly even if the OriV-Finder step is skipped (`-s` flag), so the Rep search alone produces valid output

The Rep HMMER step has no such ambiguity — Prodigal and hmmsearch have fully documented interfaces.
