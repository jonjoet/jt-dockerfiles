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
    print(f"  {f[2]:6s} {f[3]:>3s}..{f[4]:<3s} strand={f[6]} phase={f[7]}  {f[8][:38]}")

print()
print("NOTE: for a discontinuous feature the ROW ORDER carries the segment order.")
print("Any downstream tool that sorts rows by start coordinate would reorder")
print("76..90 / 1..30 into 1..30 / 76..90 — changing which segment is first,")
print("and thus which phase applies where.")
