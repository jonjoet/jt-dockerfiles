"""Real pinned-tool negatives: valid BAM output cannot hide corrupt inputs."""
import gzip
import json
from pathlib import Path
import random
import subprocess
import zlib

import pytest
from quickalign import jobs
from quickalign.errors import ValidationError
from quickalign.inputs import GZIP_TRUNCATION_TEXT, TRUNCATION_TEXT
from quickalign.models import ReadGroup, RunSpec


def make_inputs(root):
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(957)
    sequence = ''.join(rng.choice('ACGT') for _ in range(3000))
    reference = root / 'reference.fa'
    annotation = root / 'features.gff3'
    reference.write_text('>chr1\n' + sequence + '\n')
    annotation.write_text('##gff-version 3\nchr1\tsynthetic\tgene\t1\t1000\t.\t+\t.\tID=gene1;Name=Fixture\n')
    record = ('@complete\n' + sequence[500:800] + '\n+\n' + 'I' * 300 + '\n').encode()
    return reference, annotation, record


def reserve(root, technology, content, suffix='.fastq', *, layout='single', read2=None):
    reference, annotation, record = make_inputs(root / 'inputs')
    read = root / 'inputs' / ('reads' + suffix)
    read.write_bytes(content(record) if callable(content) else content)
    group = ReadGroup('test reads', technology, layout, read, read2)
    spec = RunSpec(reference, annotation, (group,), 'fixture', threads=2)
    job = jobs.reserve_job('test-job', root / 'outputs' / 'test-job', root / 'work', spec)
    return job, record


@pytest.mark.parametrize('technology', ['illumina', 'nanopore'])
@pytest.mark.parametrize('mode', ['plain-partial', 'gzip-missing-trailer', 'gzip-short-quality'])
def test_unpaired_truncation_is_portable_warning(tmp_path, technology, mode):
    def content(record):
        if mode == 'plain-partial':
            return record + b'@incomplete\nACGT\n+\nII'
        if mode == 'gzip-missing-trailer':
            return gzip.compress(record, mtime=0)[:-4]
        return gzip.compress(record + b'@incomplete\nACGT\n+\nII', mtime=0)
    job, _ = reserve(tmp_path, technology, content, '.fastq' if mode == 'plain-partial' else '.fastq.gz')
    result = jobs.run_job(job)
    metadata = jobs.read_metadata(job.output_dir)
    assert metadata['status'] == 'completed'
    assert result.warnings and TRUNCATION_TEXT in result.warnings[0].message
    has_gzip_warning = GZIP_TRUNCATION_TEXT.strip() in result.warnings[0].message
    assert has_gzip_warning == (mode == 'gzip-missing-trailer')
    assert result.tracks[0].total >= 1
    bam = result.tracks[0].bam
    subprocess.run(['samtools', 'quickcheck', str(bam)], check=True)
    alignments = subprocess.check_output(['samtools', 'view', str(bam)]).decode()
    assert 'complete\t' in alignments and 'incomplete\t' not in alignments
    assert not job.work.exists()
    # Warnings survive relocation and remain in both portable human and machine records.
    relocated = tmp_path / 'relocated bundle ü & spaces'
    job.bundle.rename(relocated)
    manifest = json.loads((relocated / 'manifest.json').read_text())
    assert manifest['warnings'][0]['input_name'] == ('reads.fastq' if mode == 'plain-partial' else 'reads.fastq.gz')
    for filename in ('README.txt', 'README.html'):
        assert TRUNCATION_TEXT in (relocated / filename).read_text()
        assert (GZIP_TRUNCATION_TEXT.strip() in (relocated / filename).read_text()) == has_gzip_warning


def corrupt(record, mode):
    encoded = bytearray(gzip.compress(record, mtime=0))
    if mode == 'crc':
        encoded[-8] ^= 0x01
        return bytes(encoded)
    if mode == 'size':
        encoded[-4] ^= 0x01
        return bytes(encoded)
    if mode == 'deflate':
        # Reserved BTYPE=3 is an unambiguous DEFLATE error, independent of parser syntax.
        encoded[10] = (encoded[10] & ~6) | 6
        return bytes(encoded)
    if mode == 'midfile-bitflip':
        # A stored DEFLATE block permits a stable internal bit flip that leaves FASTQ valid,
        # proving the checksum rather than syntax detects the corrupt sequence base.
        encoded = bytearray(gzip.compress(record * 8, compresslevel=0, mtime=0))
        offset = encoded.index(b'\n') + 30
        encoded[offset] ^= 1
        return bytes(encoded)
    raise AssertionError(mode)


