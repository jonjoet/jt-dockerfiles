"""Metadata-only discovery and explicitly clicked, bounded ZIP downloads."""
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from quickalign import bundle, jobs
from quickalign.errors import ValidationError
from quickalign.ui.config import UiConfig
from test_bundle import _build


def completed_fixture(root, job_id='job-001', archive=True):
    output = root / job_id
    job, _ = _build(output)
    job.partial.rename(job.bundle)
    jobs.atomic_json(output / 'job.json', {
        'schema_version': 1, 'job_id': job_id, 'name': 'sample', 'status': 'completed',
        'bundle': job.bundle.name, 'tracks': [], 'warnings': [],
        'export_status': 'completed' if archive else 'not_requested',
        'archive': job.bundle.name + '.zip',
    })
    if archive:
        # A small payload fixture, not represented as an export-valid ZIP.
        (output / (job.bundle.name + '.zip')).write_bytes(b'fixture archive')
    return job


def forbid_payloads(monkeypatch):
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        assert path.suffix not in {'.bam', '.bai', '.zip', '.fasta', '.gz'}, path
        return original_open(path, *args, **kwargs)
    def forbidden(*args, **kwargs):
        raise AssertionError('discovery must not hash or recursively walk')
    monkeypatch.setattr(Path, 'open', guarded_open)
    monkeypatch.setattr(Path, 'rglob', forbidden)
    monkeypatch.setattr(bundle, '_sha256', forbidden)


def test_creation_hashes_each_asset_once_and_never_again(tmp_path, monkeypatch):
    counts = Counter()
    original = bundle._sha256
    def counted(path):
        root = next(parent for parent in path.parents if parent.name.endswith('.jbrowse.partial'))
        counts[path.relative_to(root).as_posix()] += 1
        return original(path)
    monkeypatch.setattr(bundle, '_sha256', counted)
    job = completed_fixture(tmp_path, archive=False)
    manifest = jobs.completed_bundle_info(job.output_dir)[1]
    assert counts == Counter({record['path']: 1 for record in manifest['files']})
    forbid_payloads(monkeypatch)
    assert jobs.completed_bundle(job.output_dir) == job.bundle


