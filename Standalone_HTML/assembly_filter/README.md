# assembly_filter

A standalone HTML tool for trimming junk contigs/scaffolds from genome assemblies. Upload a FASTA (and optionally a GFF), review sequences sorted by length, uncheck the ones you don't want, and export cleaned files — no server or installation required.

Typical use case: you have a yeast assembly with 16 chromosomes + mitochondrial DNA, plus several short assembly artifacts. This tool lets you visually identify and remove the junk.

## Features

- Sorts contigs/scaffolds by length (or name) with N50 stats
- Select/deselect individual sequences, filter by minimum length, or invert selection
- Displays an optional reference FASTA for ranked side-by-side comparison
- Renames contigs/scaffolds while keeping exported GFF seqids synchronized
- Corresponding GFF lines are automatically removed for deselected sequences
- Validates FASTA/GFF input and reports normalization or compatibility warnings
- Exports `*.filtered.fasta` and `*.filtered.gff`
- Runs entirely client-side in the browser

## Usage

Open `assembly_filter_with_rename.html` directly in a browser (or serve via `python3 -m http.server`). Load the assembly FASTA, then optionally load its GFF annotations and a display-only reference FASTA. No build step is needed.

## Files

- `assembly_filter_with_rename.html` — assembly filtering, reference comparison, and contig renaming.
- `test/harness.mjs` — DOM-free regression tests against the page's actual JavaScript.
- `README.md` — this file.
