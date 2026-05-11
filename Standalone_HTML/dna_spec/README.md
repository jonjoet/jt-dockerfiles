# dna_spec

**Work in progress.**

A prototype standalone HTML tool for flexible assembly of reusable DNA parts into constructs. Upload a FASTA parts library, then visually build constructs by dragging parts into ordered slots.

## Features (current)

- Load a FASTA file as a sequence library
- Create named constructs with ordered slots
- Drag-and-drop parts from the library into construct slots
- Reverse-complement individual parts per slot
- Import construct definitions in bulk from a spreadsheet (CSV template provided)
- Optional GFF3 upload for part annotations
- Export assembled constructs as FASTA, CSV, or GFF

## Variants

| File | Description |
|---|---|
| `dna_spec.html` | Original prototype |
| `dna_spec_v2.html` | Revised UI with drag-and-drop slot interface |

## Usage

Open either `.html` file directly in a browser. No build step or server needed.

## Files

- `dna_spec.html` — v1 prototype.
- `dna_spec_v2.html` — v2 with improved UI.
- `README.md` — this file.
