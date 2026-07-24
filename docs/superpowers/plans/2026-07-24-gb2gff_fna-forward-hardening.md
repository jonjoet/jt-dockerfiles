# gb2gff_fna forward-hardening implementation plan

**Date:** 2026-07-24
**Status:** Ready for implementation
**Design:** `docs/superpowers/specs/2026-07-24-gb2gff_fna-forward-hardening-design.md`
**Audit:** `CLI_tools/gb2gff_fna/audit_2026-07-24/RESULTS.md`

## Outcome

Harden the existing GenBank → GFF3 + FASTA converter for genomic as well as
plasmid records:

- correct CDS phases on every strand and compound-location shape;
- preserve circular topology and represent origin wraps without depending only
  on row order;
- emit valid escaped identifiers, coordinates, strands, attributes, types, and
  hierarchy;
- modernize the image to Python 3.11/Biopython 1.87, remove AGAT, and add
  gffutils;
- replace AGAT's destructive standardizer with a non-destructive validator that
  reports errors and never rewrites the GFF3.

The audit found converter defects beyond the original three pieces. They belong
in the hardening work because the new validator would otherwise reject output
the converter can currently produce.

## Decisions resolving G1–G5

1. **Existing hierarchy only.** Parent an existing mRNA to its gene and an
   existing CDS/exon to its unambiguous mRNA. A CDS may parent directly to a
   gene when the GenBank record has no matching mRNA, as explicitly allowed by
   GFF3 NOTE 2. Do not synthesize mRNA or exon features.
2. **Alternative transcripts.** Match by exact shared `transcript_id` first,
   then by a unique strand/location-compatible mRNA sharing `locus_tag` or
   `gene`. If more than one candidate remains, warn and fall back to the gene;
   never choose the last indexed feature arbitrarily.
3. **Fixtures.** Check in a deterministic synthetic genomic edge-case fixture
   and the real NCBI `AC005021.1` record with URL, retrieval date, and SHA-256.
   The real record contains a minus-strand nine-part PON2 mRNA/CDS and proves
   that CDS→gene is currently produced where CDS→mRNA is possible.
4. **Origin wraps.** Follow the official GFF3 circular-genome convention:
   collapse an exact two-part boundary wrap into one virtual-coordinate row
   whose end exceeds the landmark length. Do not collapse a gapped/spliced
   wrap. Emit those parts separately with `part=X/Y` in Biopython biological
   order. Emit `part` on all multi-segment features so a coordinate sort does
   not erase segment order.
5. **Circular validation.** Permit at most one turn of virtual coordinates only
   when the seqid has a full-length `region` with `Is_circular=true`.

References:

