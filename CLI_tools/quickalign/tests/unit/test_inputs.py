import gzip
from pathlib import Path

import pytest

from quickalign.errors import ValidationError
from quickalign.inputs import (
    GZIP_TRUNCATION_TEXT, normalize_mate_name, parse_manifest, safe_name,
    track_ids, validate_pair, validating_unpaired_records,
)
from quickalign.models import ReadGroup


RECORD1 = b"@read/1\nACGT\n+\nIIII\n"
RECORD2 = b"@read/2\nTGCA\n+\nIIII\n"


def test_safe_names_and_collisions():
    groups = tuple(ReadGroup(label, "nanopore", "single", Path("x.fastq")) for label in ("A B", "a-b", "a-b"))
    assert safe_name(" !! ") == "sample"
    assert track_ids(groups) == ["a-b", "a-b-2", "a-b-3"]


def test_pair_name_normalization_and_strict_validation(tmp_path):
    assert normalize_mate_name(b"@name/1 comment") == (b"name", 1)
    assert normalize_mate_name(b"@name 2:N:0:1") == (b"name", 2)
    with pytest.raises(ValidationError, match="empty"):
        normalize_mate_name(b"@")
    interleaved = tmp_path / "reads.fastq"
    interleaved.write_bytes(RECORD1 + RECORD2)
    validate_pair(ReadGroup("pairs", "illumina", "interleaved", interleaved))
    interleaved.write_bytes(RECORD1 + RECORD1)
    with pytest.raises(ValidationError, match="incompatible"):
        validate_pair(ReadGroup("pairs", "illumina", "interleaved", interleaved))


def test_gzip_missing_trailer_preserves_complete_records_and_warns(tmp_path):
    path = tmp_path / "reads.fastq.gz"
    path.write_bytes(gzip.compress(RECORD1 + RECORD2)[:-8])
    records, warnings = validating_unpaired_records(path)
    assert list(records) == [RECORD1, RECORD2]
    assert warnings[0].code == "truncated_gzip"
    assert GZIP_TRUNCATION_TEXT.strip() in warnings[0].message


def test_gzip_crc_mismatch_is_fatal_after_decoded_records(tmp_path):
    path = tmp_path / "reads.fastq.gz"
    payload = bytearray(gzip.compress(RECORD1))
    payload[-8] ^= 1
    path.write_bytes(payload)
    records, warnings = validating_unpaired_records(path)
    iterator = iter(records)
    assert next(iterator) == RECORD1
    with pytest.raises(ValidationError, match="CRC"):
        next(iterator)
    assert warnings == []


def test_plain_partial_quality_is_recoverable(tmp_path):
    path = tmp_path / "reads.fastq"
    path.write_bytes(RECORD1 + b"@next\nACGT\n+\nII")
    records, warnings = validating_unpaired_records(path)
    assert list(records) == [RECORD1]
    assert warnings[0].code == "truncated_fastq"


def test_manifest_paths_are_relative_to_manifest(tmp_path):
    reads = tmp_path / "reads.fastq"
    reads.write_bytes(RECORD1)
    manifest = tmp_path / "groups.tsv"
    manifest.write_text("label\ttechnology\tlayout\tread1\tread2\nreads\tnanopore\tsingle\treads.fastq\t\n")
    groups = parse_manifest(manifest)
    assert groups[0].read1 == tmp_path / "reads.fastq"

