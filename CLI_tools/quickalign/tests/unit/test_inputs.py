import gzip
import zlib
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


def test_overlong_final_quality_without_newline_is_fatal(tmp_path):
    path = tmp_path / "reads.fastq"
    path.write_bytes(b"@read\nAC\n+\nIII")
    records, _ = validating_unpaired_records(path)
    with pytest.raises(ValidationError, match="unequal"):
        list(records)


def test_gzip_header_crc_mismatch_is_fatal(tmp_path):
    original = bytearray(gzip.compress(RECORD1))
    original[3] |= 2
    valid_crc = (zlib.crc32(original[:10]) & 0xFFFF).to_bytes(2, "little")
    payload = original[:10] + valid_crc + original[10:]
    payload[10] ^= 1
    path = tmp_path / "reads.fastq.gz"
    path.write_bytes(payload)
    records, _ = validating_unpaired_records(path)
    with pytest.raises(ValidationError, match="header CRC"):
        list(records)


def test_manifest_paths_are_relative_to_manifest(tmp_path):
    reads = tmp_path / "reads.fastq"
    reads.write_bytes(RECORD1)
    manifest = tmp_path / "groups.tsv"
    manifest.write_text("label\ttechnology\tlayout\tread1\tread2\nreads\tnanopore\tsingle\treads.fastq\t\n")
    groups = parse_manifest(manifest)
    assert groups[0].read1 == tmp_path / "reads.fastq"
    assert groups[0].read1_display == "reads.fastq"


@pytest.mark.parametrize("absolute", [False, True])
def test_manifest_display_names_preserve_labels_and_source_paths(tmp_path, absolute):
    source = tmp_path / "private source directory"
    source.mkdir()
    first, second = source / "first.fastq", source / "second.fastq"
    first.write_bytes(RECORD1)
    second.write_bytes(RECORD2)
    manifest = tmp_path / "groups.tsv"
    paths = [str(path if absolute else path.relative_to(tmp_path)) for path in (first, second)]
    manifest.write_text(
        "label\ttechnology\tlayout\tread1\tread2\n"
        f"My Paired Label\tillumina\tpaired\t{paths[0]}\t{paths[1]}\n"
    )
    group, = parse_manifest(manifest)
    assert group.label == "My Paired Label"
    assert group.read1 == first and group.read2 == second
    assert group.read1_display == "first.fastq" and group.read2_display == "second.fastq"
    assert track_ids((group,)) == ["my-paired-label"]
    validate_pair(group)


def write_fastq(root, name, content, compressed):
    path = root / (name + (".fastq.gz" if compressed else ".fastq"))
    path.write_bytes(gzip.compress(content, mtime=0) if compressed else content)
    return path


