import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gb2gff_fna


VALID_GFF = """##gff-version 3
##sequence-region chr1 1 20
chr1\tGenBank\tregion\t1\t20\t.\t+\t.\tID=chr1_region;Is_circular=true;gbkey=Src
chr1\tGenBank\tgene\t2\t18\t.\t+\t.\tID=g1;gbkey=gene
chr1\tGenBank\tmRNA\t2\t18\t.\t+\t.\tID=t1;Parent=g1;gbkey=mRNA
chr1\tGenBank\tCDS\t2\t5\t.\t+\t0\tID=c1;Parent=t1;gbkey=CDS;part=1/2
chr1\tGenBank\tCDS\t10\t18\t.\t+\t2\tID=c1;Parent=t1;gbkey=CDS;part=2/2
chr1\tGenBank\torigin_of_replication\t18\t23\t.\t+\t.\tID=o1;gbkey=rep_origin
"""


class ValidatorTests(unittest.TestCase):
    def validate_text(self, text):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "input.gff3"
            path.write_text(text)
            before = hashlib.sha256(path.read_bytes()).digest()
            result = gb2gff_fna.validate_gff(path)
            after = hashlib.sha256(path.read_bytes()).digest()
            self.assertEqual(before, after, "validation must never rewrite its input")
            return result

    def test_valid_hierarchical_and_circular_gff(self):
        self.assertTrue(self.validate_text(VALID_GFF))

    def test_dangling_parent_fails(self):
        self.assertFalse(self.validate_text(VALID_GFF.replace("Parent=g1", "Parent=nope")))

    def test_bad_cds_phase_fails(self):
        self.assertFalse(
            self.validate_text(
                VALID_GFF.replace("CDS\t2\t5\t.\t+\t0", "CDS\t2\t5\t.\t+\t.")
            )
        )

    def test_non_circular_out_of_bounds_fails(self):
        self.assertFalse(
            self.validate_text(
                VALID_GFF.replace(";Is_circular=true", "").replace(
                    "origin_of_replication\t18\t23",
                    "origin_of_replication\t18\t23",
                )
            )
        )

    def test_repeated_id_requires_complete_part_numbers(self):
        self.assertFalse(self.validate_text(VALID_GFF.replace("part=2/2", "part=1/2")))

    def test_parent_cycle_fails(self):
        self.assertFalse(
            self.validate_text(
                VALID_GFF.replace("ID=g1;gbkey=gene", "ID=g1;Parent=t1;gbkey=gene")
            )
        )

    def test_duplicate_sequence_region_fails(self):
        self.assertFalse(
            self.validate_text(
                VALID_GFF.replace(
                    "##sequence-region chr1 1 20",
                    "##sequence-region chr1 1 20\n##sequence-region chr1 1 20",
                )
            )
        )

    def test_duplicate_version_header_fails(self):
        self.assertFalse(
            self.validate_text(
                VALID_GFF.replace(
                    "##sequence-region chr1 1 20",
                    "##gff-version 3\n##sequence-region chr1 1 20",
                )
            )
        )

    def test_circular_virtual_coordinate_cannot_exceed_one_turn(self):
        self.assertFalse(
            self.validate_text(
                VALID_GFF.replace(
                    "origin_of_replication\t18\t23",
                    "origin_of_replication\t18\t41",
                )
            )
        )

    def test_non_cds_phase_fails(self):
        self.assertFalse(
            self.validate_text(
                VALID_GFF.replace("gene\t2\t18\t.\t+\t.", "gene\t2\t18\t.\t+\t0")
            )
        )

    def test_repeated_id_invariant_type_fails(self):
        self.assertFalse(
            self.validate_text(
                VALID_GFF.replace(
                    "CDS\t10\t18\t.\t+\t2",
                    "exon\t10\t18\t.\t+\t.",
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
