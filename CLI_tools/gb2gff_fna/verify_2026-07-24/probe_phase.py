"""Probe: does Biopython store complement(join(...)) parts in biological order?

If yes, cds_phases() in gb2gff_fna.py (which reverses again when strand == -1)
double-reverses and computes wrong phases for minus-strand multi-segment CDS.
"""
import sys
from Bio import SeqIO

sys.path.insert(0, "/opt")
from gb2gff_fna import cds_phases  # the real, committed function

GB = """LOCUS       probe                     90 bp ds-DNA     linear   SYN 24-JUL-2026
DEFINITION  minus-strand split CDS probe.
ACCESSION   .
FEATURES             Location/Qualifiers
     CDS             complement(join(11..40,55..90))
                     /label="minus_split"
                     /codon_start=1
ORIGIN
        1 atgcatgcat gcatgcatgc atgcatgcat gcatgcatgc atgcatgcat gcatgcatgc
       61 atgcatgcat gcatgcatgc atgcatgcat
//
"""
with open("/tmp/probe.gb", "w") as fh:
    fh.write(GB)

rec = next(SeqIO.parse("/tmp/probe.gb", "genbank"))
feat = [f for f in rec.features if f.type == "CDS"][0]
parts = list(feat.location.parts)

print("=== Biopython part order for complement(join(11..40,55..90)) ===")
for i, p in enumerate(parts):
    # +1 to show 1-based inclusive start like GFF3/GenBank
    print(f"  parts[{i}]: {int(p.start)+1}..{int(p.end)}  strand={p.strand}  len={len(p)}")

first = parts[0]
bio_first_is_high = int(first.start) + 1 == 55
print()
print(f"parts[0] is the HIGH-coordinate (biologically first on minus strand) segment: {bio_first_is_high}")
print("  -> Biopython order is BIOLOGICAL" if bio_first_is_high else "  -> Biopython order is GENOMIC left-to-right")

print()
print("=== what cds_phases() computes (committed code) ===")
phases = cds_phases(parts, 1)
for i, (p, ph) in enumerate(zip(parts, phases)):
    print(f"  parts[{i}] {int(p.start)+1}..{int(p.end)} len={len(p)} -> phase {ph}")

print()
print("=== correctness check ===")
# Biologically-first segment MUST get phase (codon_start-1)%3 == 0 here.
bio_first_idx = 0 if bio_first_is_high else len(parts) - 1
print(f"biologically-first segment is parts[{bio_first_idx}]")
print(f"its phase from cds_phases() = {phases[bio_first_idx]}  (expected 0 for codon_start=1)")
if phases[bio_first_idx] != 0:
    print("  *** BUG CONFIRMED: biologically-first segment did not get phase 0 ***")
else:
    print("  OK: biologically-first segment got phase 0")

# Second segment expectation: 36 bp first exon (55..90) -> (3 - (36-0)%3)%3 = 0
print()
print("expected phase of biologically-SECOND segment given a 36bp first segment: "
      f"{(3 - ((len(parts[bio_first_idx]) - 0) % 3)) % 3}")
other_idx = 1 - bio_first_idx if len(parts) == 2 else None
print(f"actual phase assigned to parts[{other_idx}] = {phases[other_idx]}")
