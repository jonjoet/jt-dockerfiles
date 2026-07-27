import gzip
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SERVICE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_DIR))

import migrate_legacy_zips as migrate  # noqa: E402
import plasmidsaurus_autofetch as autofetch  # noqa: E402


class ArchiveLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_tmp_root = Path(__file__).parent / ".tmp"
        cls.test_tmp_root.mkdir(exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_tmp_root, ignore_errors=True)

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=self.test_tmp_root)
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_extract_preserves_inner_gzip_bytes(self):
        fastq_gz = gzip.compress(b"@read1\nACGT\n+\n!!!!\n")
        archive = self.root / "reads.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("sample.fastq.gz", fastq_gz, compress_type=zipfile.ZIP_STORED)

        staging = self.root / "share" / ".reads.partial"
        staging.parent.mkdir()
        stats = autofetch.extract_zip(archive, staging)

        extracted = (staging / "sample.fastq.gz").read_bytes()
        self.assertEqual(extracted, fastq_gz)
        self.assertEqual(gzip.decompress(extracted), b"@read1\nACGT\n+\n!!!!\n")
        self.assertEqual(stats, {"files": 1, "bytes": len(fastq_gz)})

    def test_extract_rejects_traversal_and_removes_staging(self):
        archive = self.root / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../outside.txt", b"no")

        staging = self.root / "share" / ".results.partial"
        staging.parent.mkdir()
        with self.assertRaises(autofetch.RetryableError):
            autofetch.extract_zip(archive, staging)

        self.assertFalse(staging.exists())
        self.assertFalse((self.root / "outside.txt").exists())

    def test_free_space_failure_is_retryable(self):
        with mock.patch.object(
            autofetch.shutil,
            "disk_usage",
            return_value=SimpleNamespace(free=99),
        ):
            with self.assertRaisesRegex(
                autofetch.RetryableError, "not enough free space"
            ):
                autofetch.ensure_free_space(self.root, 100, margin=1.0)

    def test_manifest_write_is_atomic(self):
        marker = self.root / ".complete"
        autofetch.write_manifest_atomic(marker, {"layout_version": 2})

        self.assertEqual(json.loads(marker.read_text()), {"layout_version": 2})
        self.assertFalse((self.root / ".complete.part").exists())

    def test_process_item_extracts_and_only_then_marks_complete(self):
        data_dir = self.root / "share"
        scratch_dir = self.root / "scratch"
        data_dir.mkdir()
        scratch_dir.mkdir()
        fastq_gz = gzip.compress(b"@read1\nACGT\n+\n!!!!\n")

        def fake_download(url, scratch_path, min_free_bytes):
            with zipfile.ZipFile(scratch_path, "w") as zf:
                if "results" in scratch_path.name:
                    zf.writestr("report.txt", b"complete\n")
                else:
                    zf.writestr(
                        "sample.fastq.gz",
                        fastq_gz,
                        compress_type=zipfile.ZIP_STORED,
                    )
            return scratch_path.stat().st_size

        fetch_patch = mock.patch.object(
            autofetch,
            "fetch_link",
            side_effect=lambda token, code, kind: f"https://example.test/{kind}",
        )
        download_patch = mock.patch.object(
            autofetch,
            "download_to_scratch",
            side_effect=fake_download,
        )
        with fetch_patch, download_patch:
            status = autofetch.process_item(
                {"code": "ORDER-NEW", "status": "complete"},
                "token",
                data_dir,
                scratch_dir,
                0,
                False,
            )

        item_dir = data_dir / "ORDER-NEW"
        self.assertEqual(status, "done")
        self.assertEqual(
            (item_dir / "results" / "report.txt").read_bytes(), b"complete\n"
        )
        self.assertEqual(
            (item_dir / "reads" / "sample.fastq.gz").read_bytes(), fastq_gz
        )
        self.assertEqual(
            json.loads((item_dir / ".complete").read_text())["layout_version"],
            2,
        )
        self.assertEqual(list(scratch_dir.iterdir()), [])

    def test_process_item_does_not_mark_corrupt_archive_complete(self):
        data_dir = self.root / "share"
        scratch_dir = self.root / "scratch"
        data_dir.mkdir()
        scratch_dir.mkdir()

        def fake_download(url, scratch_path, min_free_bytes):
            scratch_path.write_bytes(b"not a zip")
            return scratch_path.stat().st_size

        fetch_patch = mock.patch.object(
            autofetch,
            "fetch_link",
            side_effect=lambda token, code, kind: f"https://example.test/{kind}",
        )
        download_patch = mock.patch.object(
            autofetch,
            "download_to_scratch",
            side_effect=fake_download,
        )
        with fetch_patch, download_patch:
            status = autofetch.process_item(
                {"code": "ORDER-BAD", "status": "complete"},
                "token",
                data_dir,
                scratch_dir,
                0,
                False,
            )

        self.assertEqual(status, "partial-error")
        self.assertFalse((data_dir / "ORDER-BAD" / ".complete").exists())
        self.assertEqual(list(scratch_dir.iterdir()), [])

    def test_legacy_migration_preserves_then_explicitly_deletes_zips(self):
        code = "ORDER-123"
        item_dir = self.root / code
        item_dir.mkdir()
        fastq_gz = gzip.compress(b"@read1\nACGT\n+\n!!!!\n")
        results_zip = item_dir / f"{code}_results.zip"
        reads_zip = item_dir / f"{code}_reads.zip"
        with zipfile.ZipFile(results_zip, "w") as zf:
            zf.writestr("report.txt", b"complete\n")
        with zipfile.ZipFile(reads_zip, "w") as zf:
            zf.writestr("sample.fastq.gz", fastq_gz, compress_type=zipfile.ZIP_STORED)
        (item_dir / ".complete").write_text(
            json.dumps(
                {
                    "item_code": code,
                    "fetched_at": "2026-01-01T00:00:00+00:00",
                    "files": {
                        "results": {"file": results_zip.name},
                        "reads": {"file": reads_zip.name},
                    },
                }
            )
        )

        self.assertEqual(migrate.migrate_order(item_dir), "migrated")
        self.assertEqual(
            (item_dir / "results" / "report.txt").read_bytes(), b"complete\n"
        )
        self.assertEqual(
            (item_dir / "reads" / "sample.fastq.gz").read_bytes(), fastq_gz
        )
        self.assertTrue(results_zip.exists())
        self.assertTrue(reads_zip.exists())
        manifest = json.loads((item_dir / ".complete").read_text())
        self.assertEqual(manifest["layout_version"], 2)
        self.assertEqual(manifest["files"]["results"]["files"], 1)
        self.assertEqual(manifest["files"]["reads"]["bytes"], len(fastq_gz))

        self.assertEqual(
            migrate.migrate_order(item_dir, delete_zips=True),
            "archives-deleted",
        )
        self.assertFalse(results_zip.exists())
        self.assertFalse(reads_zip.exists())


if __name__ == "__main__":
    unittest.main()
