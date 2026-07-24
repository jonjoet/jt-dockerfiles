# gb2gff_fna — forward hardening: phase fix, AGAT removal, genomic-grade GFF3

**Date:** 2026-07-24
**Status:** Scoped, pending review → implementation plan
**Location:** `CLI_tools/gb2gff_fna/`
**Extends:** `2026-06-13-gb2gff_fna-design.md` (the original one-way design)
**Evidence:** `CLI_tools/gb2gff_fna/verify_2026-07-24/` — `RUN.txt` (provenance),
`RESULTS.md` (findings §1–§11), probe scripts. All claims below marked *verified*
were tested in Docker against the committed tree at `f4b251a`.

> **Reviewer: please read "Request to reviewer" (below) before planning.** This
> document deliberately states findings and open questions rather than a chosen
> implementation. The implementation plan is yours to write.

## Context

`gb2gff_fna` converts GenBank → GFF3 + nucleotide FASTA. Work began as a
*bidirectional* proposal (adding FASTA + GFF3 → GenBank), and the investigation
for that turned up three problems in the **existing forward tool**. The reverse
direction was then **dropped by the author**: they do not want to generate
GenBank files, and will use a direct GFF→Benchling uploader for anything that
needs to land in Benchling. See "Superseded scope" for what was learned.

What remains is a focused hardening of the forward converter.

**Goal, in the author's words:** *the best GFF3 we can get from GenBank files*,
and it must **work on genomic GenBank**, not only Benchling plasmid maps.

That second clause is a real change from the original design, which treated
genomic input as a non-priority and deferred genome-grade handling as YAGNI.

## Confirmed findings (verified — do not re-litigate, but do re-verify if cheap)

**F1 — `cds_phases()` double-reverses on minus-strand multi-segment CDS.**
`gb2gff_fna.py:77-96`. The docstring assumes `parts` arrive in genomic
left-to-right order and re-reverses when `strand == -1`. False: Biopython's
GenBank parser already stores `complement(join(...))` parts in biological
(extraction) order, so the function reverses a second time and emits wrong
phases. Verified: `complement(join(11..41,55..89))` → `parts[0]=55..89 (35bp)`,
`parts[1]=11..41 (31bp)`; correct phases `[0, 1]`, actual `[2, 0]`. Plus-strand
control unaffected. (`RESULTS.md` §4, `probe_phase2.py`.)

**Trap:** segment lengths that are multiples of 3 **mask this entirely** — a first
probe using 36bp/30bp segments produced a false pass. Any regression test must
use non-multiples of 3.

