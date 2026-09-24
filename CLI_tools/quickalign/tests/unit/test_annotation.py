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

