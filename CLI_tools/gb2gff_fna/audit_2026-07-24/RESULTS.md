# Forward-converter audit results — 2026-07-24

Audited committed `gb2gff_fna.py` at `f4b251a`; the converter itself was not
modified. Probes ran in Docker with Python 3.11, Biopython 1.87, and gffutils
0.14. See `RUN.txt` and `probe_forward_edges.py`.

## Confirmed defects

1. **Reserved attribute values are not escaped.** `ID`, `Name`, and `Parent`
   are interpolated raw while ordinary qualifier values use `escape_attr()`.
   A label such as `label;one, 100%` is parsed by gffutils as `ID=label` plus a
   spurious attribute. This also breaks Parent resolution. Seqids use an
   over-broad safe character set (`/` remains unescaped), contrary to GFF3's
   restricted seqid character set.

2. **Biopython strand `0` is serialized as `.`.** Biopython uses `0` for
   relevant-but-unknown strandedness; GFF3 represents that as `?`. `None`
   correctly maps to `.`.

3. **Invalid `/codon_start` values are silently normalized.** Valid 1, 2, and
   3 values produce correct initial phases on plus-strand input. Values 0 and 4
   are modulo-wrapped into apparently valid phases; non-integers silently
   become 1. Invalid source annotations need a named warning and deterministic
   fallback, not silent reinterpretation.

4. **Zero-length Biopython locations produce invalid coordinates.** A location
   `[5:5]` emits GFF coordinates `6 5`; GFF3 requires `start <= end` and
   represents a zero-length site with equal coordinates.

5. **Remote locations are silently attached to the wrong seqid.** A location
   with `ref="REMOTE.1"` is emitted on the containing record's seqid, losing
   the reference. Until remote-location output is designed, the whole feature
   should be skipped with a warning rather than mislocated.

6. **Normalized record IDs are not checked for uniqueness.** Real
   accession.version IDs are preserved correctly (`AB123456.2`), but two
   placeholder accessions with the same LOCUS both become the same seqid,
   yielding duplicate `##sequence-region` directives and ambiguous FASTA/GFF3.

7. **Existing mRNA hierarchy is discarded.** On a real genomic record
   (`AC005021.1`), `gene`, split `mRNA`, and split `CDS` share `/gene=PON2`.
   The current converter parents both mRNA and CDS directly to the gene.
   Synthetic alternative transcripts with distinct `/transcript_id` values
   show the same defect. GFF3 convention is CDS→existing mRNA→gene; direct
   CDS→gene remains allowed when the source has no mRNA.

8. **The one-value `gene_index` is ambiguous and lossy.** It indexes only the
   first of `locus_tag`/`gene`, and later genes overwrite earlier matches.
   Alternative transcripts are assigned unique IDs correctly, but all CDS
   features still parent to the same gene, even when exact transcript IDs can
   disambiguate them.

9. **Valueless GenBank qualifiers are emitted as empty assignments.**
   `/pseudo` becomes `pseudo=`; the interoperable genomic convention is
   `pseudo=true`. Also, `/db_xref` is emitted as the nonstandard `db_xref`
   rather than official GFF3 `Dbxref`.

10. **Unknown GenBank feature keys can make column 3 invalid.** GFF3 requires a
    Sequence Ontology term or accession, but the current fallback passes an
    arbitrary INSDC key through. Preserve the original key as `gbkey` and use
    `sequence_feature` when no verified SO mapping exists.

11. **The current AGAT validation failure cannot affect exit status.**
    `run_agat_validate()` returns false, but `main()` ignores the result and
    still exits zero. The replacement validator must keep the raw file and
    return nonzero on validation errors.

12. **The wrapper contradicts its README.** The README promises container runs
    as the caller, but `run_gb2gff_fna.sh` omits `--user`, so output may be
    root-owned.

## Confirmed correct or acceptable

- `make_unique()` always produces a globally unique ID, including collisions
  with pre-suffixed bases. Its suffixes are not minimal in every case
  (`x_2` can become `x_2_2`), but that is deterministic and not a correctness
  defect.
- Real GenBank accession.version IDs survive `normalize_ids()` unchanged.
- Ordinary qualifier value escaping preserves semicolon, equals, ampersand,
  comma, tab, newline, percent, and list boundaries. The defect is confined to
  explicit reserved values and the seqid safe set.
- Walking `CompoundLocation.parts` in Biopython's existing order is the correct
  general phase rule for plus, minus, and circular locations. `codon_start`
  values 2 and 3 work once validated.

## G1–G5 decisions

- **G1:** Parent a CDS to an existing, unambiguously matched mRNA; parent that
  mRNA to the gene. `AC005021.1` is a real counterexample to the current code.
- **G2:** Stop at relationships supported by existing features. Do not
  synthesize mRNA or exon rows. Direct CDS→gene is valid when no mRNA exists.
- **G3:** Match exact shared `transcript_id` first, then a single compatible
  mRNA sharing `locus_tag`/`gene`. If multiple candidates remain, warn and
  fall back to the gene; do not choose the last feature or invent a link.
- **G4:** Add both a deterministic synthetic genomic edge-case fixture and a
  vendored, checksum-pinned `AC005021.1` fixture. The latter exercises a real
  minus-strand nine-part mRNA/CDS and CDS→mRNA parenting.
- **G5:** The official GFF3 circular-genome section explicitly sanctions
  virtual coordinates beyond the landmark length. Emit a single virtual row
  for an exactly contiguous two-part origin wrap. A genuinely discontinuous or
  spliced origin-crossing feature cannot be collapsed without adding sequence;
  retain its rows and add `part=X/Y` in biological order. The validator must
  allow one-turn virtual coordinates only when the full-length region has
  `Is_circular=true`, and must validate complete `part` numbering.

The G5 assertion that row order alone is the formal segment-order mechanism is
too strong: GFF3 does not guarantee that a generic coordinate sort preserves
biological order, and phase remains attached to its own row. Explicit `part`
metadata plus the circular virtual-coordinate convention makes the ordering
recoverable without relying solely on file order.

## Known representational losses to document

Fuzzy/unknown positions, `join` versus `order`, and remote references do not
have a complete mapping in the current scope. Exact fuzzy-position preservation
can be a later NCBI-compatible `partial`/`start_range`/`end_range` enhancement;
the immediate implementation should warn rather than silently claim full
fidelity where it cannot preserve semantics.
