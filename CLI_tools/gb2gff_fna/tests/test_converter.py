import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gffutils
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import CompoundLocation, SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord

import gb2gff_fna


def record_with(features, length=100, record_id="record1", circular=False):
    record = SeqRecord(Seq("A" * length), id=record_id, name=record_id)
    record.features = features
    if circular:
        record.annotations["topology"] = "circular"
    return record


def feature_rows(record):
    return [
        line.split("\t")
        for line in gb2gff_fna.convert([record], "GenBank")
        if line and not line.startswith("#")
    ]


class ConverterTests(unittest.TestCase):
    def test_static_multirecord_fixture_end_to_end(self):
        fixture = Path(__file__).parent / "fixtures" / "genomic_edge_cases.gb"
        with fixture.open() as handle:
            records = list(SeqIO.parse(handle, "genbank"))
        gb2gff_fna.normalize_ids(records)
        self.assertEqual(
            [record.id for record in records],
            ["EDGE_LINEAR.1", "EDGE_CIRCULAR.1"],
        )

        rows = [
            line.split("\t")
            for line in gb2gff_fna.convert(records, "GenBank")
            if line and not line.startswith("#")
        ]
        phases = {}
        parents = {}
        for row in rows:
            attrs = gb2gff_fna._parse_gff_attributes(row[8])
            if row[2] == "CDS":
                phases.setdefault(attrs["ID"][0], []).append(row[7])
            if attrs.get("Parent"):
                parents.setdefault(attrs["ID"][0], attrs["Parent"][0])

        self.assertEqual(phases["ALT-P1"], ["1", "1"])
        self.assertEqual(phases["ALT-P2"], ["2", "0"])
        self.assertEqual(phases["NEG-P1"], ["0", "2"])
        self.assertEqual(phases["PROC-P1"], ["0"])
        self.assertEqual(phases["WRAP-P"], ["2", "2"])
        self.assertEqual(parents["ALT-P1"], "ALT-T1")
        self.assertEqual(parents["ALT-P2"], "ALT-T2")
        self.assertEqual(parents["NEG-P1"], "NEG-T1")
        self.assertEqual(parents["PROC-P1"], "PROC")
        mrna_ids = {
            gb2gff_fna._parse_gff_attributes(row[8])["ID"][0]
            for row in rows
            if row[2] == "mRNA"
        }
        self.assertEqual(mrna_ids, {"ALT-T1", "ALT-T2", "NEG-T1"})

    def test_cds_phase_follows_biological_part_order_on_both_strands(self):
        plus = [
            SimpleLocation(0, 10, strand=1),
            SimpleLocation(20, 31, strand=1),
        ]
        minus = [
            SimpleLocation(20, 31, strand=-1),
            SimpleLocation(0, 10, strand=-1),
        ]
        self.assertEqual(gb2gff_fna.cds_phases(plus, 1), [0, 2])
        self.assertEqual(gb2gff_fna.cds_phases(minus, 1), [0, 1])
        self.assertEqual(gb2gff_fna.cds_phases(minus, 2), [1, 2])

    def test_invalid_codon_start_warns_and_falls_back_to_one(self):
        cds = SeqFeature(
            SimpleLocation(0, 10, strand=1),
            type="CDS",
            qualifiers={"protein_id": ["bad-codon"], "codon_start": ["4"]},
        )
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            row = feature_rows(record_with([cds]))[-1]
        self.assertEqual(row[7], "0")
        self.assertIn("invalid /codon_start='4'", stderr.getvalue())

    def test_attributes_are_escaped_and_unknown_type_falls_back_to_so_term(self):
        feature = SeqFeature(
            SimpleLocation(0, 10, strand=1),
            type="made_up_key",
            qualifiers={"label": ["A;B=one,two% x"], "pseudo": [""]},
        )
        row = feature_rows(record_with([feature]))[-1]
        self.assertEqual(row[2], "sequence_feature")
        self.assertIn("Name=A%3BB%3Done%2Ctwo%25%20x", row[8])
        self.assertIn("pseudo=true", row[8])
        self.assertIn("gbkey=made_up_key", row[8])

    def test_insdc_keys_map_to_sequence_ontology_terms(self):
        self.assertEqual(
            gb2gff_fna._gff_type("assembly_gap", "record1"), "gap"
        )
        self.assertEqual(
            gb2gff_fna._gff_type("mobile_element", "record1"),
            "mobile_genetic_element",
        )
        self.assertEqual(
            gb2gff_fna._gff_type("regulatory", "record1"),
            "regulatory_region",
        )
        self.assertEqual(
            gb2gff_fna._gff_type("transit_peptide", "record1"),
            "transit_peptide",
        )

    def test_reserved_characters_round_trip_through_gffutils(self):
        gene_key = "gene; one, 100% & ready"
        transcript_key = "tx; one, 100% & ready"
        gene = SeqFeature(
            SimpleLocation(0, 90, strand=1),
            type="gene",
            qualifiers={"locus_tag": [gene_key], "note": ["note; x,y% & z"]},
        )
        mrna = SeqFeature(
            SimpleLocation(0, 90, strand=1),
            type="mRNA",
            qualifiers={
                "locus_tag": [gene_key],
                "transcript_id": [transcript_key],
            },
        )
        lines = list(gb2gff_fna.convert([record_with([gene, mrna])], "Gen Bank"))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "escaped.gff3"
            path.write_text("\n".join(lines) + "\n")
            db = gffutils.create_db(
                path,
                dbfn=":memory:",
                force=True,
                merge_strategy="create_unique",
                disable_infer_genes=True,
                disable_infer_transcripts=True,
            )
            gene_row = next(db.features_of_type("gene"))
            mrna_row = next(db.features_of_type("mRNA"))
        self.assertEqual(gene_row.attributes["ID"], [gene_key])
        self.assertEqual(gene_row.attributes["Name"], [gene_key])
        self.assertEqual(gene_row.attributes["Note"], ["note; x,y% & z"])
        self.assertEqual(mrna_row.attributes["ID"], [transcript_key])
        self.assertEqual(mrna_row.attributes["Parent"], [gene_key])

    def test_zero_length_site_and_unknown_strands_are_valid(self):
        relevant_unknown = SeqFeature(
            SimpleLocation(5, 5, strand=0),
            type="misc_feature",
            qualifiers={"label": ["relevant unknown"]},
        )
        not_relevant = SeqFeature(
            SimpleLocation(10, 15, strand=None),
            type="misc_feature",
            qualifiers={"label": ["not relevant"]},
        )
        rows = feature_rows(record_with([relevant_unknown, not_relevant]))
        self.assertEqual(rows[-2][3:5], ["5", "5"])
        self.assertEqual(rows[-2][6], "?")
        self.assertEqual(rows[-1][6], ".")

    def test_remote_feature_is_not_silently_relocated(self):
        remote = SeqFeature(
            SimpleLocation(0, 5, strand=1, ref="REMOTE.1"),
            type="CDS",
            qualifiers={"protein_id": ["remote-protein"]},
        )
        rows = feature_rows(record_with([remote]))
        self.assertEqual([row[2] for row in rows], ["region"])

    def test_duplicate_normalized_record_ids_are_rejected(self):
        records = [
            record_with([], record_id="duplicate"),
            record_with([], record_id="duplicate"),
        ]
        with self.assertRaisesRegex(ValueError, "duplicate record identifier"):
            gb2gff_fna.normalize_ids(records)

    def test_explicit_gene_mrna_cds_hierarchy_is_preserved(self):
        gene = SeqFeature(
            SimpleLocation(100, 900, strand=-1),
            type="gene",
            qualifiers={"gene": ["PON2"], "locus_tag": ["PON2"]},
        )
        mrna = SeqFeature(
            CompoundLocation(
                [
                    SimpleLocation(700, 800, strand=-1),
                    SimpleLocation(200, 300, strand=-1),
                ],
                operator="join",
            ),
            type="mRNA",
            qualifiers={
                "gene": ["PON2"],
                "locus_tag": ["PON2"],
                "transcript_id": ["PON2-RNA"],
            },
        )
        cds = SeqFeature(
            CompoundLocation(
                [
                    SimpleLocation(720, 800, strand=-1),
                    SimpleLocation(220, 300, strand=-1),
                ],
                operator="join",
            ),
            type="CDS",
            qualifiers={
                "gene": ["PON2"],
                "locus_tag": ["PON2"],
                "transcript_id": ["PON2-RNA"],
                "protein_id": ["PON2-P"],
            },
        )
        rows = feature_rows(record_with([gene, mrna, cds], length=1000))
        by_type = {}
        for row in rows:
            by_type.setdefault(row[2], []).append(row)
        gene_id = gb2gff_fna._parse_gff_attributes(by_type["gene"][0][8])["ID"][0]
        mrna_attrs = gb2gff_fna._parse_gff_attributes(by_type["mRNA"][0][8])
        cds_attrs = gb2gff_fna._parse_gff_attributes(by_type["CDS"][0][8])
        self.assertEqual(mrna_attrs["Parent"], [gene_id])
        self.assertEqual(cds_attrs["Parent"], [mrna_attrs["ID"][0]])
        self.assertEqual([row[7] for row in by_type["CDS"]], ["0", "1"])

    def test_real_ac005021_1_pon2_shape_keeps_hierarchy(self):
        # Coordinates and identifiers mirror the minus-strand PON2 model in
        # GenBank AC005021.1, reduced to the relationship-bearing features.
        gene = SeqFeature(
            SimpleLocation(6814, 44038, strand=-1),
            type="gene",
            qualifiers={"gene": ["PON2"]},
        )
        mrna = SeqFeature(
            SimpleLocation(6814, 44038, strand=-1),
            type="mRNA",
            qualifiers={"gene": ["PON2"], "transcript_id": ["PON2-RNA"]},
        )
        cds = SeqFeature(
            SimpleLocation(7571, 43401, strand=-1),
            type="CDS",
            qualifiers={
                "gene": ["PON2"],
                "transcript_id": ["PON2-RNA"],
                "protein_id": ["PON2-P"],
            },
        )
        rows = feature_rows(
            record_with([gene, mrna, cds], length=64607, record_id="AC005021.1")
        )
        attrs = {
            row[2]: gb2gff_fna._parse_gff_attributes(row[8]) for row in rows
        }
        self.assertEqual(attrs["mRNA"]["Parent"], attrs["gene"]["ID"])
        self.assertEqual(attrs["CDS"]["Parent"], attrs["mRNA"]["ID"])

    def test_exact_origin_wrap_uses_one_virtual_coordinate_row(self):
        wrap = SeqFeature(
            CompoundLocation(
                [
                    SimpleLocation(54, 60, strand=1),
                    SimpleLocation(0, 5, strand=1),
                ],
                operator="join",
            ),
            type="rep_origin",
            qualifiers={"label": ["ori"]},
        )
        rows = feature_rows(record_with([wrap], length=60, circular=True))
        regions = [row for row in rows if row[2] == "region"]
        origins = [row for row in rows if row[2] == "origin_of_replication"]
        self.assertEqual(len(regions), 1)
        self.assertIn("Is_circular=true", regions[0][8])
        self.assertEqual(len(origins), 1)
        self.assertEqual(origins[0][3:5], ["55", "65"])
        self.assertNotIn("part=", origins[0][8])

    def test_gapped_compound_feature_keeps_ordered_parts(self):
        feature = SeqFeature(
            CompoundLocation(
                [
                    SimpleLocation(49, 55, strand=1),
                    SimpleLocation(0, 5, strand=1),
                ],
                operator="join",
            ),
            type="misc_feature",
            qualifiers={"label": ["gapped"]},
        )
        rows = [
            row
            for row in feature_rows(record_with([feature], length=60, circular=True))
            if row[2] == "sequence_feature"
        ]
        self.assertEqual([row[3:5] for row in rows], [["50", "55"], ["1", "5"]])
        self.assertIn("part=1/2", rows[0][8])
        self.assertIn("part=2/2", rows[1][8])


if __name__ == "__main__":
    unittest.main()
