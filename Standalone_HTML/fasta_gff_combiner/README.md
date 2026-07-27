# fasta_gff_combiner

A standalone HTML tool for assembling **composite genomes** from sequences spread across multiple FASTA files (with their optional GFF annotations). Load several FASTAs and GFFs, define one or more named outputs, tick which sequences belong in each, and export combined `.fasta`/`.gff` files — all client-side, no server or installation.

Typical use case: you have a bacterial chromosome in one FASTA and a handful of plasmids in others, and you want to produce a single multi-record genome (or several strain variants) that bundles the chromosome with the right plasmids — with the GFF annotations following along correctly.

## Why not just `cat`?

Concatenating FASTAs by hand breaks the moment two sequences share a name, and stitching GFFs together leaves seqids and `##sequence-region` directives out of sync with the new files. This tool handles the parts that plain concatenation can't:

- **Name-collision handling** — if two different sequences would share a name within the same output (an invalid FASTA/GFF), it's flagged per-output. Toggle **auto-disambiguate** (appends the source-file stem, plus a counter if needed) or rename sequences inline.
- **Source-aware GFF matching** — unique seqids match automatically. If a seqid occurs in more than one FASTA record, the page asks which exact record a GFF file annotates instead of copying annotations onto every duplicate.
- **GFF seqid sync** — when a sequence is renamed, its matched features' seqid column is rewritten to match the FASTA header.
- **Opt-in GFF ID namespacing** — when independent GFF inputs reuse feature IDs, the tool can give every input a visible, unique prefix and rewrite `ID`, `Parent`, and `Derives_from` together. Unresolved or ambiguous relationships block export rather than being guessed.
- **Regenerated directives** — each output GFF gets a clean `##gff-version 3` plus full-length `##sequence-region` lines computed from the exported FASTA. Source subranges are not preserved; the page warns before replacing a non-full-length declaration.

## Features

- Two multi-file drop zones (FASTA, GFF); files **accumulate** across multiple uploads
- All sequences pooled into one sortable table (name, source file, length + bar, GC% + bar, matched feature count)
- Define any number of **outputs**; a checkbox **matrix** assigns sequences to outputs
  - a sequence can go into several outputs, but can't be duplicated within a single output
  - per-output "select all (visible)", live sequence/bp/feature counts, and collision warnings
- Sequences export in the table's current sort order (sort by length to put the chromosome first)
- Inline sequence renaming + global auto-disambiguation
- Line-numbered FASTA/GFF3 validation; GTF input is rejected because it is not silently convertible to GFF3
- Output-level checks for ambiguous annotation assignments and conflicting GFF3 feature IDs
- Orphan-feature warning for GFF seqids that match no loaded sequence (these are excluded)
- One-click **Download all (.zip)** (a dependency-free, store-only ZIP writer keeps it a single portable file), plus per-output FASTA/GFF download buttons
- Runs entirely in the browser — no data leaves your machine

> **Note on auto-disambiguate:** it makes export names *globally* unique, so a given source sequence always exports under one consistent name across every output (e.g. `chr1` → `chr1.chromosome` everywhere), even in outputs where it wouldn't have collided.

> **Note on GFF ID namespacing:** this option is off by default and activates only when the loaded, matched annotations reuse an `ID` across GFF files. Once active, every matched input GFF is treated as an independent namespace so its complete feature graph remains internally consistent. Use it when the GFFs were generated independently. References to a unique ID in another GFF are rewritten to that GFF's prefix; missing or ambiguous targets block export. `Name`, `Alias`, and `Target` values are never changed.

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
