"""Probe: the case the first gffutils probe skipped — genome-style hierarchy.

Spliced CDS in real genome GFF3 is NOT duplicate-ID rows. It is multiple CDS rows
with distinct/absent IDs sharing Parent=<mRNA>. That is the mechanism gffutils is
built for, and it is what NCBI/Ensembl/prokka/bakta emit.

Tests:
  1. plus-strand spliced CDS  -> can we recover join(...) segments in order?
  2. minus-strand spliced CDS -> is ordering usable for /codon_start + phase?
  3. a file mixing BOTH mechanisms (hierarchy + duplicate-ID origin wrap)
  4. phase values preserved per segment?
"""
import gffutils

GENOME_GFF = """##gff-version 3
##sequence-region chr1 1 1000
chr1\tprokka\tgene\t101\t400\t.\t+\t.\tID=gene1;Name=abcA
chr1\tprokka\tmRNA\t101\t400\t.\t+\t.\tID=mrna1;Parent=gene1
chr1\tprokka\tCDS\t101\t160\t.\t+\t0\tID=cds1;Parent=mrna1
chr1\tprokka\tCDS\t221\t280\t.\t+\t0\tID=cds2;Parent=mrna1
chr1\tprokka\tCDS\t341\t400\t.\t+\t0\tID=cds3;Parent=mrna1
chr1\tprokka\tgene\t501\t800\t.\t-\t.\tID=gene2;Name=xyzB
chr1\tprokka\tmRNA\t501\t800\t.\t-\t.\tID=mrna2;Parent=gene2
chr1\tprokka\tCDS\t501\t535\t.\t-\t1\tID=cds4;Parent=mrna2
chr1\tprokka\tCDS\t601\t631\t.\t-\t0\tID=cds5;Parent=mrna2
chr1\tprokka\tCDS\t701\t800\t.\t-\t0\tID=cds6;Parent=mrna2
chr1\tGenBank\torigin_of_replication\t980\t1000\t.\t+\t.\tID=oriC;Name=oriC
chr1\tGenBank\torigin_of_replication\t1\t20\t.\t+\t.\tID=oriC;Name=oriC
"""
path = "/tmp/genome.gff3"
open(path, "w").write(GENOME_GFF)

db = gffutils.create_db(path, ":memory:", merge_strategy="create_unique",
                        keep_order=True, force=True)

print("gffutils", gffutils.version.version)
print()
print("=" * 70)
print("1+2) HIERARCHY: recover spliced CDS segments via Parent")
print("=" * 70)
for mrna_id in ("mrna1", "mrna2"):
    mrna = db[mrna_id]
    kids = list(db.children(mrna, featuretype="CDS", order_by="start"))
    strand = mrna.strand
    print(f"\n{mrna_id}  strand={strand}  CDS children: {len(kids)}")
    for k in kids:
        print(f"   {k.id}  {k.start}..{k.end}  phase={k.frame}")
    segs = [(k.start, k.end) for k in kids]
    if strand == "-":
        bio = segs[::-1]
        print(f"   genomic order    : {segs}")
        print(f"   biological order : {bio}  <- reverse for minus strand")
        print(f"   GenBank would be : complement(join("
              f"{','.join(f'{s}..{e}' for s, e in segs)}))")
    else:
        print(f"   GenBank would be : join("
              f"{','.join(f'{s}..{e}' for s, e in segs)})")
    print(f"   phases in genomic order: {[k.frame for k in kids]}")

print()
print("=" * 70)
print("3) MIXED FILE: does the duplicate-ID origin wrap still split?")
print("=" * 70)
oris = [f for f in db.all_features() if "oriC" in f.id]
print(f"   features matching oriC: {len(oris)}")
for f in oris:
    print(f"     id={f.id!r}  attributes['ID']={f.attributes['ID']}  "
          f"{f.start}..{f.end}")
print("   -> hierarchy handled natively; duplicate-ID still needs our coalescing")

print()
print("=" * 70)
print("4) relationship traversal sanity (the thing gffutils is FOR)")
print("=" * 70)
for gene in db.features_of_type("gene"):
    mrnas = list(db.children(gene, featuretype="mRNA"))
    cdss = list(db.children(gene, featuretype="CDS"))
    print(f"   {gene.id} ({gene.attributes.get('Name',['?'])[0]}): "
          f"{len(mrnas)} mRNA, {len(cdss)} CDS   strand={gene.strand}")
print()
print("   db.children() gives ordered, typed traversal for free —")
print("   this is exactly what reconstructing a GenBank CDS join() needs.")
