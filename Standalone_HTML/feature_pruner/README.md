# feature_pruner

A standalone HTML tool for manually cleaning duplicate GFF3 annotations. Load a GFF3 and optionally its FASTA, review matching features together, uncheck unwanted copies, and download a cleaned GFF3. Designed for plasmids with tens to hundreds of features; no server, installation, or build step is required.

Typical use case: a Benchling sequence has accumulated multiple copies of the same annotation. After exporting and converting to GFF3 (for example with [gb2gff_fna](../../CLI_tools/gb2gff_fna/)), choose which copies to keep without rewriting their attributes.

## Features

- Groups features by sequence ID, type, strand, and exact coordinates, regardless of their IDs, names, source, score, or CDS phase
- Every feature starts checked; individual checkboxes, **Keep only this**, **Keep all**, and **Undo** control retention
- Search across names, IDs, sources, and attributes; filter by type, duplicate status, or keep/remove status
- **Keep only this** acts on the entire duplicate group, even if some copies are hidden by filters; the table header checkbox acts only on visible features
- Small clickable sequence overview and an attribute inspector with the original GFF3 lines
- Keeps multipart features together: rows sharing an ID are one checkbox, and matching compares the complete set of segment coordinates
- Checks `Parent` and `Derives_from` references before export and can restore required features that were unchecked
- Preserves retained feature lines, IDs, attributes, order, comments, directives, line endings, and embedded FASTA
- Accepts multiple sequences in one GFF3/FASTA pair; FASTA is used only for lengths and ID checks
- Built-in synthetic plasmid example
- Entirely offline, with no external dependencies, uploads, or persistent browser storage

## Usage

1. Open `feature_pruner.html` directly in a modern browser.
2. Drop one GFF3 and its FASTA together, or select them with **Open files**. You can also load the GFF3 first and add its FASTA later.
3. Use **Duplicates only** to narrow the table. Click a feature name to compare its source, attributes, and original lines.
4. Uncheck unwanted features, keeping at least one representative where appropriate. **Keep only this** is a shortcut for choosing a representative within a group.
5. Resolve any missing-reference warning, then choose **Download cleaned GFF3**. The filename is `*.cleaned.gff3`.

The original files are not modified. FASTA does not need to be exported again because the sequence is unchanged. Selection changes stay in the current tab; download the output before closing it.

## Matching and limitations

- Matching locations are candidates for review, not proof of biological equivalence. Different names, products, CDS phases, or other qualifiers can appear within one group. Attributes from removed features are **not merged** into the retained copy.
- A `gene` and its `CDS` remain separate because their types differ. Overlapping annotations with different boundaries are not grouped.
- Rows sharing an ID are treated as segments of one feature, following GFF3 conventions. They cannot be unchecked independently. Conflicting reuse of an ID across sequence IDs, feature types, or strands is rejected.
- Retained references to unchecked parents/derivation targets block export. **Restore required features** follows these references recursively. References already missing from the input require source correction or removal of the referring feature. References are never redirected to a different duplicate automatically.
- FASTA sequence IDs must match the GFF3 sequence IDs. Missing FASTA IDs produce a warning; those features are still retained. Without FASTA, the overview uses the GFF3 sequence-region end or the maximum feature coordinate.
- Circular features extending past the FASTA length produce a warning and wrap in the overview. Their original GFF3 coordinates are preserved.
- Input must be uncompressed UTF-8 GFF3/FASTA, up to 30 MB per file. This is a small manual review tool, not a general GFF3 repair or validation suite. GTF attributes and malformed feature lines are rejected.

## Testing

The dependency-free Node harness exercises the page's actual JavaScript, including duplicate matching, multipart features, relationship checks, file-load ordering, selection changes, and lossless export.

```bash
cd Standalone_HTML/feature_pruner
node test/harness.mjs
```

Manual browser smoke test: open the HTML, choose **Try a sample**, toggle **Duplicates only**, use **Keep only this**, verify **Undo**, inspect a feature, and download the result. All sample features initially remain checked.

## Files

- `feature_pruner.html` — the complete application.
- `test/harness.mjs` — regression tests against the embedded JavaScript.
- `README.md` — this file.