def test_more_than_cache_capacity_twice_and_after_restart(tmp_path, monkeypatch):
    seed = completed_fixture(tmp_path)
    for i in range(2, 71):
        output = tmp_path / f'job-{i:03}'
        shutil.copytree(seed.output_dir, output)
        jobs.update_metadata(output, job_id=output.name)
    forbid_payloads(monkeypatch)
    from quickalign.ui import app
    deferred = []
    for name in ('write', 'caption', 'success', 'info', 'warning', 'error'):
        monkeypatch.setattr(app.st, name, lambda *a, **kw: None)
    monkeypatch.setattr(app.st, 'download_button', lambda label, data, **kw: deferred.append(data))
    calls = []
    original_validate = bundle.validate_bundle
    def counted(path):
        calls.append(path)
        return original_validate(path)
    monkeypatch.setattr(bundle, 'validate_bundle', counted)
    for _ in range(2):
        items = jobs.discover_jobs(tmp_path)
        assert len(items) == 70 and all(item['bundle_available'] for item in items)
        assert all(item['bundle_size_bytes'] > 0 for item in items)
        assert all(item['archive_size_bytes'] == len(b'fixture archive') for item in items)
        for item in items:
            app.render_result(UiConfig((tmp_path,), tmp_path, tmp_path / 'work'), item, item['job_id'])
    assert len(calls) == 140 and len(deferred) == 140
    assert all(callable(callback) for callback in deferred)
    # A new interpreter models restart; guards are installed before first discovery.
    code = '''
from pathlib import Path
import sys
from quickalign import bundle, jobs
original = Path.open
def guard(path, *a, **kw):
    assert path.suffix not in {'.bam', '.bai', '.zip', '.fasta', '.gz'}, path
    return original(path, *a, **kw)
def forbidden(*a, **kw):
    raise AssertionError('payload hash or recursive discovery')
Path.open = guard
Path.rglob = forbidden
bundle._sha256 = forbidden
from quickalign.ui import app
from quickalign.ui.config import UiConfig
for name in ('write', 'caption', 'success', 'info', 'warning', 'error'):
    setattr(app.st, name, lambda *a, **kw: None)
def download(label, data, **kw):
    assert callable(data)
app.st.download_button = download
config = UiConfig((Path(sys.argv[1]),), Path(sys.argv[1]), Path(sys.argv[1]) / 'work')
for _ in range(2):
    items = jobs.discover_jobs(sys.argv[1])
    assert len(items) == 70 and all(i['bundle_available'] for i in items)
    for item in items:
        app.render_result(config, item, item['job_id'])
print('70 completed jobs discovered and rendered twice after fresh interpreter restart; no payload reads, hashes, or recursive walks')
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)], check=True, text=True, capture_output=True)
    (tmp_path / 'restart-check.txt').write_text(result.stdout)


def test_benign_extras_and_same_size_payload_change_remain_available(tmp_path, monkeypatch):
    job = completed_fixture(tmp_path)
    (job.bundle / '.DS_Store').write_bytes(b'finder')
    (job.bundle / 'sample.local.jbrowse').write_text('{"local": "generated"}')
    (job.bundle / 'notes').mkdir()
    (job.bundle / 'notes' / 'extra.txt').write_text('user note')
    (job.bundle / 'alignments' / 'reads-one.bam').write_bytes(b'XYZ')
    forbid_payloads(monkeypatch)
    assert jobs.discover_jobs(tmp_path)[0]['bundle_available']


def test_missing_required_output_reported_and_unpublished_directory_ignored(tmp_path):
    job = completed_fixture(tmp_path)
    (job.bundle / 'alignments' / 'reads-one.bam.bai').unlink()
    item, = jobs.discover_jobs(tmp_path)
    assert not item['bundle_available']
    assert 'Missing file' in item['validation_error'] and '.bam.bai' in item['validation_error']
    jobs.update_metadata(job.output_dir, status='running')
    assert not jobs.discover_jobs(tmp_path)[0]['bundle_available']
    with pytest.raises(ValidationError, match='No completed bundle'):
        jobs.completed_bundle(job.output_dir)
    (job.output_dir / 'job.json').unlink()
    assert jobs.discover_jobs(tmp_path) == []


@pytest.mark.parametrize('unsafe', ['../outside', '/outside', 'alignments/../../outside', 'C:\\outside'])
def test_unsafe_inventory_rejected(tmp_path, unsafe):
    job = completed_fixture(tmp_path)
    manifest_path = job.bundle / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['files'][0]['path'] = unsafe
    manifest_path.write_text(json.dumps(manifest))
    assert not jobs.discover_jobs(tmp_path)[0]['bundle_available']


@pytest.mark.parametrize('target', ['alignments/reads-one.bam', 'alignments'])
def test_tracked_symlink_rejected(tmp_path, target):
    job = completed_fixture(tmp_path)
    path = job.bundle / target
    real = job.output_dir / 'relocated-asset'
    path.rename(real)
    path.symlink_to(real, target_is_directory=real.is_dir())
    with pytest.raises(ValidationError, match='Symlink'):
        jobs.completed_bundle(job.output_dir)


def test_render_defers_download_and_reuses_discovery(tmp_path, monkeypatch):
    from quickalign.ui import app
    job = completed_fixture(tmp_path)
    item, = jobs.discover_jobs(tmp_path)
    captured = []
    for name in ('write', 'caption', 'success', 'info', 'warning', 'error'):
        monkeypatch.setattr(app.st, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(app.st, 'download_button', lambda label, data, **kwargs: captured.append((data, kwargs)))
    def forbidden(*a, **kw):
        raise AssertionError('render must not repeat availability or load archive')
    with monkeypatch.context() as context:
        context.setattr(jobs, 'completed_bundle_info', forbidden)
        context.setattr(jobs, 'downloadable_archive', forbidden)
        context.setattr(Path, 'open', forbidden)
        context.setattr(Path, 'rglob', forbidden)
        app.render_result(UiConfig((tmp_path,), tmp_path, tmp_path / 'work'), item, 'result')
    callback, kwargs = captured[0]
    assert callable(callback) and kwargs['on_click'] == 'ignore'
    assert kwargs['mime'] == 'application/zip'
    assert callback() == b'fixture archive'
    # The rendered small file grows before the explicitly clicked callback.
    with (job.output_dir / item['archive_name']).open('wb') as stream:
        stream.truncate(5 * 1024**3)
    with pytest.raises(ValidationError, match='download limit'):
        callback()


def test_sparse_multigigabyte_placeholder_is_rejected_without_open(tmp_path, monkeypatch):
    job = completed_fixture(tmp_path)
    archive = job.output_dir / (job.bundle.name + '.zip')
    with archive.open('wb') as stream:
        stream.truncate(5 * 1024**3)
    forbid_payloads(monkeypatch)
    item, = jobs.discover_jobs(tmp_path)
    assert item['bundle_available'] and item['archive_size_bytes'] == 5 * 1024**3
    assert jobs.downloadable_archive(job.output_dir, 128 * 1024**2) is None
    with pytest.raises(ValidationError, match='download limit'):
        jobs.download_archive_bytes(job.output_dir, 128 * 1024**2)


@pytest.mark.parametrize('mode', ['symlink', 'directory', 'fifo', 'wrong-name', 'outside', 'failed'])
def test_unsafe_or_unfinished_archives_not_downloadable(tmp_path, mode):
    job = completed_fixture(tmp_path)
    archive = job.output_dir / (job.bundle.name + '.zip')
    archive.unlink()
    if mode == 'symlink':
        target = tmp_path / 'private'
        target.write_bytes(b'private')
        archive.symlink_to(target)
    elif mode == 'directory':
        archive.mkdir()
    elif mode == 'fifo':
        os.mkfifo(archive)
    else:
        archive.write_bytes(b'archive')
        jobs.update_metadata(job.output_dir, **({'archive': 'wrong.jbrowse.zip'} if mode == 'wrong-name'
                             else {'archive': '../outside.jbrowse.zip'} if mode == 'outside'
                             else {'export_status': 'failed'}))
    assert jobs.downloadable_archive(job.output_dir, 100) is None
    with pytest.raises(ValidationError):
        jobs.download_archive_bytes(job.output_dir, 100)


def test_download_read_has_hard_cap_despite_growth_after_fstat(tmp_path, monkeypatch):
    job = completed_fixture(tmp_path)
    archive = job.output_dir / (job.bundle.name + '.zip')
    original_fdopen = os.fdopen
    requested = []
    class GrowingReader:
        def __init__(self, fd):
            self.stream = original_fdopen(fd, 'rb', buffering=0)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def fileno(self):
            return self.stream.fileno()
        def read(self, limit):
            requested.append(limit)
            with archive.open('ab') as writer:
                writer.write(b'X' * 1000)
            return self.stream.read(limit)
    monkeypatch.setattr(jobs.os, 'fdopen', lambda fd, mode, **kwargs: GrowingReader(fd))
    with pytest.raises(ValidationError, match='download limit'):
        jobs.download_archive_bytes(job.output_dir, 32)
    assert requested == [33]


def test_export_rejects_unsafe_extra_and_preserves_completed_result(tmp_path):
    job = completed_fixture(tmp_path, archive=False)
    (job.bundle / 'extra-link').symlink_to(job.bundle / 'config.json')
    assert jobs.completed_bundle(job.output_dir) == job.bundle
    with pytest.raises(ValidationError, match='symlink'):
        jobs.export_zip(job.output_dir)
    assert jobs.read_metadata(job.output_dir)['export_status'] == 'failed'
    assert jobs.completed_bundle(job.output_dir) == job.bundle


def test_pinned_streamlit_registers_deferred_download_without_loading_zip(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    job = completed_fixture(tmp_path)
    forbid_payloads(monkeypatch)
    script = f'''
