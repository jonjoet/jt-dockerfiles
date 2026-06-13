# gb2gff_fna — GenBank → GFF3 + FASTA CLI

**Date:** 2026-06-13
**Status:** Approved design, pending implementation
**Location:** `CLI_tools/gb2gff_fna/`

## Purpose

A Dockerized CLI that converts a GenBank file into a clean GFF3 annotation file
plus a nucleotide FASTA (`.fna`). Primary use case is Benchling-exported plasmid
maps, but the tool must be robust: it should never crash on unusual input and
should faithfully represent every feature it finds.

## Why this is non-trivial

No single off-the-shelf tool does this cleanly across input types:

- **`bp_genbank2gff3` (BioPerl)** is built for NCBI/genome records and *imposes*
  a `gene → mRNA → CDS` hierarchy. On flat plasmid maps it produces cluttered,
  warning-laden output and ignores Benchling's `/label` qualifier.
- **AGAT** cannot read GenBank at all — its converters take GFF/GTF/BED/EMBL.
  What AGAT is good at is *standardizing and validating* an existing GFF3.

Plasmid maps and genome records want opposite things (flat faithful dump vs.
reconstructed hierarchy), so the chosen approach is a custom Biopython converter
tuned for plasmids, with AGAT available as an optional standardization pass.

NCBI whole-genome GenBank files are explicitly **out of scope** as a priority:
those usually ship with FASTA + GFF already. Genome-grade hierarchy
reconstruction can be added later if needed (YAGNI).

## Approach

Custom Biopython converter (core) + optional AGAT validation pass, both shipped
in one Docker image.

## Repo layout

```
CLI_tools/gb2gff_fna/
  Dockerfile
  gb2gff_fna.py          # the Biopython converter (core logic)
  run_gb2gff_fna.sh      # edit-vars-and-run wrapper (mirrors run_plasann.sh)
  README.md
  example/
    plasmid_benchling.gb # small Benchling-style plasmid for testing/demo
```

## CLI interface

```
python3 gb2gff_fna.py INPUT.gb -o OUTDIR [--prefix NAME] [--source STR] [--validate]
```

- `INPUT.gb` — input GenBank file (single- or multi-record; circular OK).
- `-o OUTDIR` — output directory (created if absent).
- `--prefix NAME` — output basename; defaults to input file basename (sans ext).
- `--source STR` — value for the GFF3 source column; default `GenBank`.
- `--validate` — run the resulting GFF3 through AGAT's standardizer. Off by
  default (AGAT can reject perfectly reasonable plasmid features).

**Outputs:** `OUTDIR/<prefix>.fna` and `OUTDIR/<prefix>.gff3`.

## GFF3 mapping rules

- **seqid** = record id / LOCUS name. Emit one `##sequence-region <seqid> 1
  <length>` directive per record, after the `##gff-version 3` header.
- **coords**: Biopython locations are 0-based half-open; GFF3 is 1-based
  inclusive. Convert `start+1 .. end`.
- **Name** ← `/label` (Benchling convention), falling back to `/gene`,
  `/product`, then `locus_tag`.
- **ID**: `locus_tag` if present, else `Name`, else `<type>_<N>`. Uniqueness
  enforced with a per-run counter (suffix on collision).
- **type** (GFF3 column 3): map common Benchling/GenBank feature keys to valid
  Sequence Ontology terms where there is a clean mapping
  (`rep_origin` → `origin_of_replication`, `primer_bind` →
  `primer_binding_site`); pass through keys that are already valid
  (`gene`, `CDS`, `mRNA`, `tRNA`, `rRNA`, `promoter`, `terminator`, `exon`);
  pass through unknown keys unchanged rather than crashing.
- **Compound / origin-crossing locations**: emit one GFF3 line per segment, all
  segments sharing the same `ID`. This is the standard multi-segment
  representation and is correct both for circular features that wrap the origin
  and for spliced CDS.
- **strand**: `+` / `-` / `.`.
- **phase**: computed for `CDS` features (honoring `/codon_start`); `.` for
  everything else.
- **Parent**: link a `CDS`/`mRNA` to a `gene` feature *only* when they share a
  `locus_tag` or `gene` value; otherwise features remain flat (the plasmid
  default).
- **attributes**: all remaining qualifiers preserved as URL-escaped
  `key=value` pairs; `/note` → `Note`. Reserved attribute names (`ID`, `Name`,
  `Parent`) are not overwritten by qualifiers.

## FASTA output

`Bio.SeqIO.write(records, ..., "fasta")` over all records — full sequence, one
record per GenBank record. File extension `.fna`.

## Error handling

- Missing input file or unparseable GenBank → clear message naming the problem,
  exit 1.
- A feature with no usable location → skipped with a warning to stderr;
  conversion continues.
- A record with no features → still writes valid FASTA and a header-only GFF3
  for that record, with a warning.
- `--validate` and AGAT errors → warn, keep the raw (unvalidated) GFF3 on disk,
  exit non-zero so the failure is visible.

## Docker

- Base image: `mambaorg/micromamba` (mirrors the existing `Vulcan` CLI pattern).
- Install into base env: `micromamba install -y -n base -c bioconda
  -c conda-forge biopython agat` (AGAT pulls in Perl/BioPerl as a side effect).
- Copy `gb2gff_fna.py` to `/opt/`.
- `ENTRYPOINT` runs the script inside the activated base env via the micromamba
  entrypoint shim; `CMD ["--help"]`.
- `WORKDIR /data`.

## run_gb2gff_fna.sh

Edit-the-variables-then-run wrapper modeled on `run_plasann.sh`:
editable `INPUT_FILE`, `OUTPUT_DIR`, `PREFIX`, `VALIDATE`, `IMAGE`,
`BUILD_IF_MISSING`; auto-builds the image if absent; mounts only the input dir
and output dir (no host paths outside the working tree); runs the container.

## Testing (inside Docker, on the main thread)

Per repo conventions, build and verify with Docker; map only directories inside
the working tree.

1. Build the image.
2. Create `example/plasmid_benchling.gb` (Benchling-style: `/label` qualifiers,
   a `promoter`, a `primer_bind`, a `rep_origin`, a `CDS`, and one feature whose
   location crosses the origin) and a second 2-record GenBank file for the
   multi-record case.
3. Run the converter and assert:
   - `.fna` record count and per-record sequence lengths are correct.
   - `.gff3` begins with `##gff-version 3` and has a `##sequence-region` per
     record.
   - A spot-checked feature has correct 1-based inclusive coordinates.
   - `/label` values appear as `Name=` attributes.
   - The origin-crossing feature is emitted as multiple lines sharing one `ID`.
4. Run again with `--validate` and confirm AGAT accepts the file (or reports
   cleanly without destroying the raw output).

## Out of scope (future work)

- Genome-grade hierarchy reconstruction for complex eukaryotic GenBank.
- Embedded-FASTA (`##FASTA`) single-file output mode.
- Per-record split output files.
