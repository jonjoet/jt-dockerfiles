"""Probe 2: expose the minus-strand double-reversal with non-multiple-of-3 segments.

complement(join(11..41,55..89)):  11..41 = 31bp, 55..89 = 35bp
Biopython yields parts in BIOLOGICAL order (verified in probe_phase.py):
    parts[0] = 55..89 (35bp)   <- biologically first
    parts[1] = 11..41 (31bp)

Correct GFF3 phases for codon_start=1:
    biologically-first  -> 0
    biologically-second -> (3 - ((35 - 0) % 3)) % 3 = 1
"""
import sys
from Bio import SeqIO

sys.path.insert(0, "/opt")
from gb2gff_fna import cds_phases

GB = """LOCUS       probe2                    90 bp ds-DNA     linear   SYN 24-JUL-2026
DEFINITION  minus-strand split CDS, segments not divisible by 3.
ACCESSION   .
FEATURES             Location/Qualifiers
     CDS             complement(join(11..41,55..89))
                     /label="minus_split"
                     /codon_start=1
ORIGIN
        1 atgcatgcat gcatgcatgc atgcatgcat gcatgcatgc atgcatgcat gcatgcatgc
       61 atgcatgcat gcatgcatgc atgcatgcat
//
"""
with open("/tmp/probe2.gb", "w") as fh:
    fh.write(GB)

rec = next(SeqIO.parse("/tmp/probe2.gb", "genbank"))
feat = [f for f in rec.features if f.type == "CDS"][0]
parts = list(feat.location.parts)

print("=== Biopython part order ===")
for i, p in enumerate(parts):
    print(f"  parts[{i}]: {int(p.start)+1}..{int(p.end)}  len={len(p)}  strand={p.strand}")

# Independent ground truth: walk parts in the order Biopython gave (already
# biological), propagating phase the standard way.
def correct_phases(parts, codon_start):
    ph = [0] * len(parts)
    ph[0] = (codon_start - 1) % 3
    for i in range(1, len(parts)):
        ph[i] = (3 - ((len(parts[i - 1]) - ph[i - 1]) % 3)) % 3
    return ph

expected = correct_phases(parts, 1)
actual = cds_phases(parts, 1)

print()
print("=== phases ===")
print(f"  expected (biological order, no re-reversal): {expected}")
print(f"  cds_phases() committed code:                 {actual}")
print()
if expected != actual:
    print("  *** BUG CONFIRMED: cds_phases() double-reverses on minus strand ***")
    for i, p in enumerate(parts):
        flag = "  <-- WRONG" if expected[i] != actual[i] else ""
        print(f"    parts[{i}] {int(p.start)+1}..{int(p.end)}: "
              f"expected {expected[i]}, got {actual[i]}{flag}")
else:
    print("  no divergence for this case")

# Sanity: the plus-strand split case must be unaffected.
print()
print("=== plus-strand control: join(11..41,55..89) ===")
GB_PLUS = GB.replace("complement(join(11..41,55..89))", "join(11..41,55..89)")
with open("/tmp/probe2p.gb", "w") as fh:
    fh.write(GB_PLUS)
recp = next(SeqIO.parse("/tmp/probe2p.gb", "genbank"))
fp = [f for f in recp.features if f.type == "CDS"][0]
pp = list(fp.location.parts)
for i, p in enumerate(pp):
    print(f"  parts[{i}]: {int(p.start)+1}..{int(p.end)}  len={len(p)}  strand={p.strand}")
ep, ap = correct_phases(pp, 1), cds_phases(pp, 1)
print(f"  expected: {ep}   cds_phases(): {ap}   -> {'OK' if ep == ap else 'DIVERGES'}")
