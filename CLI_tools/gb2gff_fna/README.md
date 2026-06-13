# gb2gff_fna

Convert a **GenBank** file into a **GFF3** annotation file plus a nucleotide
**FASTA** (`.fna`), in one Docker container.

It is tuned for **Benchling-exported plasmid maps** but is built to be robust on
any GenBank input: it never tries to crash on unusual features, it uses the
`/label` qualifier (Benchling's convention) as the GFF3 `Name`, and it correctly
handles circular features that cross the origin.

## Why this tool exists

There is no single off-the-shelf converter that does this cleanly across input
types:

- **BioPerl's `bp_genbank2gff3`** is built for NCBI/genome records and *imposes*
  a `gene → mRNA → CDS` hierarchy. On flat plasmid maps it produces cluttered
  output and ignores `/label`.
- **AGAT** can't read GenBank at all — its converters take GFF/GTF/BED/EMBL. It
  *is* excellent at standardizing/validating an existing GFF3, which is why it's
  available here as an optional post-processing step.

So this tool uses a small Biopython converter (faithful, plasmid-friendly) and
keeps AGAT on hand for an optional standardization pass.

## What it produces

For an input `myplasmid.gb` and output directory `out/`:

- `out/myplasmid.fna` — nucleotide FASTA, one record per GenBank record.
- `out/myplasmid.gff3` — GFF3 with a `##sequence-region` line per record and one
  feature line per GenBank feature (multi-segment / origin-crossing features are
  emitted as multiple lines sharing one `ID`).

The FASTA header and GFF3 `seqid` always match (the LOCUS name is used when the
record has no accession, which is the usual case for Benchling exports).

## Quick start

The easiest way is the included wrapper. Edit the variables at the top of
`run_gb2gff_fna.sh`, then run it:

```bash
./run_gb2gff_fna.sh
```

It auto-builds the image on first run, mounts your input and output
directories, and runs the conversion as your own user so output files aren't
owned by root.

## Manual usage

Build the image once:

```bash
docker build -t gb2gff_fna:latest .
```

Run it (mount an input dir read-only and a writable output dir; `--user` keeps
output files owned by you):

```bash
docker run --rm --user "$(id -u):$(id -g)" \
    -v "$PWD/example:/data/input:ro" \
    -v "$PWD/out:/data/output" \
    gb2gff_fna:latest \
    /data/input/plasmid_benchling.gb -o /data/output
```

### Options

```
gb2gff_fna.py INPUT.gb -o OUTDIR [--prefix NAME] [--source STR] [--validate]
```

| Option | Description |
|--------|-------------|
| `INPUT.gb` | Input GenBank file (single- or multi-record; circular OK). |
| `-o, --outdir` | Output directory (created if absent). Default: current dir. |
| `--prefix` | Output basename. Default: input filename without extension. |
| `--source` | Value for the GFF3 source column. Default: `GenBank`. |
| `--validate` | Run the result through AGAT's GFF3 standardizer (see caveat). |

## The `--validate` caveat (off by default)

`--validate` runs the GFF3 through AGAT's `agat_convert_sp_gxf2gxf.pl`
standardizer. AGAT is **gene-model-centric**: it will wrap bare CDS features into
a tidy `gene → mRNA → exon → CDS` hierarchy, but it will also **drop features
that don't fit a gene model** — including the `rep_origin`, `primer_bind`,
`misc_feature`, and `promoter`-type features that make up most of a plasmid map.

So:

- **Plasmid maps:** leave `--validate` **off**. The default output is the
  faithful, complete representation you want.
- **Genome / annotation-tool GenBank headed into a strict downstream tool:**
  `--validate` can be useful to produce a clean, spec-normalized gene model.

If AGAT fails for any reason, the raw (unvalidated) GFF3 is kept and the tool
exits non-zero so the failure is visible.

## How features are mapped

- **Coordinates:** converted to GFF3's 1-based inclusive convention.
- **Name** ← `/label`, then `/gene`, `/product`, `locus_tag`.
- **ID:** `locus_tag` if present, else the Name, else `<type>_<n>`; made unique
  across the whole file.
- **Type:** common GenBank keys are mapped to valid Sequence Ontology terms
  (e.g. `rep_origin` → `origin_of_replication`, `primer_bind` →
  `primer_binding_site`); unrecognized keys pass through unchanged.
- **Parent:** a CDS/mRNA is linked to a `gene` feature only when they share a
  `locus_tag`/`gene`; otherwise features stay flat (the plasmid default).
- **Other qualifiers** are preserved as URL-escaped attributes; `/note` → `Note`.

## Example

`example/plasmid_benchling.gb` is a tiny synthetic circular plasmid (a promoter,
a CDS, a primer-binding site, and a `rep_origin` that crosses the origin). It is
used by the default settings in `run_gb2gff_fna.sh` and is handy for a smoke
test.

## Notes

- Built on the `mambaorg/micromamba` base; installs `biopython` and `agat` from
  bioconda/conda-forge. (AGAT pulls in Perl/BioPerl, so `bp_genbank2gff3` is also
  present in the image if you ever want it.)
- Out of scope for now: genome-grade hierarchy reconstruction for complex
  eukaryotic GenBank, embedded-FASTA single-file output, and per-record split
  files.
