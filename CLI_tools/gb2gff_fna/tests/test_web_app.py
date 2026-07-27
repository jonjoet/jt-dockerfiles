import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from streamlit.testing.v1 import AppTest

import gb2gff_fna_web


class WebAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example_path = (
            Path(__file__).resolve().parents[1]
            / "example"
            / "plasmid_benchling.gb"
        )
        cls.example_bytes = cls.example_path.read_bytes()

    def test_upload_conversion_returns_valid_individual_and_zip_outputs(self):
        result = gb2gff_fna_web.convert_upload(
            self.example_bytes,
            self.example_path.name,
            source="Web upload",
            validate=True,
        )

        self.assertEqual(result.prefix, "plasmid_benchling")
        self.assertEqual(result.record_count, 1)
        self.assertEqual(result.total_bases, 60)
        self.assertGreater(result.feature_rows, 0)
        self.assertTrue(result.validated)
        self.assertTrue(result.gff3.startswith(b"##gff-version 3\n"))
        self.assertTrue(result.fna.startswith(b">"))
        self.assertIn(b"\tWeb%20upload\t", result.gff3)

        with zipfile.ZipFile(io.BytesIO(result.archive)) as archive:
            self.assertEqual(
                archive.namelist(),
                ["plasmid_benchling.gff3", "plasmid_benchling.fna"],
            )
            self.assertEqual(
                archive.read("plasmid_benchling.gff3"), result.gff3
            )
            self.assertEqual(
                archive.read("plasmid_benchling.fna"), result.fna
            )

    def test_custom_prefix_is_used_for_all_download_names(self):
        result = gb2gff_fna_web.convert_upload(
            self.example_bytes,
            self.example_path.name,
            requested_prefix="my plasmid",
            validate=False,
        )
        self.assertEqual(result.prefix, "my plasmid")
        self.assertIsNone(result.validated)
        with zipfile.ZipFile(io.BytesIO(result.archive)) as archive:
            self.assertEqual(
                archive.namelist(),
                ["my plasmid.gff3", "my plasmid.fna"],
            )

    def test_path_like_output_prefix_is_rejected(self):
        for prefix in ("../escape", "nested/name", r"nested\name"):
            with self.subTest(prefix=prefix):
                with self.assertRaisesRegex(
                    gb2gff_fna_web.ConversionError,
                    "filename, not a path",
                ):
                    gb2gff_fna_web.convert_upload(
                        self.example_bytes,
                        self.example_path.name,
                        requested_prefix=prefix,
                    )

    def test_header_unsafe_output_prefix_is_rejected(self):
        for prefix in ('bad"name', "bad\nname", "bad\rname", "bad\x7fname"):
            with self.subTest(prefix=prefix):
                with self.assertRaisesRegex(
                    gb2gff_fna_web.ConversionError,
                    "quotes or control characters",
                ):
                    gb2gff_fna_web.convert_upload(
                        self.example_bytes,
                        self.example_path.name,
                        requested_prefix=prefix,
                    )

    def test_empty_and_non_genbank_uploads_are_rejected(self):
        with self.assertRaisesRegex(
            gb2gff_fna_web.ConversionError, "uploaded file is empty"
        ):
            gb2gff_fna_web.convert_upload(b"", "empty.gb")
        with self.assertRaisesRegex(
            gb2gff_fna_web.ConversionError, "No GenBank records"
        ):
            gb2gff_fna_web.convert_upload(b"not a GenBank record\n", "bad.gb")

    def test_validation_failure_retains_outputs_and_diagnostics(self):
        invalid = self.example_bytes.replace(
            b"circular", b"linear  ", 1
        ).replace(b"join(55..60,1..5)", b"55..80", 1)
        validated = gb2gff_fna_web.convert_upload(
            invalid,
            "linear.gb",
            validate=True,
        )
        unvalidated = gb2gff_fna_web.convert_upload(
            invalid,
            "linear.gb",
            validate=False,
        )

        self.assertFalse(validated.validated)
        self.assertIn("out-of-bounds feature on non-circular", validated.diagnostics)
        self.assertEqual(validated.gff3, unvalidated.gff3)
        self.assertEqual(validated.fna, unvalidated.fna)
        self.assertGreater(len(validated.archive), 0)

    def test_streamlit_page_renders_without_exceptions(self):
        app_path = Path(__file__).resolve().parents[1] / "gb2gff_fna_web.py"
        app = AppTest.from_file(str(app_path)).run(timeout=10)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.title[0].value, "GenBank → GFF3 + FASTA")


if __name__ == "__main__":
    unittest.main()
