from pathlib import Path

import pytest

from quickalign.commands import (
    align_argv, allocate_threads, bgzip_argv, bwa_index_argv, faidx_argv,
    index_argv, sort_argv, tabix_argv,
)
from quickalign.models import ReadGroup


def test_thread_budget_includes_sort_main_thread():
    assert allocate_threads(2) == (1, 0)
    assert allocate_threads(4) == (2, 1)
    with pytest.raises(ValueError):
        allocate_threads(1)


def test_exact_illumina_and_nanopore_argv():
    illumina = ReadGroup("Sample A", "illumina", "interleaved", Path("reads.fq.gz"))
    assert align_argv(illumina, "sample-a", Path("ref.fa"), Path("idx/ref"), 3) == [
        "bwa-mem2", "mem", "-t", "3", "-R", "@RG\\tID:sample-a\\tSM:Sample A\\tPL:ILLUMINA",
        "-p", "idx/ref", "reads.fq.gz",
    ]
    nanopore = ReadGroup("ONT", "nanopore", "single", Path("ont.fq"))
    assert align_argv(nanopore, "ont", Path("ref.fa"), Path("unused"), 2) == [
        "minimap2", "-ax", "map-ont", "-t", "2", "-R", "@RG\\tID:ont\\tSM:ONT\\tPL:ONT",
        "ref.fa", "ont.fq",
    ]


def test_exact_index_sort_and_annotation_argv():
    assert faidx_argv(Path("ref.fa")) == ["samtools", "faidx", "ref.fa"]
    assert bwa_index_argv(Path("ref.fa"), Path("bwa/ref")) == ["bwa-mem2", "index", "-p", "bwa/ref", "ref.fa"]
    assert sort_argv(Path("x.bam"), Path("work/x"), 1, "128M") == [
        "samtools", "sort", "-@", "1", "-m", "128M", "-T", "work/x", "-o", "x.bam", "-",
    ]
    assert index_argv(Path("x.bam")) == ["samtools", "index", "-b", "x.bam", "x.bam.bai"]
    assert bgzip_argv(Path("x.gff3")) == ["bgzip", "-c", "x.gff3"]
    assert tabix_argv(Path("x.gff3.gz")) == ["tabix", "-f", "-p", "gff", "x.gff3.gz"]

