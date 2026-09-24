import io
from pathlib import Path
from dataclasses import replace
import pytest

from quickalign import jobs
from quickalign.errors import ValidationError
from quickalign.ui.config import UiConfig
from quickalign.ui.paths import Selection, browse, resolve, redact
from quickalign.ui import service


@pytest.fixture
def config(tmp_path):
    inputs, outputs, work = [tmp_path / name for name in ('inputs', 'outputs', 'work')]
    for p in (inputs, outputs, work):
        p.mkdir()
    (inputs / 'ref.fa').write_text('>ref\nACGT\n')
    (inputs / 'genes.gff3').write_text('##gff-version 3\n')
    (inputs / 'reads.fastq').write_text('@read\nACGT\n+\nIIII\n')
    return UiConfig((inputs,), outputs, work)


def request(config):
    def source(name):
        return service.Source('server', Selection(0, name))
    return service.Submission(source('ref.fa'), source('genes.gff3'),
           (service.ReadRow('reads', 'nanopore', 'single', source('reads.fastq')),), 'sample')


def test_browser_containment_and_types(config, tmp_path):
    root = config.input_roots[0]
    (root / '.hidden.fastq').write_text('private')
    (root / 'escape.fastq').symlink_to(tmp_path / 'outside.fastq')
    (tmp_path / 'outside.fastq').write_text('outside')
    (root / 'hidden-alias.fastq').symlink_to(root / '.hidden.fastq')
    assert [x[0] for x in browse(config, Selection(0), 'reads')] == ['reads.fastq']
    for rel in ('../outside.fastq', '/etc/passwd', '.hidden.fastq', 'escape.fastq', 'hidden-alias.fastq'):
        with pytest.raises(ValidationError):
            resolve(config, Selection(0, rel), 'reads', expect_file=True)
    with pytest.raises(ValidationError):
        resolve(config, Selection(-1, 'reads.fastq'))
    assert '/work/private' not in redact('Failure /work/private/log.txt')


def test_config_mounts_and_upload_limits(config):
    env = {'QUICKALIGN_OUTPUT_ROOT': str(config.output_root), 'QUICKALIGN_WORK_ROOT': str(config.work_root)}
    loaded = UiConfig.load(env, input_base=config.input_roots[0])
    assert loaded.max_download_bytes == 128 * 1024**2
    with pytest.raises(ValidationError):
        UiConfig.load({**env, 'QUICKALIGN_MAX_UPLOAD_MIB': '129'}, input_base=config.input_roots[0])
    with pytest.raises(ValidationError):
        UiConfig.load({**env, 'QUICKALIGN_WORK_ROOT': str(config.output_root)}, input_base=config.input_roots[0])


def test_gate_rejects_before_reservation(config):
    service.initialize(config)
    with service.GATE.lock:
        with pytest.raises(service.BusyError):
            service.submit(config, request(config))
    assert list(config.output_root.iterdir()) == []


def test_gate_shared_across_imports_and_active_discovery(config, monkeypatch):
    import importlib
    assert importlib.import_module('quickalign.ui.service').GATE is service.GATE
    seen = []
    def core(job, prepared):
        assert service.GATE.active_job_id == job.job_id
        seen.extend(jobs.discover_jobs(config.output_root, service.GATE.active_job_id))
        assert job.work.exists()
        with pytest.raises(service.BusyError):
            service.submit(config, request(config))
        jobs.update_metadata(job, status='failed', failure={'message': 'fixture'})
        return None
    monkeypatch.setattr(jobs, 'run_job', core)
    service.submit(config, request(config))
    assert seen[0]['display_status'] == 'running'
    assert service.GATE.active_job_id is None
    assert not service.GATE.lock.locked()


@pytest.mark.parametrize('terminal', ['completed', 'failed'])
def test_control_exception_preserves_terminal_and_releases_gate(config, monkeypatch, terminal):
    class Rerun(BaseException):
        pass
    def core(job, prepared):
        jobs.update_metadata(job, status=terminal, failure={'message': 'original'}, bundle='sample.jbrowse')
        (job.bundle).mkdir()
        raise Rerun()
    monkeypatch.setattr(jobs, 'run_job', core)
    def cleanup(job):
        raise OSError('cleanup interruption')
    monkeypatch.setattr(jobs, 'cleanup_work', cleanup)
    with pytest.raises(Rerun):
        service.submit(config, request(config))
    output, = config.output_root.iterdir()
    metadata = jobs.read_metadata(output)
    assert metadata['status'] == terminal
    assert metadata['failure']['message'] == 'original'
    assert service.GATE.active_job_id is None and not service.GATE.lock.locked()


class Upload(io.BytesIO):
    def __init__(self, name, data):
        super().__init__(data)
        self.name, self.size = name, len(data)


def test_upload_paths_and_display_names(config, monkeypatch):
    submission = request(config)
    upload = Upload('../../private/reads.fastq', b'@x\nACGT\n+\nIIII\n')
    row = replace(submission.rows[0], read1=service.Source('upload', upload=upload))
    captured = []
    def core(job, prepared):
        read = prepared.read_groups[0]
        assert read.read1.is_relative_to(job.work / 'uploads')
        assert read.read1.name == '0001.fastq'
        assert read.read1_display == 'reads.fastq'
        assert read.read1.read_bytes() == upload.getvalue()
        captured.append(job)
        jobs.update_metadata(job, status='failed', failure={'message': 'fixture'})
    monkeypatch.setattr(jobs, 'run_job', core)
    service.submit(config, replace(submission, rows=(row,)))
    assert not captured[0].work.exists()
    with pytest.raises(ValidationError):
        service.validate_submission(replace(config, max_upload_bytes=1), replace(submission, rows=(row,)))


def test_navigation_rows_and_no_submission(config, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(UiConfig, 'load', classmethod(lambda cls: config))
    app = AppTest.from_file('/opt/quickalign/streamlit_app.py').run()
    assert not app.exception
    app.button(key='reference_use').disabled
    app.selectbox(key='reference_file_0_.').select(('ref.fa', False, Selection(0, 'ref.fa'))).run()
    app.button(key='reference_use').click().run()
    assert app.session_state['reference_selected'] == Selection(0, 'ref.fa')
    next(b for b in app.button if b.label == 'Add read group').click().run()
    assert len(app.session_state['row_ids']) == 2
    app.radio(key='read_0_layout').set_value('Paired').run()
    app.checkbox(key='read_0_interleaved').check().run()
    assert not any(x.key == 'read_0_r2_mode' for x in app.radio)
    app.selectbox(key='read_0_tech').select('Nanopore').run()
    assert not any(x.key == 'read_0_layout' for x in app.radio)
    assert list(config.output_root.iterdir()) == []
    assert not app.exception
