# fasta_gff_combiner

A standalone HTML tool for assembling **composite genomes** from sequences spread across multiple FASTA files (with their optional GFF annotations). Load several FASTAs and GFFs, define one or more named outputs, tick which sequences belong in each, and export combined `.fasta`/`.gff` files — all client-side, no server or installation.

Typical use case: you have a bacterial chromosome in one FASTA and a handful of plasmids in others, and you want to produce a single multi-record genome (or several strain variants) that bundles the chromosome with the right plasmids — with the GFF annotations following along correctly.

## Why not just `cat`?

Concatenating FASTAs by hand breaks the moment two sequences share a name, and stitching GFFs together leaves seqids and `##sequence-region` directives out of sync with the new files. This tool handles the parts that plain concatenation can't:

- **Name-collision handling** — if two different sequences would share a name within the same output (an invalid FASTA/GFF), it's flagged per-output. Toggle **auto-disambiguate** (appends the source-file stem, plus a counter if needed) or rename sequences inline.
- **GFF seqid sync** — annotations are matched to sequences by seqid; when a sequence is renamed, its features' seqid column is rewritten to match the FASTA header.
- **Regenerated directives** — each output GFF gets a clean `##gff-version 3` plus freshly computed `##sequence-region` lines (from the actual sequence lengths), instead of stale concatenated headers.

## Features

- Two multi-file drop zones (FASTA, GFF); files **accumulate** across multiple uploads
- All sequences pooled into one sortable table (name, source file, length + bar, GC% + bar, matched feature count)
- Define any number of **outputs**; a checkbox **matrix** assigns sequences to outputs
  - a sequence can go into several outputs, but can't be duplicated within a single output
  - per-output "select all (visible)", live sequence/bp/feature counts, and collision warnings
- Sequences export in the table's current sort order (sort by length to put the chromosome first)
- Inline sequence renaming + global auto-disambiguation
- Orphan-feature warning for GFF seqids that match no loaded sequence (these are excluded)
- One-click **Download all (.zip)** (a dependency-free, store-only ZIP writer keeps it a single portable file), plus per-output FASTA/GFF download buttons
- Runs entirely in the browser — no data leaves your machine

> **Note on auto-disambiguate:** it makes export names *globally* unique, so a given source sequence always exports under one consistent name across every output (e.g. `chr1` → `chr1.chromosome` everywhere), even in outputs where it wouldn't have collided.

## Usage

Open `fasta_gff_combiner.html` directly in a browser (or serve via `python3 -m http.server`). No build step needed.

## Testing

`test/` contains small FASTA/GFF fixtures and a Node harness that exercises the page's real
parsing, GFF-rewrite, collision/disambiguation, and ZIP-writer logic against the DOM-free functions:

```
cd Standalone_HTML/fasta_gff_combiner
node test/harness.mjs
```

## Files

- `fasta_gff_combiner.html` — the tool.
- `test/` — fixtures (`chromosome.fasta`, `plasmids.fasta`, `contig_collide.fasta`, `anno.gff3`) and `harness.mjs`.
- `README.md` — this file.