**F2 — the image is severely stale, and the cause is channel order.**
Currently Python **3.6.15** (EOL 2021) with Biopython **1.70** (2017). The
Dockerfile installs `-c bioconda -c conda-forge`; bioconda's `biopython` build is
stale (1.70, `np112py36_1`) and, being first, wins the solve and drags Python to
3.6. **agat was never the constraint.** Listing `conda-forge` first (the order
bioconda's own docs recommend) resolves cleanly to modern versions.
(`RESULTS.md` §6.)

**F3 — AGAT is expensive and its removal is measured.**
| | packages | download |
|---|---|---|
| with agat | 229 | 305 MB |
| without agat, with gffutils | **45** | **64 MB** |

AGAT drags Perl, BioPerl and **R** (`r-base` alone 27MB) to support a
`--validate` flag the README already tells users to leave **off**, because AGAT
is gene-model-centric and *drops* features that don't fit a gene model —
including the `rep_origin`/`primer_bind`/`misc_feature` features that make up most
of a plasmid map. (`RESULTS.md` §9.)

**F4 — the modern environment is verified functional and output-identical.**
Built Python 3.11.15 + Biopython 1.87 + gffutils 0.14 (no agat) and ran the
**unmodified** committed script on `example/plasmid_benchling.gb`: `.fna` and
`.gff3` are **byte-identical** (matching md5s) to the Python 3.6 / Biopython 1.70
output. The main risk of a 17-release Biopython jump is retired *for that
fixture*. (`RESULTS.md` §11.)

**Scope limit, stated plainly:** that is one 60bp synthetic fixture — plus strand,
single-segment CDS, one origin-crossing `rep_origin`. It does **not** establish
invariance for genomic input or minus-strand split CDS.

## Scope — three pieces

Intended to land as independently verifiable commits, in this order.

### Piece 1 — fix `cds_phases()` (F1)
Process `parts` in their existing (already biological) order; drop the
strand-based reversal. Correct the misleading docstring.

This **changes output** for minus-strand multi-segment CDS. That is the point —
it is a correctness fix, not cosmetics — but it means "output unchanged" is the
wrong acceptance test for this commit. Ground truth must be computed
independently, not diffed against current behavior.

### Piece 2 — modernize the image, remove AGAT, add gffutils (F2, F3)
- Reorder channels to `-c conda-forge -c bioconda` and pin `python`/`biopython`
  explicitly. Verified working: Python 3.11 / Biopython 1.87.
- Remove `agat`; add `gffutils`.
- Remove `--validate`'s AGAT implementation: `run_agat_validate()`
  (`gb2gff_fna.py:226-264`), the README's "`--validate` caveat" section, and
  `VALIDATE` in `run_gb2gff_fna.sh`.
- `bp_genbank2gff3` disappears with BioPerl; the README mentions its presence, so
  that note goes too.

### Piece 3 — a gffutils-based validator, replacing AGAT's
**Author's decision: an actual replacement is wanted, not just deletion.**

Non-destructive by design — it **reports, never rewrites**. This is the specific
failing of AGAT's pass that motivated replacing it.

Candidate checks (reviewer to confirm/extend):
- the emitted GFF3 reparses cleanly under `gffutils`;
- every `Parent` reference resolves;
- coordinates lie within the declared `##sequence-region` bounds;
- same-`ID` discontinuous row groups are internally consistent (same seqid, type,
  strand);
- CDS rows carry a valid phase (`0`/`1`/`2`).

**Subtlety the reviewer must handle:** this tool *intentionally* emits repeated
`ID`s for discontinuous features (origin-crossing, spliced CDS). `gffutils` treats
duplicate IDs as a condition to merge/rename/error over — verified: it renames the
second row to `<id>_1` and never reconstructs the group. A validator naively
built on `create_db(merge_strategy="error")` would therefore flag *correct* output
as invalid. Note `attributes["ID"]` retains the original value on all rows and is
the stable grouping key. (`RESULTS.md` §7, §8.)

## Request to reviewer

The author has asked that **codex audit the forward converter and write the
implementation plan**. Two specific asks:

**A. Audit `gb2gff_fna.py` for further latent bugs of the same class as F1** —
defects the single 60bp plus-strand fixture cannot exercise. F1 sat in committed,
working-looking code and was invisible to the example. Areas that have *not* been
independently verified: compound-location handling generally, `/codon_start`
values other than 1, unusual strand values (`0`/`None`), `make_unique()` collision
behavior, `normalize_ids()` against real accessions, and attribute escaping
round-trip fidelity. Report findings before fixing.

**B. Weigh the "genomic GenBank" quality questions below**, which the rescope
opened and which are genuinely undecided.

### Open question G1 — CDS should probably parent to mRNA, not gene
**Unverified observation, flagged for evaluation — I did not test this against a
real genomic record.** Reading `gb2gff_fna.py:169-172`, `gene_index` is populated
only from features of `type == "gene"`. At `:188-192`, any CDS/mRNA/tRNA/rRNA/exon
sharing a `locus_tag` is parented to that **gene**. For a eukaryotic genomic
record carrying `gene` + `mRNA` + `CDS` with a shared `/locus_tag`, that yields
`CDS Parent=<gene>`, where GFF3/SO convention wants `CDS Parent=<mRNA>`.

If correct, this is a real quality defect for genomic input and directly in scope
for "the best GFF3 we can get". Note it would be *fixing* a link GenBank actually
asserts, not inventing structure.

### Open question G2 — how far to go toward a gene model, without inventing one
There is a spectrum, and the author has already ruled out the far end:
- correctly parenting CDS to an **existing** mRNA (G1) — not invention;
- emitting explicit `exon` rows derived from an mRNA/CDS `join()` — borderline;
  genome tools often expect them, GenBank rarely states them;
- synthesizing an `mRNA` level where none exists — **ruled out**. GenBank's table
  is flat, relationship is implied by `/locus_tag`, and splicing lives inside a
  single feature's location. Inventing mRNA is exactly what the README faults
  `bp_genbank2gff3` for.

Reviewer to recommend where to stop.

### Open question G3 — alternative splicing / repeated locus_tag
Multiple CDS or mRNA features sharing one `/locus_tag` (isoforms) currently get
uniquified IDs via `make_unique()` and all parent to the same gene. Whether that
is adequate for genomic input is untested.

### Open question G5 — origin-spanning features: row order is load-bearing
**Verified** (`RESULTS.md` §12, `probe_origin_cds.py`). Two parts:

*Settled:* the F1 phase bug **does** reach origin-spanning minus-strand CDS —
`complement(join(70..89,1..25))` gives expected `[0,2]`, actual `[1,0]`. It is the
same bug, and the F1 fix handles it correctly. Plus-strand wraps are unaffected.
Worth a fixture, not a separate fix.

*Open:* for a discontinuous feature the **GFF3 row order carries the segment
order**, and for an origin-spanning feature that order is necessarily *not*
ascending by start coordinate:

```
CDS  76..90  phase=0  ID=wrap_plus
CDS   1..30  phase=0  ID=wrap_plus
```

Any downstream normalizer that sorts rows by `(seqid, start)` — a very common
operation — reorders these, changing which segment is first and therefore which
phase applies where. Where segment lengths are not multiples of 3 the phases
differ and sorting **silently corrupts** the feature. This is a live risk for the
author's stated downstream path, a GFF→Benchling uploader, and is another reason
AGAT's normalizing pass was a poor fit.

There may be a spec-sanctioned alternative: GFF3 arguably permits an end
coordinate **beyond the landmark length** for a landmark marked `Is_circular`
(one row, `76..120` on a 90bp circular molecule) — sort-stable, unambiguous, one
phase. **This has not been verified against the spec text and is not asserted.**

Reviewer to decide: keep the discontinuous form and document the ordering
constraint (possibly having the validator warn that such features are
order-sensitive), adopt the beyond-length form for circular landmarks, or emit
both behind a flag. Note this interacts directly with the retained `Is_circular`
work.

### Open question G4 — no genomic fixture exists
Every verification so far used a 60bp synthetic plasmid. "Works on genomic
GenBank" cannot be claimed without a genomic fixture — minimally a multi-record
prokaryotic record with `gene`+`CDS` on both strands, a minus-strand split CDS,
and ideally a eukaryotic record exercising `gene`→`mRNA`→`CDS`. Sourcing or
constructing this is part of the work.

## Retained from the bidirectional design (still wanted)

- **`Is_circular=true`** on the record's region/`source` line when the GenBank
  LOCUS is circular. Originally motivated by round-tripping; retained on the
  author's instruction — *"we want to keep circular sequences circular"* — and
  independently useful to a downstream GFF→Benchling uploader, which needs to
  know a plasmid is circular.
- **Synthesize a full-length `region` line when no `source` feature exists**, so
  `Is_circular` always has a carrier. Without this, a circular record lacking a
  `source` feature silently loses its topology.

## Testing requirements

Per repo conventions: no host installs; Docker only; map only directories inside
the tool directory; every run directory gets a `RUN.txt` written before the first
command.

- **Piece 1:** minus-strand split CDS with segment lengths **not** multiples of 3,
  asserted against independently computed ground truth. Plus-strand split control
  unchanged. Example fixture unchanged (it has no minus-strand split CDS).
- **Piece 2:** assert Python ≥ 3.11 / Biopython ≥ 1.81 / gffutils present, agat
  absent. Forward output byte-identical for the example fixture (already shown
  once at F4 — re-confirm in the real image). Confirm `--validate` no longer
  invokes AGAT.
- **Piece 3:** validator passes on correct output **including** discontinuous
  same-`ID` features; fails loudly on a deliberately corrupted file (dangling
  `Parent`, out-of-bounds coordinate, bad phase).
- **Genomic:** whatever fixture G4 produces, exercised end-to-end.

## Out of scope

- Generating GenBank from GFF3/FASTA — dropped; see Superseded scope.
- Synthesizing an `mRNA` level not present in the source (G2).
- Embedded-FASTA (`##FASTA`) single-file output.
- Per-record split output files.

## Superseded scope — the bidirectional proposal (archival)

Retained because it explains the findings above and why the rescope happened.

The original plan added `gff_fna2gb.py` (FASTA + GFF3 → GenBank) in the same
image behind a `reverse` keyword. It was reviewed by codex, which returned
REQUEST CHANGES; **four load-bearing assumptions proved false on testing**, and
the investigation is what surfaced F1–F3.

- **`bcbio-gff` rejected.** Does not merge repeated-`ID` rows into a
  `CompoundLocation` (verified: `ori_wrap` returns as two features); nests
  `Parent` children into `sub_features` that would have to be re-flattened; sorts
  records by seqid; invents phantom records for unmatched seqids
  (`create_missing=True`). (`RESULTS.md` §1–§3.)
- **`gffutils` initially rejected, then partly reinstated.** It likewise cannot
  represent a discontinuous feature (`Feature` has scalar `start`/`stop`), so no
  `merge_strategy` reconstructs `join(55..60,1..5)`. But the first evaluation
  wrongly generalized from that to "no benefit", under an incorrect
  *plasmid-only* scope assumption. Once genomes entered scope, `db.children()`
  proved to handle `Parent`-based spliced CDS well — verified on both strands with
  phases intact. It survives the rescope as the **validator** in Piece 3.
  (`RESULTS.md` §7–§8.)
- **Neither library collapses merged rows to a min/max span** — the dangerous
  `1..60` outcome (silently inverting an origin-spanning feature into its
  complement) does not occur.
- **Round-trip fidelity was inherently limited**: a FASTA+GFF3 pair cannot carry
  topology, `molecule_type`, fuzzy/`between`/`one-of` positions, `join` vs `order`,
  remote references, or record-level metadata (ACCESSION, REFERENCES, COMMENT…).
  It would have been a sequence + feature-table round trip, never a lossless one.

Two general lessons worth keeping:
1. **Library behavior was asserted from memory and was wrong** on the single most
   important detail. Probe the parser before designing against it.
2. **A passing probe can be a false pass** — the 36bp/30bp phase probe.
