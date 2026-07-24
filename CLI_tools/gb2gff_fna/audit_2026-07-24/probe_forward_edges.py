#!/usr/bin/env python3
"""Exercise forward-converter branches absent from the plasmid fixture."""

from io import StringIO
import sys

import gffutils
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import CompoundLocation, ExactPosition, SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord

sys.path.insert(0, "/work")
from gb2gff_fna import convert, make_unique, normalize_ids


def section(name):
    print(f"\n## {name}")


def feature_line(record, feature, source="source with space"):
    record.features = [feature]
    return [line for line in convert([record], source) if not line.startswith("#")][0]


section("versions")
import Bio

print("biopython", Bio.__version__)
print("gffutils", gffutils.__version__)


section("explicit ID/Name escaping and qualifier round-trip")
rec = SeqRecord(Seq("A" * 20), id="seq id/one")
feat = SeqFeature(
    SimpleLocation(0, 10, strand=1),
    type="misc_feature",
    qualifiers={
        "label": ["label;one, 100%"],
        "note": ["semi; equals= amp& comma, tab\t newline\n percent%"],
        "db_xref": ["DB:one", "DB:two"],
    },
)
rec.features = [feat]
lines = list(convert([rec], "source with space"))
print("\n".join(lines))
gff = "\n".join(lines) + "\n"
try:
    db = gffutils.create_db(
        gff,
        dbfn=":memory:",
        from_string=True,
        force=True,
        merge_strategy="create_unique",
        disable_infer_genes=True,
        disable_infer_transcripts=True,
    )
    parsed = next(db.all_features())
    print("gffutils attrs", dict(parsed.attributes))
except Exception as exc:
    print("gffutils parse error", type(exc).__name__, str(exc))


section("strand 0 versus None")
for strand in (0, None):
    rec = SeqRecord(Seq("A" * 20), id=f"strand_{strand}")
    feat = SeqFeature(
        SimpleLocation(1, 5, strand=strand),
        type="misc_feature",
        qualifiers={"label": [f"s{strand}"]},
    )
    cols = feature_line(rec, feat).split("\t")
    print(repr(strand), "->", cols[6])


section("codon_start values")
for codon_start in ("1", "2", "3", "0", "4", "bad"):
    rec = SeqRecord(Seq("A" * 80), id=f"codon_{codon_start}")
    parts = [
        SimpleLocation(0, 10, strand=1),
        SimpleLocation(20, 31, strand=1),
    ]
    feat = SeqFeature(
        CompoundLocation(parts, operator="join"),
        type="CDS",
        qualifiers={"label": ["cds"], "codon_start": [codon_start]},
    )
    rec.features = [feat]
    phases = [
        line.split("\t")[7]
        for line in convert([rec], "GenBank")
        if not line.startswith("#")
    ]
    print(codon_start, "->", phases)


section("zero-length and remote locations")
for name, location in (
    ("zero", SimpleLocation(5, 5, strand=1)),
    ("remote", SimpleLocation(2, 8, strand=1, ref="REMOTE.1")),
):
    rec = SeqRecord(Seq("A" * 20), id=name)
    feat = SeqFeature(location, type="misc_feature", qualifiers={"label": [name]})
    print(name, "->", feature_line(rec, feat))


section("make_unique collisions")
used = set()
for base in ("x", "x", "x_2", "x", "x_3", "x"):
    print(base, "->", make_unique(base, used), sorted(used))


