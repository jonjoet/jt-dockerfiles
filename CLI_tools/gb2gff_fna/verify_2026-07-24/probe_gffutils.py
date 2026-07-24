"""Probe: can gffutils coalesce duplicate-ID rows into a real discontinuous feature?

The decisive question is NOT "does it merge" but "does it merge WITHOUT losing the
segment boundaries". Our origin-crossing rep_origin is join(55..60,1..5); a merge
that collapses to a min/max span yields 1..60 — the exact complement of the truth.
"""
import gffutils
import gffutils.version

print("gffutils version:", gffutils.version.version)

GFF3 = "/data/v/fwd/plasmid_benchling.gff3"
print("input rows for ori_wrap:")
for ln in open(GFF3):
    if "ori_wrap" in ln:
        f = ln.split("\t")
        print(f"   {f[2]}  {f[3]}..{f[4]}  strand={f[6]}")

print()
print("=" * 70)
print("A) default merge_strategy")
print("=" * 70)
for strategy in ("error", "merge", "create_unique"):
    print(f"\n--- merge_strategy={strategy!r} ---")
    try:
        db = gffutils.create_db(
            GFF3, ":memory:", merge_strategy=strategy,
            keep_order=True, force=True,
        )
    except Exception as exc:
        print(f"   raised {type(exc).__name__}: {str(exc)[:120]}")
        continue

    feats = [f for f in db.all_features() if "ori_wrap" in f.id]
    print(f"   features whose id contains 'ori_wrap': {len(feats)}")
    for f in feats:
        print(f"     id={f.id!r}  {f.start}..{f.end}  strand={f.strand}")
        span = f.end - f.start + 1
        if len(feats) == 1 and span > 11:
            print(f"     *** COLLAPSED to a {span}bp span — segment boundaries LOST ***")
            print("     *** join(55..60,1..5) became a contiguous run: WRONG ***")

print()
print("=" * 70)
print("B) does gffutils expose discontinuous segments natively?")
print("=" * 70)
db = gffutils.create_db(GFF3, ":memory:", merge_strategy="create_unique",
                        keep_order=True, force=True)
f = list(db.all_features())[0]
print("Feature attrs available:", [a for a in dir(f) if not a.startswith("_")][:25])
print()
print("Is there a 'parts'/'segments' concept? ->",
      any(hasattr(f, n) for n in ("parts", "segments", "pieces")))

print()
print("=" * 70)
print("C) attribute unescaping behavior (double-decode hazard)")
print("=" * 70)
for feat in db.all_features():
    if "Note" in feat.attributes:
        print(f"   Note = {feat.attributes['Note']!r}")
        raw = open(GFF3).read()
        print("   source contained '%20':", "%20" in raw)
        val = feat.attributes["Note"][0]
        print("   -> gffutils DID unescape" if "%" not in val
              else "   -> gffutils left it encoded")
        break

print()
print("=" * 70)
print("D) what a 'merge' actually did to attributes/coords")
print("=" * 70)
dbm = gffutils.create_db(GFF3, ":memory:", merge_strategy="merge",
                         keep_order=True, force=True)
for feat in dbm.all_features():
    if "ori_wrap" in feat.id:
        print(f"   id={feat.id} coords={feat.start}..{feat.end}")
        print(f"   attributes={dict(feat.attributes)}")
