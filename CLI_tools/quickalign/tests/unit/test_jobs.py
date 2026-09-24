from dataclasses import replace
import json
from pathlib import Path
import pytest
from quickalign.errors import ValidationError
from quickalign.models import RunSpec
from quickalign import jobs


def spec():
    return RunSpec(Path('reference.fa'), Path('annotation.gff'), (), 'sample')


def test_reservation_terminal_preservation_and_scoped_cleanup(tmp_path):
    other = tmp_path / 'work' / 'other'
    other.mkdir(parents=True)
    job = jobs.reserve_job('job-1', tmp_path / 'outputs' / 'job-1', tmp_path / 'work', spec())
    assert jobs.read_metadata(job.output_dir)['status'] == 'running'
    jobs.fail_job(job, ValueError('first'))
    jobs.fail_job(job, ValueError('second'))
    assert jobs.read_metadata(job.output_dir)['failure']['message'] == 'first'
    jobs.cleanup_work(job)
    assert not job.work.exists()
    assert other.exists()


def test_work_collision_retains_existing_work_and_failed_metadata(tmp_path):
    work = tmp_path / 'work' / 'collision'
    work.mkdir(parents=True)
    (work / 'precious').write_text('keep')
    out = tmp_path / 'out'
    with pytest.raises(FileExistsError):
        jobs.reserve_job('collision', out, work.parent, spec())
    assert jobs.read_metadata(out)['status'] == 'failed'
    assert (work / 'precious').read_text() == 'keep'
    assert jobs.reconcile_work(tmp_path, work.parent) == []


def test_discovery_never_reconciles_active_or_unknown_work(tmp_path):
    output, work = tmp_path / 'outputs', tmp_path / 'work'
    active = jobs.reserve_job('active', output / 'active', work, spec())
    prior = jobs.reserve_job('prior', output / 'prior', work, spec())
    kept = jobs.reserve_job('kept', output / 'kept', work, replace(spec(), keep_work=True))
    (work / 'unknown').mkdir()
    items = {item['job_id']: item for item in jobs.discover_jobs(output, 'active')}
    assert items['active']['display_status'] == 'running'
    assert items['prior']['display_status'] == 'interrupted'
    assert prior.work.exists()
    assert jobs.reconcile_work(output, work, 'active') == [prior.work]
    assert active.work.exists() and kept.work.exists() and (work / 'unknown').exists()


def test_atomic_json_and_size_limit(tmp_path):
    job = jobs.reserve_job('job', tmp_path / 'out', tmp_path / 'work', spec())
    jobs.update_metadata(job, stage='one')
    assert json.loads((job.output_dir / 'job.json').read_text())['stage'] == 'one'
    assert not list(job.output_dir.glob('.job-*'))
    (job.output_dir / 'job.json').write_bytes(b' ' * (jobs.MAX_METADATA_BYTES + 1))
    with pytest.raises(ValidationError):
        jobs.read_metadata(job.output_dir)


def test_completed_survives_failure_handler(tmp_path):
    job = jobs.reserve_job('job', tmp_path / 'out', tmp_path / 'work', spec())
    jobs.update_metadata(job, status='completed')
    jobs.fail_job(job, KeyboardInterrupt())
    assert jobs.read_metadata(job.output_dir)['status'] == 'completed'


def fake_pipeline(monkeypatch):
    import sys
    import types
    from quickalign.models import PreparedInputs
    class Runner:
        def __init__(self, job):
            self.records, self.warnings = [], []
    modules = {
        'inputs': {'prepare_inputs': lambda spec, prepared: PreparedInputs(spec.reference, spec.annotation, spec.read_groups)},
        'commands': {'CommandRunner': Runner, 'probe_versions': lambda runner: {'test': '1'}},
        'alignment': {'build_alignments': lambda *args: []},
        'annotation': {'build_annotation': lambda *args: None},
        'bundle': {'build_bundle': lambda *args: None, 'validate_bundle': lambda path: {}},
    }
    for name, attrs in modules.items():
        module = types.ModuleType('quickalign.' + name)
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, 'quickalign.' + name, module)


def test_failure_after_rename_not_published(monkeypatch, tmp_path):
    fake_pipeline(monkeypatch)
    job = jobs.reserve_job('job', tmp_path / 'out', tmp_path / 'work', spec())
    real_update = jobs.update_metadata
    def fail_completion(job, **updates):
        if updates.get('status') == 'completed':
            raise RuntimeError('interrupted after rename')
        return real_update(job, **updates)
    monkeypatch.setattr(jobs, 'update_metadata', fail_completion)
    with pytest.raises(RuntimeError):
        jobs.run_job(job)
    assert job.bundle.is_dir()
    assert jobs.read_metadata(job.output_dir)['status'] == 'failed'
    with pytest.raises(ValidationError):
        jobs.completed_bundle(job.output_dir)


def test_export_failure_keeps_completed_bundle(monkeypatch, tmp_path):
    fake_pipeline(monkeypatch)
    job = jobs.reserve_job('job', tmp_path / 'out', tmp_path / 'work', replace(spec(), zip_export=True))
    def broken(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(jobs.zipfile, 'ZipFile', broken)
    with pytest.raises(OSError, match='disk full'):
        jobs.run_job(job)
    data = jobs.read_metadata(job.output_dir)
    assert data['status'] == 'completed' and data['export_status'] == 'failed'
    assert jobs.completed_bundle(job.output_dir) == job.bundle
    assert jobs.downloadable_archive(job.output_dir, 100) is None


def test_keep_work_and_double_reservation(monkeypatch, tmp_path):
    fake_pipeline(monkeypatch)
    job = jobs.reserve_job('job', tmp_path / 'out', tmp_path / 'work', replace(spec(), keep_work=True))
    with pytest.raises(FileExistsError):
        jobs.reserve_job('other', job.output_dir, tmp_path / 'work', spec())
    jobs.run_job(job)
    assert job.work.exists()
    with pytest.raises(ValidationError):
        jobs.run_job(job)
    assert jobs.read_metadata(job.output_dir)['status'] == 'completed'


@pytest.mark.parametrize('field,value', [('status', []), ('warnings', 'oops'),
                                        ('failure', 'oops'), ('tracks', [1]),
                                        ('warnings', [{'message': []}])])
def test_malformed_metadata_is_not_discovered(tmp_path, field, value):
    output = tmp_path / 'outputs'
    job = jobs.reserve_job('job', output / 'job', tmp_path / 'work', spec())
    data = jobs.read_metadata(job.output_dir)
    data[field] = value
    jobs.atomic_json(job.output_dir / 'job.json', data)
    assert jobs.discover_jobs(output) == []
