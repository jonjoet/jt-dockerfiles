"""Probe: does BCBio.GFF.parse merge repeated-ID rows into one CompoundLocation?

Input is REAL forward-converter output (verify_2026-07-24/fwd/), whose origin-
crossing rep_origin is two rows sharing ID=ori_wrap.
"""
import BCBio
from BCBio import GFF
from Bio import SeqIO
from Bio.SeqFeature import CompoundLocation

print("bcbio-gff version:", getattr(BCBio, "__version__", "unknown"))

FNA = "/data/v/fwd/plasmid_benchling.fna"
GFF3 = "/data/v/fwd/plasmid_benchling.gff3"

fasta_dict = SeqIO.to_dict(SeqIO.parse(FNA, "fasta"))
print("fasta records:", list(fasta_dict))

with open(GFF3) as fh:
    recs = list(GFF.parse(fh, base_dict=fasta_dict))

print("parsed records:", [r.id for r in recs])
rec = recs[0]

print()
print("=== top-level features as parsed ===")
for f in rec.features:
    fid = f.qualifiers.get("ID", ["<none>"])[0]
    kind = type(f.location).__name__
    nparts = len(f.location.parts)
    print(f"  type={f.type:24s} ID={fid:12s} loc={kind:17s} parts={nparts}  {f.location}")
    if f.sub_features:
        for sf in f.sub_features:
            print(f"      sub: type={sf.type} ID={sf.qualifiers.get('ID',['?'])[0]} {sf.location}")

print()
print("=== the ori_wrap question ===")
wraps = [f for f in rec.features
         if f.qualifiers.get("ID", [""])[0].startswith("ori_wrap")]
print(f"number of features whose ID starts with 'ori_wrap': {len(wraps)}")
for f in wraps:
    print(f"   ID={f.qualifiers.get('ID')} loc={f.location} "
          f"compound={isinstance(f.location, CompoundLocation)}")

merged = len(wraps) == 1 and isinstance(wraps[0].location, CompoundLocation)
print()
if merged:
    print("  RESULT: MERGED into one CompoundLocation -> spec assumption HOLDS")
else:
    print("  RESULT: NOT merged -> spec assumption FALSE, coalescing layer needed")
    print("          (codex's claim 1 confirmed)")

print()
print("=== attribute decoding: does BCBio already unquote values? ===")
for f in rec.features:
    if "Note" in f.qualifiers:
        print(f"  Note qualifier = {f.qualifiers['Note']!r}")
        print("   -> already unquoted" if "%20" not in f.qualifiers["Note"][0]
              else "   -> still percent-encoded")
        break

print()
print("=== create_missing behavior: unknown seqid ===")
import tempfile, os
bad = tempfile.NamedTemporaryFile("w", suffix=".gff3", delete=False)
bad.write("##gff-version 3\n")
bad.write("NOT_IN_FASTA\tGenBank\tgene\t1\t10\t.\t+\t.\tID=ghost\n")
bad.close()
with open(bad.name) as fh:
    bad_recs = list(GFF.parse(fh, base_dict=dict(fasta_dict)))
print("  record ids after parsing a GFF with an unmatched seqid:",
      [r.id for r in bad_recs])
ghost = [r for r in bad_recs if r.id == "NOT_IN_FASTA"]
if ghost:
    seq = ghost[0].seq
    print(f"  -> phantom record CREATED (seq type={type(seq).__name__}); "
          "default create_missing=True confirmed")
else:
    print("  -> no phantom record created")
os.unlink(bad.name)
