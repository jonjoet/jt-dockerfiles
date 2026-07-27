# gb2gff_fna

Convert a **GenBank** file into a **GFF3** annotation file plus a nucleotide
**FASTA** (`.fna`), using either a browser interface or the command line in one
Docker image.

It supports both **Benchling-exported plasmid maps** and genomic GenBank
records. It preserves explicit `gene → mRNA → CDS` relationships when the input
contains evidence for them, keeps flat plasmid annotations flat, and correctly
handles circular features that cross the origin.

## Why this tool exists

There is no single off-the-shelf converter that does this cleanly across input
types:

- **BioPerl's `bp_genbank2gff3`** is built for NCBI/genome records and *imposes*
  a `gene → mRNA → CDS` hierarchy. On flat plasmid maps it produces cluttered
  output and ignores `/label`.
The converter therefore uses Biopython directly and includes a non-destructive
validator. Validation checks the generated file without rewriting annotations
or synthesizing a gene model.

## What it produces

For an input `myplasmid.gb` and output directory `out/`:

- `out/myplasmid.fna` — nucleotide FASTA, one record per GenBank record.
- `out/myplasmid.gff3` — GFF3 with a `##sequence-region` line per record and one
  feature line per GenBank feature. Genuine multi-segment features use repeated
  rows with one shared `ID` and ordered `part=X/Y` attributes. An exact,
  contiguous circular boundary wrap uses one virtual-coordinate row.

The FASTA header and GFF3 `seqid` always match (the LOCUS name is used when the
record has no accession, which is the usual case for Benchling exports).

## Web interface

The Streamlit interface is the easiest option for interactive use. Start it
with Docker Compose:

```bash
docker compose up -d --build
```

Open <http://localhost:8501>, upload a `.gb`, `.gbk`, or `.genbank` file, and
download the generated GFF3 and FASTA individually or together as a ZIP. The
form exposes the output basename, GFF3 source column, and non-destructive
validation switch. Validation is enabled by default.

The server restarts automatically unless explicitly stopped. Common management
commands are:

```bash
docker compose logs -f
docker compose stop
docker compose start
docker compose down
```

Set `GB2GFF_FNA_PORT` to publish a different host port:

```bash
GB2GFF_FNA_PORT=1722 docker compose up -d
```

Uploaded and generated files are held in memory. Validation uses an ephemeral
in-container `tmpfs`; no host data directory or persistent volume is required.
Anyone who can reach the web port can submit files, so bind or firewall the
port appropriately when deploying beyond a trusted network.

## CLI quick start

For command-line use, edit the variables at the top of
`run_gb2gff_fna.sh`, then run:

```bash
./run_gb2gff_fna.sh
```

It auto-builds the image on first run, mounts your input and output
directories, and runs the conversion as your own user so output files aren't
owned by root.

## Manual CLI usage

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
| `--validate` | Validate the generated GFF3 without changing it. |

## Validation

`--validate` performs structural checks and asks `gffutils` to parse the result.
It verifies directives, columns, coordinates, strand and CDS phase values,
sequence bounds, circular virtual coordinates, repeated-ID invariants,
`part=X/Y` numbering, resolved `Parent` references, and acyclic hierarchy.

Validation never modifies the `.gff3`. A failure leaves both generated files in
place, reports every detected error to standard error, and exits non-zero.

## How features are mapped

- **Coordinates:** converted to GFF3's 1-based inclusive convention.
- **Name:** selected by feature type from stable identifiers and useful labels.
- **ID:** prefers `locus_tag` for genes, `transcript_id` for transcripts, and
  `protein_id` for CDS features; every ID is made unique across the whole file.
- **Type:** common GenBank keys are mapped to valid Sequence Ontology terms
  (e.g. `rep_origin` → `origin_of_replication`, `primer_bind` →
  `primer_binding_site`). Unrecognized keys become `sequence_feature`, with the
  original key retained as `gbkey`.
- **Parent:** transcript-to-gene and CDS/exon-to-transcript links require unique,
  compatible qualifier and location evidence. CDS/exon features fall back to a
  uniquely supported gene parent. Ambiguous relationships remain flat.
- **Other qualifiers:** preserved as percent-escaped attributes; `/note` becomes
  `Note`, `/db_xref` becomes `Dbxref`, and valueless flags become `true`.

Remote-reference locations are skipped with a warning instead of being silently
relocated onto the current record. Duplicate normalized record IDs are rejected.
Real `accession.version` identifiers are preserved. Records without an accession
fall back to their LOCUS name so FASTA headers and GFF3 seqids stay aligned.
Unknown strand is emitted as `.`, while an explicitly relevant but unknown
strand is emitted as `?`.

For circular records, a full-length `region` feature receives
`Is_circular=true`; one is synthesized when absent. Exact contiguous wraps can
extend to at most one landmark length beyond the sequence end, as allowed by
GFF3. Gapped compound features remain separate ordered parts.

GFF3 cannot preserve every GenBank location expression exactly. Fuzzy endpoints
are emitted as warned integer approximations; remote locations are skipped; and
the distinction between `join` and `order` is not retained beyond ordered
`part=X/Y` rows.

## Example

`example/plasmid_benchling.gb` is a tiny synthetic circular plasmid (a promoter,
a CDS, a primer-binding site, and a `rep_origin` that crosses the origin). It is
used by the default settings in `run_gb2gff_fna.sh` and is handy for a smoke
test.

## Notes

- Built on `mambaorg/micromamba` with Python 3.11, Biopython 1.87,
  gffutils 0.14, and Streamlit 1.59.2.
- The converter preserves evidenced hierarchy; it does not invent missing
  transcripts or attempt biological reconstruction from coordinates alone.
- Embedded-FASTA single-file output and per-record split files are out of scope.

## Tests

Run the Docker-only regression and smoke suite:

```bash
./tests/run_tests.sh
```

The harness mounts only this tool directory and writes timestamped evidence
under `tests/runs/run_*/` (ignored by Git). It exercises the CLI conversion,
web conversion helper, Compose configuration, and a live Streamlit health
check.