- [Sequence Ontology GFF3 specification](https://github.com/The-Sequence-Ontology/Specifications/blob/master/gff3.md)
- [NCBI GFF3 data model and circular-coordinate examples](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/reference-docs/file-formats/annotation-files/about-ncbi-gff3/)
- [NCBI AC005021.1 GenBank record](https://www.ncbi.nlm.nih.gov/nuccore/AC005021.1)

## Final file set

| File | Planned change |
|---|---|
| `CLI_tools/gb2gff_fna/gb2gff_fna.py` | Converter correctness, hierarchy, topology, virtual wraps, validator |
| `CLI_tools/gb2gff_fna/Dockerfile` | Modern pinned Python/Biopython, gffutils, no AGAT |
| `CLI_tools/gb2gff_fna/run_gb2gff_fna.sh` | New validator wording and caller UID/GID |
| `CLI_tools/gb2gff_fna/README.md` | Genomic behavior, validator, hierarchy, circular and loss caveats |
| `README.md` | Remove the plasmid-only description |
| `CLI_tools/gb2gff_fna/tests/test_converter.py` | Pure conversion/unit regressions |
| `CLI_tools/gb2gff_fna/tests/test_validator.py` | Valid and corrupted GFF3 cases |
| `CLI_tools/gb2gff_fna/tests/run_tests.sh` | Docker-only test runner and run provenance |
| `CLI_tools/gb2gff_fna/tests/fixtures/genomic_edge_cases.gb` | Deterministic multi-record edge fixture |
| `CLI_tools/gb2gff_fna/tests/fixtures/AC005021.1.gb` | Real genomic regression fixture |
| `CLI_tools/gb2gff_fna/tests/fixtures/README.md` | Fixture provenance and checksums |

## Implementation sequence

### Commit 1 — Add regression fixtures and a Docker-only test harness

1. Add `tests/run_tests.sh`. It must:
   - create a run directory under `CLI_tools/gb2gff_fna/tests/runs/`;
   - write `RUN.txt` before the first Docker command;
   - build a dedicated `gb2gff_fna:test` image;
   - mount only directories under `CLI_tools/gb2gff_fna`;
   - never map host `/tmp`;
   - run the Python unit tests through the micromamba entrypoint.
2. Add a static `genomic_edge_cases.gb` fixture containing:
   - two records to exercise seqid handling;
   - plus- and minus-strand split CDS features whose segment lengths are not
     multiples of three;
   - valid `codon_start` values 1, 2, and 3;
   - gene→mRNA→CDS with two transcript IDs under one locus;
   - a prokaryotic gene→CDS with no mRNA;
   - strand `0` and `None` non-CDS features;
   - a circular record with no source feature;
   - an exact contiguous origin wrap and a gapped origin-spanning CDS;
   - labels/IDs containing semicolon, comma, percent, space, and ampersand;
   - a zero-length site feature.
3. Vendor `AC005021.1` unchanged from NCBI. Record its retrieval URL/date and
   SHA-256; tests must not access the network.
4. Add tests that describe desired behavior, even where they initially fail.
   Ground-truth phases must be literal expected arrays, not values computed by
   calling converter helpers.

Verification:

- The harness obeys the repository mount rule and records provenance.
- Baseline plasmid output remains captured for later byte comparison.
- The new tests fail specifically on the audited defects, not on fixture syntax.

### Commit 2 — Correct converter semantics

#### 2.1 IDs, names, escaping, and types

1. Split escaping helpers by GFF3 field:
   - seqid uses exactly the GFF3-safe set
     `[A-Za-z0-9.:^*$@!+_?-|]`;
   - attributes percent-encode delimiters/control characters;
   - explicit `ID`, `Name`, `Parent`, `Is_circular`, and `part` values pass
     through the same attribute-value encoder as qualifiers.
2. Preserve comma as a separator only between independently escaped list
   values.
3. Map `/note`→`Note` and `/db_xref`→`Dbxref`; serialize valueless boolean
   qualifiers such as `/pseudo` as `true`.
4. Add `gbkey=<original GenBank feature type>` without mutating the Biopython
   feature. Extend the verified INSDC→SO map; if a key has no verified SO
   mapping, emit `sequence_feature`, retain `gbkey`, and warn instead of placing
   a non-SO token in column 3.
5. Make display names and ID bases type-aware:
   - gene: label, gene, locus_tag;
   - mRNA/RNA: label, transcript_id, product, gene, locus_tag;
   - CDS: label, protein_id, product, gene, locus_tag;
   - other: existing label/gene/product/locus_tag fallback.
   Continue using `make_unique()` globally; its collision algorithm is correct.
6. After placeholder normalization, reject duplicate record IDs with a clear
   error naming the duplicate. Preserve real accession.version IDs unchanged.

#### 2.2 Locations, phase, and strand

1. Rewrite `cds_phases()` to walk `parts` exactly in Biopython order. Remove
   strand reversal and correct the docstring.
2. Accept only integer `codon_start` values 1–3. On a missing value use 1; on an
   invalid present value warn with record/feature context and use 1.
3. Map strand `1`→`+`, `-1`→`-`, `0`→`?`, and `None`→`.`.
4. Convert a zero-length Biopython site to equal GFF3 start/end coordinates.
5. Preflight every part before emitting any row for a feature:
   - if a part has a remote `ref`/`ref_db`, warn and skip the whole feature;
   - if an endpoint cannot be converted to an integer, warn and skip the whole
     feature;
   - do not emit a partially converted compound feature.
6. Keep integer approximations for supported fuzzy endpoints but warn once per
   affected feature and document that exact fuzziness is not preserved.

#### 2.3 Circular landmarks and segment order

1. Identify a full-length source feature per record. Map it to `region`, add
   `gbkey=Src`, and add `Is_circular=true` when
   `record.annotations["topology"] == "circular"`.
2. If no source spans the full record (including the no-source case), emit a
   synthetic full-length landmark region before other features. Preserve any
   partial source features separately.
3. For an exact two-part boundary wrap on a circular record:
   - plus: high part ends at record length and low part starts at zero;
   - minus: biological first part starts at zero and the other ends at length;
   emit one row from the high-part start through `length + low-part end`.
   A CDS uses the phase of its biological first part.
4. For every remaining compound feature, emit each part with the same ID plus
   `part=1/N ... N/N` in biological order. Do not collapse a gapped or spliced
   wrap.
5. Warn for a record with no features, matching the original documented
   behavior.

#### 2.4 Existing hierarchy without synthesis

1. In the first pass, assign IDs to all features before building relationships.
2. Index genes and mRNAs to lists, not single overwritten values, under every
   non-empty `locus_tag`, `gene`, and `transcript_id` that applies.
3. Parent resolution:
   - mRNA/tRNA/rRNA/ncRNA→unique matching gene;
   - CDS/exon→exact matching mRNA by `transcript_id`;
   - otherwise CDS/exon→one strand/location-compatible mRNA sharing
     `locus_tag`/`gene`;
   - otherwise CDS/exon→unique matching gene;
   - ambiguity→warning plus gene fallback or no Parent.
4. Never synthesize mRNA/exon rows and never infer multiple parents merely from
   overlap.

Verification:

- All converter tests pass in the old and modern Biopython environments except
  for explicitly version-gated behavior.
- `AC005021.1` emits mRNA Parent=gene and CDS Parent=mRNA, with correct
  minus-strand phases.
- The plasmid fixture differs only in intentional additions/changes:
  `gbkey`, circular landmark metadata, and virtual origin-wrap representation.
- gffutils reparses labels and Parent IDs containing reserved characters to
  their original decoded values.

### Commit 3 — Modernize the image and remove AGAT

1. Change channel order to `-c conda-forge -c bioconda`.
2. Pin:
   - `python=3.11`;
   - `biopython=1.87`;
   - `gffutils=0.14`.
3. Remove `agat` and update Dockerfile comments.
4. Remove `shutil`, `subprocess`, `run_agat_validate()`, and the AGAT-backed
   `--validate` behavior.
5. Temporarily remove the CLI flag and wrapper variable in this commit so there
   is no flag that silently does nothing; Commit 4 restores the same public name
   with new semantics.
6. Update the AGAT/BioPerl dependency notes in the README, leaving the full
   validator documentation for Commit 4.

Verification:

- Image reports Python 3.11.x, Biopython 1.87, and gffutils 0.14.
- `agat_convert_sp_gxf2gxf.pl`, `bp_genbank2gff3`, and the Python `BCBio` module
  are absent.
- Converter and genomic fixture tests pass in the final image.
- Record package count/image size for handoff, without making size a brittle
  exact test.

### Commit 4 — Add the non-destructive gffutils validator

1. Reintroduce `--validate` with the description “validate and report; never
   rewrite output.”
2. Implement `validate_gff(path)` using
   `gffutils.create_db(..., dbfn=":memory:", merge_strategy="create_unique",
   disable_infer_genes=True, disable_infer_transcripts=True)`.
   `create_unique` is deliberate: repeated original IDs are valid; grouping
   always uses `feature.attributes["ID"]`, not gffutils's renamed database ID.
3. Add explicit semantic checks around the gffutils parse:
   - one valid `##gff-version 3` header;
   - at most one `##sequence-region` per decoded seqid;
   - every feature seqid has a sequence region;
   - nine columns, integer positive coordinates, `start <= end`;
   - linear features stay within bounds;
   - virtual coordinates are allowed only for a circular landmark and no more
     than one sequence length beyond it;
   - strand is `+`, `-`, `.`, or `?`;
   - every CDS phase is 0/1/2 and every non-CDS phase is `.`;
   - every Parent resolves to an original ID and no self/cyclic Parent graph;
   - repeated-ID rows agree on seqid, source, type, strand, and invariant
     attributes;
   - `part=X/Y`, when present, is complete, unique, and covers 1..Y; `part` is
     excluded from invariant-attribute equality;
   - any out-of-bounds virtual feature has a full-length region carrying
     `Is_circular=true`.
4. Collect all diagnostics with line numbers. On failure:
   - retain the generated FASTA and raw GFF3 unchanged;
   - print a concise error list to stderr;
   - exit 1.
   On success, print a validation summary and exit 0.
5. Hash the GFF3 before and after validation in tests to prove the validator is
   non-destructive.
6. Add corrupted fixtures/tests for:
   - dangling Parent;
   - Parent cycle;
   - duplicate sequence-region;
   - linear out-of-bounds and invalid circular virtual coordinates;
   - bad CDS phase and non-CDS phase;
   - inconsistent repeated-ID type/strand;
   - missing/duplicate/inconsistent `part` values.

Verification:

- Correct plasmid and genomic output passes, including duplicate IDs,
  multi-part CDS features, encoded IDs, and virtual circular coordinates.
- Each corrupted case fails for the intended diagnostic.
- Validation never changes the output hash.
- Main returns nonzero on validation failure.

### Commit 5 — Final documentation and wrapper alignment

1. Rewrite the tool README around general GenBank input, retaining Benchling
   behavior as one use case rather than the scope boundary.
2. Document:
   - existing-feature hierarchy policy and ambiguity warnings;
   - no synthetic mRNA/exon;
   - phase and `codon_start`;
   - circular landmark, virtual coordinate, and `part` conventions;
   - validator checks and non-destructive failure behavior;
   - fuzzy/remote/operator limitations;
   - accession.version/seqid behavior.
3. Restore `VALIDATE=0` in the wrapper for the new validator and add
   `--user "$(id -u):$(id -g)"` to match the README's ownership promise.
4. Update the top-level README row to “GenBank → genomic/plasmid GFF3 +
   nucleotide FASTA with non-destructive validation.”
5. Run the complete Docker test harness from a fresh run directory and record
   image versions, output hashes, and test counts in `RUN.txt`.

## Acceptance checklist

- [ ] Minus-strand split CDS phases match independent literal expectations,
      including non-multiple-of-three segments and codon_start 2/3.
- [ ] Strand 0 emits `?`; None emits `.`.
- [ ] Reserved characters survive a gffutils parse in ID, Name, Parent, and
      ordinary qualifiers.
- [ ] Duplicate normalized seqids fail clearly; real accession.version survives.
- [ ] Zero-length sites are valid; remote/unknown locations warn and do not
      produce mislocated partial output.
- [ ] AC005021.1 CDS parents to its existing mRNA and all nine CDS phases pass.
- [ ] Alternative transcript IDs resolve to their own mRNAs; ambiguity never
      silently picks the last feature.
- [ ] No mRNA or exon is synthesized.
- [ ] Circular records always have a landmark region with Is_circular=true.
- [ ] Exact origin wraps use virtual coordinates; gapped/spliced wraps retain
      parts with complete part=X/Y metadata.
- [ ] Image contains pinned modern Python/Biopython/gffutils and no AGAT/BioPerl.
- [ ] Validator accepts valid repeated IDs and rejects every corruption case.
- [ ] Validator leaves the GFF3 byte-for-byte unchanged.
- [ ] All Docker mounts remain inside `CLI_tools/gb2gff_fna`; host `/tmp` is
      never mapped; every run directory receives `RUN.txt` first.
