# Probe results — 2026-07-24 (see RUN.txt for commit/provenance)

Verifying codex's design-review claims against the bidirectional spec.
gb2gff_fna.py was NOT modified; probes ran against the committed version.

## 1. BCBio.GFF.parse does NOT merge repeated-ID rows  — CLAIM CONFIRMED
Input: real forward output (fwd/plasmid_benchling.gff3), rows 7-8 share ID=ori_wrap.
Env: python:3.11-slim, biopython 1.87, bcbio-gff (pip).
Result: two separate SeqFeatures, each SimpleLocation, compound=False.
  ID=['ori_wrap'] loc=[54:60](+) compound=False
  ID=['ori_wrap'] loc=[0:5](+)   compound=False
=> A coalescing layer is REQUIRED. join(55..60,1..5) will not come back on its own.
Divergence from codex's account: both rows kept ID 'ori_wrap'; no x_2 renaming
observed in this version/path. Core claim unaffected.

## 2. BCBio already percent-decodes attribute VALUES — CLAIM CONFIRMED
Note qualifier parsed as 'constitutive promoter' (source text was
'origin-crossing%20feature' / 'constitutive%20promoter').
=> A local unquote() on values would double-decode. Do NOT add one.

## 3. create_missing=True by default — CLAIM CONFIRMED
Parsing a GFF row with seqid NOT_IN_FASTA against base_dict silently created a
phantom record: ids = ['NOT_IN_FASTA', 'test_plasmid'].
=> The spec's promised "named error" does not happen for free. Prevalidate seqids
   or use GFFParser(create_missing=False).

## 4. cds_phases() double-reverses on minus strand — CLAIM CONFIRMED (pre-existing bug)
Biopython stores complement(join(...)) parts in BIOLOGICAL order:
  complement(join(11..41,55..89)) -> parts[0]=55..89(35bp), parts[1]=11..41(31bp)
cds_phases() reverses again when strand==-1, so:
  expected [0, 1]   got [2, 0]
Plus-strand control join(11..41,55..89): expected [0,2], got [0,2] -> OK.
=> Bug affects minus-strand MULTI-SEGMENT CDS only. Single-segment and plus-strand
   are unaffected, which is why the example fixture never exposed it.
   NOTE: probe_phase.py used 36bp/30bp segments (both divisible by 3) and MASKED
   the bug — segment lengths must not be multiples of 3 to expose it.

## 5. NEW (not from codex): image dependency floor
The existing gb2gff_fna:latest image is Python 3.6 with an old Biopython.
`micromamba install bcbio-gff` into it resolved a bcbio-gff expecting
Bio.SeqFeature.SimpleLocation (Biopython >= 1.81) and crashed:
  AttributeError: module 'Bio.SeqFeature' has no attribute 'SimpleLocation'
=> Adding bcbio-gff is NOT a one-line Dockerfile change; the image needs a
   python/biopython bump, and that bump must be re-verified against the forward
   path (agat pin may fight it).

## 6. Python 3.6 root cause = CHANNEL ORDER (not agat)  — solved
Current image: python 3.6.15, biopython 1.70 (2017!), agat 1.7.0, perl 5.32.1.
The Dockerfile installs with `-c bioconda -c conda-forge`. bioconda's biopython
is stale (1.70, build np112py36_1) and, being first in channel order, wins the
solve — dragging python down to 3.6. agat was never the constraint.

Verified fix — swap to conda-forge first (the order bioconda's own docs
recommend) and pin:
    micromamba create --dry-run -c conda-forge -c bioconda \
        "python=3.11" "biopython>=1.81" agat
resolves cleanly:
    python     3.11
    biopython  1.87   (conda-forge)
    agat       1.7.0  (bioconda — SAME version as the current image)
    229 packages, 305MB total download.
=> The image can be modernized with no loss of agat functionality. This also
   removes the dependency-bump risk that was blocking the reverse feature.

## 7. gffutils evaluated as a bcbio-gff replacement — REJECTED (gffutils 0.14)
Probe: probe_gffutils.py against the same real forward output.

Decisive question was whether it coalesces duplicate-ID rows into a genuine
discontinuous feature. It does not:
  merge_strategy='error'         -> ValueError: Duplicate ID ori_wrap
  merge_strategy='merge'         -> TWO features: ori_wrap (55..60), ori_wrap_1 (1..5)
  merge_strategy='create_unique' -> TWO features: ori_wrap (55..60), ori_wrap_1 (1..5)
Same failure as bcbio-gff: join(55..60,1..5) is not reconstructed.

Structural reason: gffutils.Feature has scalar start/stop and NO parts/segments
concept at all (dir() confirms). A discontinuous feature is not representable in
its data model, so no flag could fix this.