@pytest.mark.parametrize("compressed", [False, True])
def test_bare_at_eof_recovers_preceding_single_reads(tmp_path, compressed):
    path = write_fastq(tmp_path, "reads", RECORD1 + RECORD2 + b"@", compressed)
    records, warnings = validating_unpaired_records(path)
    assert list(records) == [RECORD1, RECORD2]
    assert len(warnings) == 1 and warnings[0].code == "truncated_fastq"


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("suffix", [b"\n", b"\r\n\n \t\n \t", b"\n" * 65537])
def test_single_trailing_blank_suffix_is_accepted(tmp_path, compressed, suffix):
    path = write_fastq(tmp_path, "reads", RECORD1 + RECORD2 + suffix, compressed)
    records, warnings = validating_unpaired_records(path)
    assert list(records) == [RECORD1, RECORD2]
    assert warnings == []


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("layout", ["paired", "interleaved"])
def test_paired_trailing_blank_suffix_is_accepted(tmp_path, compressed, layout):
    first = write_fastq(tmp_path, "first", RECORD1 + (RECORD2 if layout == "interleaved" else b"") + b"\n \t\r\n", compressed)
    second = write_fastq(tmp_path, "second", RECORD2 + b"\n\n", compressed) if layout == "paired" else None
    validate_pair(ReadGroup("pairs", "illumina", layout, first, second))
    for path, expected in [(first, [RECORD1, RECORD2] if second is None else [RECORD1]), *([(second, [RECORD2])] if second else [])]:
        records, warnings = validating_unpaired_records(path)
        assert list(records) == expected and warnings == []


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("layout", ["paired", "interleaved"])
@pytest.mark.parametrize("suffix, message", [
    (b"@", "truncated FASTQ"),
    (b"@\nACGT\n+\nIIII\n", "empty read identifier"),
    (b"\n" + RECORD2, "blank lines"),
])
def test_paired_invalid_suffix_is_fatal(tmp_path, compressed, layout, suffix, message):
    first = write_fastq(tmp_path, "first", RECORD1 + (RECORD2 + suffix if layout == "interleaved" else b""), compressed)
    second = write_fastq(tmp_path, "second", RECORD2 + suffix, compressed) if layout == "paired" else None
    with pytest.raises(ValidationError, match=message):
        validate_pair(ReadGroup("pairs", "illumina", layout, first, second))


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("suffix, message", [
    (b"@\n", "empty read identifier"),
    (b"@\nACGT\n+\nIIII\n", "empty read identifier"),
    (b"\n" + RECORD2, "blank lines"),
    (b"\n@", "blank lines"),
])
def test_single_invalid_suffix_is_fatal(tmp_path, compressed, suffix, message):
    path = write_fastq(tmp_path, "reads", RECORD1 + suffix, compressed)
    records, warnings = validating_unpaired_records(path)
    assert next(records) == RECORD1
    with pytest.raises(ValidationError, match=message):
        list(records)
    assert warnings == []


@pytest.mark.parametrize("compressed", [False, True])
def test_trailing_blanks_do_not_hide_unequal_mates(tmp_path, compressed):
    first = write_fastq(tmp_path, "first", RECORD1 + RECORD1 + b"\n", compressed)
    second = write_fastq(tmp_path, "second", RECORD2 + b"\n", compressed)
    with pytest.raises(ValidationError, match="unequal record counts"):
        validate_pair(ReadGroup("pairs", "illumina", "paired", first, second))


def test_gzip_trailing_blanks_do_not_hide_crc_failure(tmp_path):
    payload = bytearray(gzip.compress(RECORD1 + b"\n\n", mtime=0))
    payload[-8] ^= 1
    path = tmp_path / "reads.fastq.gz"
    path.write_bytes(payload)
    records, warnings = validating_unpaired_records(path)
    assert next(records) == RECORD1
    with pytest.raises(ValidationError, match="CRC"):
        list(records)
    assert warnings == []


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("content", [b"", b"@", b"\n\r\n", b"@incomplete\n"])
def test_single_without_complete_reads_is_fatal(tmp_path, compressed, content):
    path = write_fastq(tmp_path, "reads", content, compressed)
    records, warnings = validating_unpaired_records(path)
    with pytest.raises(ValidationError, match="no complete reads"):
        list(records)
    assert warnings == []


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("layout", ["paired", "interleaved"])
@pytest.mark.parametrize("content", [b"", b"\n\r\n"])
def test_paired_without_complete_reads_is_fatal(tmp_path, compressed, layout, content):
    first = write_fastq(tmp_path, "first", content, compressed)
    second = write_fastq(tmp_path, "second", content, compressed) if layout == "paired" else None
    with pytest.raises(ValidationError, match="no complete reads"):
        validate_pair(ReadGroup("pairs", "illumina", layout, first, second))


@pytest.mark.parametrize("corruption", ["crc", "deflate"])
def test_empty_gzip_corruption_keeps_integrity_diagnostic(tmp_path, corruption):
    payload = bytearray(gzip.compress(b"\n", mtime=0))
    if corruption == "crc":
        payload[-8] ^= 1
    else:
        payload[10] = (payload[10] & ~6) | 6
    path = tmp_path / "reads.fastq.gz"
    path.write_bytes(payload)
    records, warnings = validating_unpaired_records(path)
    with pytest.raises(ValidationError, match="CRC" if corruption == "crc" else "DEFLATE"):
        list(records)
    assert warnings == []