section("normalize_ids real accession and duplicate placeholders")
gb = """LOCUS       LOCUS_ONE                 12 bp    DNA     linear   SYN 24-JUL-2026
DEFINITION  accession record.
ACCESSION   AB123456
VERSION     AB123456.2
FEATURES             Location/Qualifiers
ORIGIN
        1 aaaaaaaaaaaa
//
LOCUS       SAME_LOCUS                12 bp    DNA     linear   SYN 24-JUL-2026
DEFINITION  placeholder one.
ACCESSION   .
FEATURES             Location/Qualifiers
ORIGIN
        1 aaaaaaaaaaaa
//
LOCUS       SAME_LOCUS                12 bp    DNA     linear   SYN 24-JUL-2026
DEFINITION  placeholder two.
ACCESSION   .
FEATURES             Location/Qualifiers
ORIGIN
        1 aaaaaaaaaaaa
//
"""
records = list(SeqIO.parse(StringIO(gb), "genbank"))
print("before", [(r.id, r.name) for r in records])
normalize_ids(records)
print("after", [(r.id, r.name) for r in records])
print(
    "sequence-region",
    [line for line in convert(records, "GenBank") if line.startswith("##sequence-region")],
)


section("gene/mRNA/CDS and repeated locus_tag")
rec = SeqRecord(Seq("A" * 500), id="genome")
rec.features = [
    SeqFeature(
        SimpleLocation(0, 400, strand=1),
        type="gene",
        qualifiers={"locus_tag": ["LOC1"], "gene": ["g"]},
    ),
    SeqFeature(
        CompoundLocation(
            [SimpleLocation(0, 100, strand=1), SimpleLocation(200, 400, strand=1)],
            operator="join",
        ),
        type="mRNA",
        qualifiers={
            "locus_tag": ["LOC1"],
            "gene": ["g"],
            "transcript_id": ["TX1"],
        },
    ),
    SeqFeature(
        CompoundLocation(
            [SimpleLocation(20, 100, strand=1), SimpleLocation(200, 350, strand=1)],
            operator="join",
        ),
        type="CDS",
        qualifiers={
            "locus_tag": ["LOC1"],
            "gene": ["g"],
            "transcript_id": ["TX1"],
            "protein_id": ["P1"],
            "codon_start": ["1"],
        },
    ),
    SeqFeature(
        CompoundLocation(
            [SimpleLocation(0, 80, strand=1), SimpleLocation(250, 400, strand=1)],
            operator="join",
        ),
        type="mRNA",
        qualifiers={
            "locus_tag": ["LOC1"],
            "gene": ["g"],
            "transcript_id": ["TX2"],
        },
    ),
    SeqFeature(
        CompoundLocation(
            [SimpleLocation(10, 80, strand=1), SimpleLocation(250, 390, strand=1)],
            operator="join",
        ),
        type="CDS",
        qualifiers={
            "locus_tag": ["LOC1"],
            "gene": ["g"],
            "transcript_id": ["TX2"],
            "protein_id": ["P2"],
            "codon_start": ["1"],
        },
    ),
]
for line in convert([rec], "GenBank"):
    if not line.startswith("#"):
        cols = line.split("\t")
        print(cols[2], cols[3], cols[4], cols[8])


section("valueless qualifier")
rec = SeqRecord(Seq("A" * 20), id="bool")
feat = SeqFeature(
    SimpleLocation(0, 10, strand=1),
    type="gene",
    qualifiers={"locus_tag": ["BOOL1"], "pseudo": [""]},
)
print(feature_line(rec, feat))


section("gffutils virtual circular coordinates and part order")
virtual_gff = """##gff-version 3
##sequence-region circ 1 90
circ\tGenBank\tregion\t1\t90\t.\t+\t.\tID=circ;Is_circular=true
circ\tGenBank\tCDS\t76\t120\t.\t+\t1\tID=wrap_contiguous
circ\tGenBank\tCDS\t70\t89\t.\t-\t2\tID=wrap_split;part=2/2
circ\tGenBank\tCDS\t91\t115\t.\t-\t0\tID=wrap_split;part=1/2
"""
db = gffutils.create_db(
    virtual_gff,
    dbfn=":memory:",
    from_string=True,
    force=True,
    merge_strategy="create_unique",
    disable_infer_genes=True,
    disable_infer_transcripts=True,
)
for parsed in db.all_features(order_by=("seqid", "start")):
    print(
        parsed.featuretype,
        parsed.start,
        parsed.end,
        parsed.strand,
        parsed.frame,
        dict(parsed.attributes),
    )