GOOD NEWS (risk ruled out): it does NOT collapse to a min/max span. The feared
1..60 outcome — which would silently invert an origin-crossing feature into its
complement — does not occur. Coordinates are preserved per row.

USEFUL FINDING (applies to ANY library path): when gffutils renames the second
row's feature id to ori_wrap_1, attributes['ID'] still holds the ORIGINAL
'ori_wrap' on both rows. So the correct grouping key is always the ID ATTRIBUTE,
never the library's assigned feature id.

Why it is worse than bcbio-gff here, not better:
- bcbio-gff at least yields Biopython SeqRecord/SeqFeature objects. gffutils
  yields its own Feature type with no Biopython interop, so a full conversion
  layer to SeqFeature/CompoundLocation would be needed ON TOP of the grouping we
  already have to write.
- It builds a SQLite DB — real machinery for a 5-feature plasmid map.
- It unescapes attribute values too, so the double-decode hazard is identical.

Forward direction (GenBank -> GFF3): no benefit. gffutils has no GenBank
knowledge; it could only format output lines (the trivial part we already do),
and would first require constructing gffutils.Feature objects from Biopython
features — more work, not less. It also cannot represent our multi-segment output
as a single object.

What gffutils IS genuinely good at (not our bottleneck): relationship queries
(db.children()/db.parents()) on genome-scale hierarchical annotation, and
dialect detection across GFF2/GTF/GFF3 variants. Revisit ONLY if this tool ever
needs to ingest arbitrary third-party GFF/GTF dialects.

=> Hand-rolled stdlib reader stands.

## 8. CORRECTION to §7 — gffutils ADOPTED for the reverse direction
§7 concluded "no benefit". That conclusion was drawn under a WRONG SCOPE
ASSUMPTION (inherited from the README's "tuned for Benchling plasmid maps" and
never questioned). The user corrected it: this tool is for GENOMES, not just
plasmids, and gffutils is already used across their other pipelines (asat, gcev,
reannot).

§7 also conflated two distinct GFF3 mechanisms. Probe: probe_gffutils_genome.py.

  (a) SPLICED CDS VIA Parent  — the genome standard (NCBI/Ensembl/prokka/bakta):
      multiple CDS rows, distinct/absent IDs, sharing Parent=<mRNA>.
      gffutils handles this NATIVELY and well. Verified:
        mrna1 (+): db.children(order_by=start) -> 101..160, 221..280, 341..400
                   => join(101..160,221..280,341..400)
        mrna2 (-): -> 501..535, 601..631, 701..800  phases ['1','0','0']
                   => complement(join(501..535,601..631,701..800))
      Ordered, typed traversal with per-segment phase preserved. This is exactly
      what rebuilding a GenBank CDS join() requires. §7 NEVER TESTED THIS.

  (b) DISCONTINUOUS FEATURE VIA DUPLICATE ID — one logical feature, repeated ID.
      This is what OUR forward converter emits for origin-spanning features.
      gffutils cannot model it (scalar start/stop, no segment concept).
      Verified again in a MIXED file: oriC 980..1000 and oriC_1 1..20 stay split,
      with attributes['ID'] == 'oriC' on both.

REVISED VERDICT (reverse direction): USE gffutils.
  - Hierarchy traversal is essential once genomes are in scope, and it is the
    single largest piece of reverse-direction work. gffutils does it well.
  - Team already uses it in asat/gcev/reannot -> idiom consistency, maintainable.
  - The duplicate-ID coalescing pass is small, must be written under ANY approach,
    and has a clean grouping key (attributes['ID'], stable even when gffutils
    renames the feature id to oriC_1).
  - Cost that remains real: gffutils.Feature -> Biopython SeqFeature/
    CompoundLocation conversion layer, and a SQLite db build.

STILL TRUE FROM §7: no merge_strategy reconstructs an origin-spanning feature;
neither library collapses to a min/max span (the dangerous 1..60 failure mode
does not occur).

## 9. AGAT removal — measured footprint
Dry-run solves, conda-forge first:
  WITH agat    (python=3.11, biopython>=1.81, agat)      -> 229 packages, 305MB
  WITHOUT agat (python=3.11, biopython>=1.81, gffutils)  ->  45 packages,  64MB
=> 5x fewer packages, ~79% smaller download. AGAT drags Perl + BioPerl + R
   (r-base 4.4.3 alone is 27MB) to support a --validate flag the tool's own README
   tells users to leave OFF for plasmid maps (AGAT drops non-gene-model features).