from pathlib import Path
from quickalign import jobs
from quickalign.ui.app import render_result
from quickalign.ui.config import UiConfig
root = Path({str(tmp_path)!r})
config = UiConfig((root,), root, root / 'work')
item, = jobs.discover_jobs(root)
render_result(config, item, 'result')
'''
    result = AppTest.from_string(script).run()
    assert not result.exception
    download, = result.get('download_button')
    assert download.proto.ignore_rerun
    assert download.proto.deferred_file_id
    assert not download.proto.url


@pytest.mark.parametrize('replacement', ['symlink', 'fifo'])
def test_download_rechecks_regular_file_after_metadata_inspection(tmp_path, monkeypatch, replacement):
    job = completed_fixture(tmp_path)
    archive = job.output_dir / (job.bundle.name + '.zip')
    original = jobs.downloadable_archive
    def swapped(*args):
        path = original(*args)
        archive.unlink()
        if replacement == 'symlink':
            archive.symlink_to(job.bundle / 'config.json')
        else:
            os.mkfifo(archive)
        return path
    monkeypatch.setattr(jobs, 'downloadable_archive', swapped)
    with pytest.raises((OSError, ValidationError)):
        jobs.download_archive_bytes(job.output_dir, 100)


def test_archive_stat_failure_does_not_change_bundle_availability(tmp_path, monkeypatch):
    completed_fixture(tmp_path)
    original = Path.lstat
    def denied(path, *args, **kwargs):
        if path.name.endswith('.zip'):
            raise PermissionError('cannot inspect ZIP')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', denied)
    item, = jobs.discover_jobs(tmp_path)
    assert item['bundle_available'] and 'validation_error' not in item
    assert 'archive_name' not in item
