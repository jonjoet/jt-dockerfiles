# rescount

A standalone HTML tool for counting restriction enzyme cut sites across sequences in a multi-FASTA file. Select enzymes from a built-in database (or type/upload a custom list), and get a matrix of cut counts per sequence per enzyme — no server or installation required.

## Features

- Built-in database of common restriction enzymes with recognition sequences
- Two enzyme selection modes: pick from a searchable grid, or type/upload a list
- Handles IUPAC ambiguity codes and searches both strands (unless the site is palindromic)
- Results displayed as a sortable table
- Export results as CSV
- Runs entirely client-side in the browser

## Usage

Open `resCount.html` directly in a browser. Upload a FASTA file, select your enzymes, and click analyze.

## Files

- `resCount.html` — the tool.
- `README.md` — this file.