Removing AGAT is a user-facing change, not just a Dockerfile edit:
  - the --validate CLI flag and run_agat_validate() (gb2gff_fna.py:226-264) go
  - README's "--validate caveat" section goes
  - run_gb2gff_fna.sh's VALIDATE variable goes
  - bp_genbank2gff3 (BioPerl) disappears as a side effect; README mentions it

## 10. Does GenBank encode hierarchy like GFF3? NO — structural difference
Relevant to whether the FORWARD direction should reconstruct gene->mRNA->CDS.
  GenBank: feature table is FLAT. No explicit parent-child link. Relationship is
    implied by shared /locus_tag convention. Splicing is expressed INSIDE one
    feature's location: CDS join(101..160,221..280,341..400).
  GFF3:    one row PER SEGMENT, relationship explicit via Parent.
=> "Reconstructing hierarchy" forward means INVENTING an mRNA level that is
   usually absent from the source (prokaryotic GenBank has gene + CDS only).
   That is exactly what the README criticises bp_genbank2gff3 for doing.
   Current forward behavior (flat + opportunistic Parent when CDS/gene share a
   locus_tag) is the honest mapping of what GenBank actually asserts.
   Note the forward writer already emits multi-segment CDS as multiple rows
   sharing one ID — the GFF3 discontinuous form, a subset of NCBI's convention.

## 11. Slim modern env VERIFIED functional — forward output byte-identical
Built: python 3.11.15 + biopython 1.87 + gffutils 0.14, NO agat, conda-forge first.
Ran the UNMODIFIED committed gb2gff_fna.py on example/plasmid_benchling.gb.

  old env (python 3.6.15 / biopython 1.70):
    78f7d3045e92e3070ee612f245d8810d  plasmid_benchling.fna
    96a05cf657ed5f588cca029b569a31cb  plasmid_benchling.gff3
  new env (python 3.11.15 / biopython 1.87):
    78f7d3045e92e3070ee612f245d8810d  plasmid_benchling.fna
    96a05cf657ed5f588cca029b569a31cb  plasmid_benchling.gff3

BYTE-IDENTICAL across a 17-release Biopython jump. The main risk of the image
modernization is retired for this fixture.

SCOPE LIMIT — do not overclaim: this is ONE fixture (60bp, 5 features, plus
strand, single-segment CDS + one origin-crossing rep_origin). It does NOT prove
invariance for genome-scale input or minus-strand split CDS. Those need their own
fixtures, and the minus-strand split CDS output WILL change anyway once the
cds_phases bug (RESULTS.md §4) is fixed — by design.

## 12. Origin-SPANNING CDS — F1 reaches it; plus a NEW row-order fragility
Probe: probe_origin_cds.py. 90bp circular, CDS wrapping the origin, both strands.
(The example fixture's only origin-crossing feature is a rep_origin, so
cds_phases() is never invoked on a wrapped location there.)

(a) PLUS strand, join(76..90,1..30):
    Biopython parts: [76..90 (15bp), 1..30 (30bp)] — given order.
    expected [0,0]; cds_phases() [0,0].  MATCH.

(b) MINUS strand, complement(join(70..89,1..25)):
    Biopython parts: [1..25 (25bp), 70..89 (20bp)] — REVERSED into biological
    order, consistent with RESULTS.md §4.
    expected [0,2]; cds_phases() [1,0].  DIVERGES.
=> The F1 double-reversal bug DOES reach origin-spanning minus-strand CDS. It is
   the same bug, not a new one, and the F1 fix (walk parts in given order)
   handles this case correctly. Good general confirmation of the fix rule.

(c) NEW FINDING — ROW ORDER IS SEMANTICALLY LOAD-BEARING, and not coord-sorted.
    Emitted rows for the plus-strand wrap:
        CDS  76..90  phase=0   ID=wrap_plus
        CDS   1..30  phase=0   ID=wrap_plus
    Row order (76.. before 1..) conveys segment order. It is NOT ascending by
    start coordinate — it cannot be, for an origin-spanning feature.

    Any downstream normalizer that sorts GFF3 rows by (seqid, start) — a very
    common operation, and one AGAT's standardizer would plausibly perform —
    reorders these, changing which segment is first and therefore which phase
    applies where. For segment lengths that are not multiples of 3 the phases
    differ and sorting silently corrupts the feature.

    This affects the stated downstream path: a GFF->Benchling uploader that sorts
    rows would mis-handle origin-spanning features.

    Note there may be a spec-sanctioned alternative: GFF3 arguably permits an end
    coordinate beyond the landmark length for a landmark marked Is_circular
    (i.e. one row, 76..120 on a 90bp circular molecule) which is sort-stable and
    unambiguous. NOT VERIFIED AGAINST THE SPEC TEXT — flagged as open question G5,
    not asserted.
