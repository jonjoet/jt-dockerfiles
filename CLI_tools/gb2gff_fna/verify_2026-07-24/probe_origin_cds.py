"""Probe: origin-SPANNING CDS. The example fixture never exercises this.

Its only origin-crossing feature is a rep_origin, so cds_phases() is never
invoked on a wrapped location. Questions:
  1. What part order does Biopython give for join(...) that wraps the origin?
  2. Ditto complement(join(...)) — does the minus-strand reversal interact with
     the F1 double-reversal bug?
  3. What ROW ORDER does the forward converter emit, and is that order
     semantically load-bearing?
"""
import sys
from Bio import SeqIO

sys.path.insert(0, "/opt")
from gb2gff_fna import cds_phases, convert

# 90bp circular. CDS wraps the origin: 76..90 (15bp) then 1..30 (30bp) = 45bp.
GB = """LOCUS       wrap                      90 bp ds-DNA     circular SYN 24-JUL-2026
DEFINITION  origin-spanning CDS probe.
ACCESSION   .
FEATURES             Location/Qualifiers
     source          1..90
                     /organism="synthetic DNA construct"
                     /mol_type="other DNA"
     CDS             join(76..90,1..30)
                     /label="wrap_plus"
                     /codon_start=1
     CDS             complement(join(70..89,1..25))
                     /label="wrap_minus"
                     /codon_start=1
ORIGIN
        1 atgcatgcat gcatgcatgc atgcatgcat gcatgcatgc atgcatgcat gcatgcatgc
       61 atgcatgcat gcatgcatgc atgcatgcat
//
"""
open("/tmp/wrap.gb", "w").write(GB)
rec = next(SeqIO.parse("/tmp/wrap.gb", "genbank"))


def correct_phases(parts, codon_start):
    """Ground truth: walk parts in the order given, propagating phase."""
    ph = [0] * len(parts)
    ph[0] = (codon_start - 1) % 3
    for i in range(1, len(parts)):
        ph[i] = (3 - ((len(parts[i - 1]) - ph[i - 1]) % 3)) % 3
    return ph


for feat in [f for f in rec.features if f.type == "CDS"]:
    label = feat.qualifiers["label"][0]
    parts = list(feat.location.parts)
    print("=" * 68)
    print(f"{label}   location = {feat.location}")
    print("=" * 68)
    for i, p in enumerate(parts):
        print(f"  parts[{i}]: {int(p.start)+1}..{int(p.end)}  len={len(p)}  strand={p.strand}")

    total = sum(len(p) for p in parts)
    print(f"  total length = {total} bp ({'multiple of 3' if total % 3 == 0 else 'NOT mult of 3'})")

    expected = correct_phases(parts, 1)
    actual = cds_phases(parts, 1)
    print(f"  expected phases (walk parts in given order): {expected}")
    print(f"  cds_phases() committed code:                 {actual}")
    print("  -> MATCH" if expected == actual else "  -> *** DIVERGES (F1 bug reaches this case) ***")
    print()

print("=" * 68)
print("ROW ORDER actually emitted by the forward converter")
print("=" * 68)
for line in convert([rec], "GenBank"):
    if line.startswith("#"):
        continue
    f = line.split("\t")
    # Width 78: 38 truncated immediately before part=, hiding the very
    # mechanism the note below discusses.
    print(f"  {f[2]:6s} {f[3]:>3s}..{f[4]:<3s} strand={f[6]} phase={f[7]}  {f[8][:78]}")

print()
print("NOTE (corrected 2026-07-24, after the hardening fix landed):")
print()
print("  The original trailing note here claimed that sorting rows by start")
print("  coordinate would reorder this feature's 76..90 / 1..30 rows 'and thus")
print("  change which phase applies where'. BOTH HALVES WERE WRONG, in ways")
print("  worth keeping on record:")
print()
print("  1. The phase claim was wrong even pre-fix. Phase is column 8 of its")
print("     OWN row and travels with that row through a sort, so phase stays")
print("     correctly bound to its coordinates. What a sort actually destroys")
print("     is the SEGMENT ORDER needed to reconstruct the join.")
print()
print("  2. The coordinates are wrong post-fix. An exactly contiguous two-part")
print("     wrap is now emitted as ONE virtual-coordinate row (76..120 on a")
print("     90bp landmark, licensed by Is_circular=true on the full-length")
print("     region), so there are no rows left to reorder. A gapped wrap is")
print("     still multi-row, but now carries explicit part=X/Y in biological")
print("     order, which makes segment order recoverable regardless of sorting.")
print()
print("  Pre-fix behavior is recorded in RESULTS.md §12; this probe was written")
print("  against f4b251a and now runs against the hardened converter.")
