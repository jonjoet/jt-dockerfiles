from pathlib import Path

import pytest

from quickalign.annotation import normalize_annotation
from quickalign.errors import ValidationError


def test_annotation_is_sorted_and_embedded_fasta_removed(tmp_path):
    source = tmp_path / "in.gff3"
    source.write_text(
        "##gff-version 3\n"
        "chr2\ts\tgene\t4\t5\t.\t+\t.\tID=b\n"
        "# comment after features is omitted\n"
        "chr1\ts\tgene\t2\t3\t.\t+\t.\tID=a\n"
        "##FASTA\n>chr1\nAAAA\n"
    )
    output = tmp_path / "out.gff3"
    normalize_annotation(source, output, {"chr1": 10, "chr2": 10})
    assert output.read_text().splitlines() == [
        "##gff-version 3",
        "chr1\ts\tgene\t2\t3\t.\t+\t.\tID=a",
        "chr2\ts\tgene\t4\t5\t.\t+\t.\tID=b",
    ]


def test_annotation_rejects_bad_coordinates(tmp_path):
    source = tmp_path / "in.gff3"
    source.write_text("chr1\ts\tgene\t1\t11\t.\t+\t.\tID=a\n")
    with pytest.raises(ValidationError, match="outside"):
        normalize_annotation(source, tmp_path / "out.gff3", {"chr1": 10})


@pytest.mark.parametrize(
    ("score", "strand", "phase", "message"),
    [
        ("nan", "+", ".", "score"),
        ("inf", "+", ".", "score"),
        ("bad", "+", ".", "score"),
        ("1.0", "x", ".", "strand"),
        ("1.0", "+", "3", "phase"),
        ("1.0", "+", "", "phase"),
    ],
)
def test_annotation_rejects_invalid_score_strand_and_phase(tmp_path, score, strand, phase, message):
    source = tmp_path / "in.gff3"
    source.write_text(f"chr1\ts\tgene\t1\t2\t{score}\t{strand}\t{phase}\tID=a;Name=original\n")
    with pytest.raises(ValidationError, match=message):
        normalize_annotation(source, tmp_path / "out.gff3", {"chr1": 10})


def test_annotation_accepts_question_strand_and_preserves_attributes(tmp_path):
    source = tmp_path / "in.gff3"
    row = "chr1\ts\tgene\t1\t2\t1.25\t?\t2\tID=a;Note=x%20y"
    source.write_text(row + "\n")
    output = tmp_path / "out.gff3"
    normalize_annotation(source, output, {"chr1": 10})
    assert output.read_text() == row + "\n"
