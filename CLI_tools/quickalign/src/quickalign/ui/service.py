"""Process-global single-job gate and bounded upload staging; no Streamlit imports."""
from dataclasses import dataclass, field
from pathlib import Path
import threading

from quickalign import jobs
from quickalign.errors import ValidationError, QuickalignError
from quickalign.models import PreparedInputs, ReadGroup, RunSpec
from .paths import Selection, resolve, suffix


class BusyError(QuickalignError):
    pass


@dataclass
class ExecutionGate:
    lock: threading.Lock = field(default_factory=threading.Lock)
    active_job_id: str | None = None


GATE = ExecutionGate()
_STARTUP_LOCK = threading.Lock()
_INITIALIZED = set()


def initialize(config):
    """Called once for each process root pair, before submissions can acquire gate."""
    key = (config.output_root, config.work_root)
    with _STARTUP_LOCK:
        if key not in _INITIALIZED:
            with GATE.lock:
                jobs.reconcile_work(*key, active_job_id=GATE.active_job_id)
                _INITIALIZED.add(key)
    return GATE


@dataclass(frozen=True)
class Source:
    kind: str
    selection: Selection | None = None
    upload: object | None = None


@dataclass(frozen=True)
class ReadRow:
    label: str
    technology: str
    layout: str
    read1: Source
    read2: Source | None = None


@dataclass(frozen=True)
class Submission:
    reference: Source
    annotation: Source
    rows: tuple[ReadRow, ...]
    name: str
    threads: int = 4
    sort_memory: str = '256M'
    keep_work: bool = False


def _sources(submission):
    result = [(submission.reference, 'reference'), (submission.annotation, 'annotation')]
    for row in submission.rows:
        result.append((row.read1, 'reads'))
        if row.read2 is not None:
            result.append((row.read2, 'reads'))
    return result


def display_name(source):
    value = source.upload.name if source.kind == 'upload' else source.selection.relative
    return str(value).replace('\\', '/').rsplit('/', 1)[-1]


def validate_submission(config, submission):
    if not submission.name.strip() or not submission.rows:
        raise ValidationError('Provide a sample name and at least one read group')
    if not 2 <= submission.threads <= config.max_threads:
        raise ValidationError('Thread count exceeds the configured range')
    count = total = 0
    for source, kind in _sources(submission):
        if source is None:
            raise ValidationError('Select all required input files')
        if source.kind == 'server' and source.selection is not None:
            resolve(config, source.selection, kind, expect_file=True)
        elif source.kind == 'upload' and source.upload is not None:
            upload = source.upload
            if not suffix(str(upload.name), kind):
                raise ValidationError('Unsupported upload file type')
            size = getattr(upload, 'size', None)
            if not isinstance(size, int) or not 0 <= size <= config.max_upload_bytes:
                raise ValidationError('Upload exceeds the per-file limit')
            count += 1
            total += size
        else:
            raise ValidationError('Select all required input files')
    if count > config.max_upload_files or total > config.max_upload_total_bytes:
        raise ValidationError('Uploads exceed the file-count or total-size limit')
    for row in submission.rows:
        ReadGroup(row.label, row.technology, row.layout, Path('read1.fastq'),
                  Path('read2.fastq') if row.read2 is not None else None)


def submit(config, submission):
    validate_submission(config, submission)
    initialize(config)
    if not GATE.lock.acquire(blocking=False):
        raise BusyError('Another job is running. Try again after it finishes.')
    job = None
    output = None
    try:
        job_id = jobs.new_job_id()
        GATE.active_job_id = job_id
        output = config.output_root / job_id
        # Placeholders reserve the job before upload staging; prepared inputs replace them.
        placeholders = tuple(ReadGroup(r.label, r.technology, r.layout, Path('read1.fastq'),
                             Path('read2.fastq') if r.read2 else None) for r in submission.rows)
        spec = RunSpec(Path('reference.fasta'), Path('annotation.gff3'), placeholders,
                       submission.name, submission.threads, submission.sort_memory,
                       submission.keep_work, 'streamlit', False)
        job = jobs.reserve_job(job_id, output, config.work_root, spec)
        uploaded_total = 0
        sequence = 0

        def stage(source, kind):
            nonlocal uploaded_total, sequence
            if source.kind == 'server':
                return resolve(config, source.selection, kind, expect_file=True)
            upload = source.upload
            sequence += 1
            target = job.work / 'uploads' / f'{sequence:04d}{suffix(str(upload.name), kind)}'
            target.parent.mkdir(exist_ok=True)
            upload.seek(0)
            size = 0
            with target.open('xb') as handle:
                while chunk := upload.read(1024 * 1024):
                    size += len(chunk)
                    uploaded_total += len(chunk)
                    if size > config.max_upload_bytes or uploaded_total > config.max_upload_total_bytes:
                        raise ValidationError('Upload exceeds the configured size limit')
                    handle.write(chunk)
            if size != upload.size:
                raise ValidationError('Upload size changed during staging')
            return target

        reference = stage(submission.reference, 'reference')
        annotation = stage(submission.annotation, 'annotation')
        groups = tuple(ReadGroup(r.label, r.technology, r.layout, stage(r.read1, 'reads'),
                      stage(r.read2, 'reads') if r.read2 else None,
                      display_name(r.read1), display_name(r.read2) if r.read2 else None)
                      for r in submission.rows)
        return jobs.run_job(job, PreparedInputs(reference, annotation, groups,
                            reference_display=display_name(submission.reference),
                            annotation_display=display_name(submission.annotation)))
    except BaseException as error:
        if output is not None:
            jobs.fail_job(job or output, error)
        raise
    finally:
        try:
            if job is not None:
                try:
                    jobs.cleanup_work(job)
                except (OSError, ValidationError) as cleanup_error:
                    try:
                        jobs.update_metadata(job, cleanup_error=str(cleanup_error))
                    except (OSError, ValueError, ValidationError):
                        pass
        finally:
            GATE.active_job_id = None
            GATE.lock.release()
