# assembly_filter

A standalone HTML tool for trimming junk contigs/scaffolds from genome assemblies. Upload a FASTA (and optionally a GFF), review sequences sorted by length, uncheck the ones you don't want, and export cleaned files — no server or installation required.

Typical use case: you have a yeast assembly with 16 chromosomes + mitochondrial DNA, plus several short assembly artifacts. This tool lets you visually identify and remove the junk.

## Variants

| File | Description |
|---|---|
| `assembly_filter.html` | Base version — upload FASTA + optional GFF, filter by checkbox, export |
| `assembly_filter_with_reference.html` | Adds a reference FASTA panel for side-by-side comparison (reference sequences are shown but never included in the export) |
| `assembly_filter_with_rename.html` | Adds the ability to rename contigs/scaffolds during export |

## Features

- Sorts contigs/scaffolds by length (or name) with N50 stats
- Select/deselect individual sequences, filter by minimum length, or invert selection
- Corresponding GFF lines are automatically removed for deselected sequences
- Exports `*.filtered.fasta` and `*.filtered.gff`
- Runs entirely client-side in the browser

## Usage

Open any of the `.html` files directly in a browser (or serve via `python3 -m http.server`). No build step needed.

## Files

- `assembly_filter.html` — base tool.
- `assembly_filter_with_reference.html` — variant with reference comparison.
- `assembly_filter_with_rename.html` — variant with contig renaming.
- `README.md` — this file.