@pytest.mark.parametrize('technology', ['illumina', 'nanopore'])
@pytest.mark.parametrize('mode', ['crc', 'size', 'deflate', 'midfile-bitflip'])
def test_gzip_integrity_failure_prevents_publication(tmp_path, technology, mode):
    job, _ = reserve(tmp_path, technology, lambda record: corrupt(record, mode), '.fastq.gz')
    with pytest.raises(ValidationError):
        jobs.run_job(job)
    data = jobs.read_metadata(job.output_dir)
    assert data['status'] == 'failed'
    assert not job.bundle.exists()
    assert (job.output_dir / 'logs').is_dir()
    assert not job.work.exists()
    with pytest.raises(ValidationError):
        jobs.completed_bundle(job.output_dir)


@pytest.mark.parametrize('mode', ['bad-header', 'bad-separator', 'short-quality-line', 'overlong-final-quality'])
def test_malformed_complete_fastq_is_fatal(tmp_path, mode):
    malformed = {'bad-header': b'not-a-header\nACGT\n+\nIIII\n',
                 'bad-separator': b'@bad\nACGT\nno-plus\nIIII\n',
                 'short-quality-line': b'@bad\nACGT\n+\nII\n',
                 'overlong-final-quality': b'@bad\nACGT\n+\nIIIIII'}[mode]
    job, _ = reserve(tmp_path, 'nanopore', lambda record: record + malformed)
    with pytest.raises(ValidationError):
        jobs.run_job(job)
    assert jobs.read_metadata(job.output_dir)['status'] == 'failed'
    assert not job.bundle.exists()


@pytest.mark.parametrize('layout', ['paired', 'interleaved'])
def test_paired_truncation_remains_strict(tmp_path, layout):
    reference, annotation, record = make_inputs(tmp_path / 'inputs')
    read1 = tmp_path / 'inputs' / 'r1.fastq'
    read2 = tmp_path / 'inputs' / 'r2.fastq'
    read1.write_bytes(record.replace(b'@complete', b'@complete/1'))
    read2.write_bytes(record.replace(b'@complete', b'@complete/2')[:-15])
    if layout == 'interleaved':
        read1.write_bytes(read1.read_bytes() + read2.read_bytes())
    group = ReadGroup('pairs', 'illumina', layout, read1, read2 if layout == 'paired' else None)
    job = jobs.reserve_job('strict', tmp_path / 'outputs' / 'strict', tmp_path / 'work',
                           RunSpec(reference, annotation, (group,), 'fixture', threads=2))
    with pytest.raises(ValidationError):
        jobs.run_job(job)
    metadata = jobs.read_metadata(job.output_dir)
    assert metadata['status'] == 'failed' and not job.partial.exists()
    assert not metadata['commands']


@pytest.mark.parametrize('truncated', [False, True])
def test_cli_zip_failure_is_nonzero_but_bundle_accessible(tmp_path, monkeypatch, capsys, truncated):
    from quickalign.cli import main
    reference, annotation, record = make_inputs(tmp_path / 'inputs')
    reads = tmp_path / 'inputs' / 'reads.fastq'
    reads.write_bytes(record + (b'@unfinished\nACGT\n+\nII' if truncated else b''))
    def fail_zip(*args, **kwargs):
        raise OSError('injected ZIP disk failure')
    monkeypatch.setattr(jobs.zipfile, 'ZipFile', fail_zip)
    out = tmp_path / 'output'
    code = main(['build', str(reference), str(annotation), '--outdir', str(out),
                 '--nanopore', str(reads), '--threads', '2', '--zip'])
    assert code != 0
    data = jobs.read_metadata(out)
    assert data['status'] == 'completed' and data['export_status'] == 'failed'
    assert jobs.completed_bundle(out).is_dir()
    assert jobs.downloadable_archive(out, 10**9) is None
    diagnostic = capsys.readouterr().err
    assert 'Completed bundle remains available' in diagnostic
    if truncated:
        assert TRUNCATION_TEXT in diagnostic
