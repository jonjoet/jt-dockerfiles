"""Real tool publication records one checksum per asset, then metadata only."""
from collections import Counter
import json
from pathlib import Path
import zipfile

from quickalign import bundle, jobs
from test_failures import reserve


def test_publication_discovery_and_export_do_not_rehash(tmp_path, monkeypatch):
    calls = Counter()
    original = bundle._sha256
    def counted(path):
        calls[path.relative_to(job.partial).as_posix()] += 1
        return original(path)
    monkeypatch.setattr(bundle, '_sha256', counted)
    job, _ = reserve(tmp_path, 'nanopore', lambda record: record)
    result = jobs.run_job(job)
    manifest = json.loads((result.bundle / 'manifest.json').read_text())
    assert calls == Counter({entry['path']: 1 for entry in manifest['files']})
    def forbidden(*args, **kwargs):
        raise AssertionError('completed output must not rehash')
    monkeypatch.setattr(bundle, '_sha256', forbidden)
    for _ in range(2):
        assert jobs.discover_jobs(job.output_dir.parent)[0]['bundle_available']
    archive = jobs.export_zip(job.output_dir)
    with zipfile.ZipFile(archive) as opened:
        assert opened.testzip() is None
    assert jobs.download_archive_bytes(job.output_dir, 1024**2) == archive.read_bytes()
    (tmp_path / 'checksum-counts.json').write_text(json.dumps(calls, indent=2))
