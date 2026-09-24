"""Durable shared lifecycle; completed metadata is the publication authority."""
from __future__ import annotations
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid
import zipfile

from .errors import ValidationError
from .models import JobResult, ReservedJob

MAX_METADATA_BYTES = 2 * 1024 * 1024
JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def new_job_id():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def atomic_json(path: Path, data: dict):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=".job-", suffix=".json.tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, default=_json_default)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_metadata(output_dir):
    root = Path(output_dir)
    path = root / "job.json"
    if root.is_symlink() or path.is_symlink() or not path.is_file():
        raise ValidationError("Invalid job metadata")
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise ValidationError("Job metadata exceeds its size limit")
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValidationError("Unsupported job metadata schema")
    if not isinstance(value.get("job_id"), str) or not JOB_ID.fullmatch(value["job_id"]):
        raise ValidationError("Invalid job identifier")
    if value.get("status") not in {"running", "failed", "completed"}:
        raise ValidationError("Invalid job status")
    return value


def update_metadata(job_or_dir, **updates):
    root = job_or_dir.output_dir if isinstance(job_or_dir, ReservedJob) else Path(job_or_dir)
    data = read_metadata(root)
    data.update(updates)
    data["updated"] = timestamp()
    atomic_json(root / "job.json", data)
    return data


def fail_job(job_or_output_dir, error):
    """Best-effort failure recording without changing a terminal result."""
    root = job_or_output_dir.output_dir if isinstance(job_or_output_dir, ReservedJob) else Path(job_or_output_dir)
    try:
        data = read_metadata(root)
        if data["status"] != "running":
            return
        failure = {"type": type(error).__name__, "message": str(error)}
        for key in ("command", "returncode", "logs"):
            if getattr(error, key, None) is not None:
                failure[key] = getattr(error, key)
        update_metadata(root, status="failed", failure=failure, finished=timestamp())
    except (OSError, ValueError, ValidationError, TypeError):
        # Never mask the original failure, especially during interruption.
        return


def reserve_job(job_id, output_dir, work_root, run_spec):
    if not JOB_ID.fullmatch(job_id):
        raise ValidationError("Invalid job identifier")
    if not NAME.fullmatch(run_spec.name) or run_spec.name in {".", ".."}:
        raise ValidationError("Use a safe sample name containing letters, numbers, dots, dashes or underscores")
    output_dir = Path(output_dir).absolute()
    if output_dir.is_symlink():
        raise ValidationError("Output directory must not be a symlink")
    # exist_ok=False is the concurrency boundary: a prior job is never reused.
    output_dir.mkdir(parents=True, exist_ok=False)
    output_dir = output_dir.resolve(strict=True)
    work_root = Path(work_root).absolute()
    work = work_root / job_id
    job = ReservedJob(job_id, output_dir, work,
                      output_dir / f"{run_spec.name}.jbrowse.partial",
                      output_dir / f"{run_spec.name}.jbrowse", run_spec)
    initial = {"schema_version": 1, "job_id": job_id, "status": "running",
               "origin": run_spec.origin, "keep_work": run_spec.keep_work,
               "name": run_spec.name, "started": timestamp(), "updated": timestamp(),
               "output_dir": str(output_dir), "work_dir": str(work), "work_reserved": False,
               "warnings": [], "tracks": [], "commands": [], "export_status": "not_requested",
               "run_spec": asdict(run_spec)}
    try:
        atomic_json(output_dir / "job.json", initial)
        if work_root.is_symlink():
            raise ValidationError("Work root must not be a symlink")
        work_root.mkdir(parents=True, exist_ok=True)
        root = work_root.resolve(strict=True)
        work = root / job_id
        job = ReservedJob(job_id, output_dir, work, job.partial, job.bundle, run_spec)
        work.mkdir(exist_ok=False)
        (work / "tmp").mkdir()
        (output_dir / "logs").mkdir()
        update_metadata(job, work_dir=str(work), work_reserved=True)
        return job
    except BaseException as exc:
        # If initial write failed, attempt the durable failed record directly.
        if not (output_dir / "job.json").exists():
            initial.update(status="failed", failure={"type": type(exc).__name__, "message": str(exc)})
            try:
                atomic_json(output_dir / "job.json", initial)
            except OSError:
                pass
        else:
            fail_job(job, exc)
        raise


def cleanup_work(job):
    if job.spec.keep_work:
        return
    work = job.work
    if work.name != job.job_id or work.is_symlink():
        raise ValidationError("Unsafe scoped work directory")
    data = read_metadata(job.output_dir)
    if data["job_id"] != job.job_id or Path(data.get("work_dir", "")) != work:
        raise ValidationError("Work directory does not match job metadata")
    if work.exists() and data.get("work_reserved") is True:
        shutil.rmtree(work)


def _write_manifest(job, prepared):
    import csv
    with (job.output_dir / "read-groups.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["label", "technology", "layout", "read1", "read2"])
        for group in prepared.read_groups:
            writer.writerow([group.label, group.technology, group.layout, str(group.read1), str(group.read2 or "")])


def run_job(job, prepared_inputs=None):
    if not isinstance(job, ReservedJob):
        raise TypeError("run_job requires a ReservedJob")
    from .inputs import prepare_inputs
    from .commands import CommandRunner, probe_versions
    from .alignment import build_alignments
    from .annotation import build_annotation
    from .bundle import build_bundle, validate_bundle
    runner = None
    result = None
    try:
        data = read_metadata(job.output_dir)
        if data["job_id"] != job.job_id or data["status"] != "running":
            raise ValidationError("Job is not a running reservation")
        prepared = prepare_inputs(job.spec, prepared_inputs)
        _write_manifest(job, prepared)
        job.partial.mkdir(exist_ok=False)
        runner = CommandRunner(job)
        versions = probe_versions(runner)
        update_metadata(job, stage="alignments", tool_versions=versions)
        tracks = build_alignments(job, prepared, runner)
        update_metadata(job, stage="annotation")
        build_annotation(job, prepared, runner)
        warnings = list(runner.warnings)
        update_metadata(job, stage="bundle", warnings=[asdict(w) for w in warnings],
                        tracks=[_track_metadata(t) for t in tracks], commands=runner.records)
        build_bundle(job, prepared, tracks, runner, warnings, versions)
        validate_bundle(job.partial)
        # rename, fsync, then completed metadata: only this order publishes.
        if job.bundle.exists():
            raise ValidationError("Final bundle already exists")
        job.partial.rename(job.bundle)
        _fsync_dir(job.output_dir)
        update_metadata(job, status="completed", stage="completed", finished=timestamp(),
                        bundle=job.bundle.name, commands=runner.records,
                        warnings=[asdict(w) for w in warnings], tracks=[_track_metadata(t) for t in tracks])
        published_tracks = tuple(replace(t, bam=job.bundle / t.bam.relative_to(job.partial),
                                        bai=job.bundle / t.bai.relative_to(job.partial),
                                        flagstat=job.bundle / t.flagstat.relative_to(job.partial)) for t in tracks)
        result = JobResult(job.job_id, job.output_dir, job.bundle, tuple(warnings), published_tracks)
    except BaseException as exc:
        if runner is not None:
            try:
                update_metadata(job, commands=runner.records, warnings=[asdict(w) for w in runner.warnings])
            except (OSError, ValueError, TypeError, ValidationError):
                pass
        fail_job(job, exc)
        raise
    finally:
        try:
            cleanup_work(job)
        except (OSError, ValidationError) as exc:
            try:
                update_metadata(job, cleanup_error=str(exc))
            except (OSError, ValueError, ValidationError):
                pass
    # ZIP export is deliberately outside core failure handling.
    if job.spec.zip_export:
        archive = export_zip(job)
        result = JobResult(result.job_id, result.output_dir, result.bundle, result.warnings,
                           result.tracks, "completed", archive)
    return result


def _track_metadata(track):
    return {"track_id": track.track_id, "label": track.group.label,
            "technology": track.group.technology, "layout": track.group.layout,
            "mapped": track.mapped, "total": track.total,
            "zero_mapped": track.mapped == 0}


def completed_bundle(output_dir):
    from .bundle import validate_bundle
    root = Path(output_dir).resolve(strict=True)
    data = read_metadata(root)
    name = data.get("bundle")
    if data["status"] != "completed" or not isinstance(name, str):
        raise ValidationError("No validated completed bundle")
    if Path(name).name != name or not name.endswith(".jbrowse"):
        raise ValidationError("Unsafe bundle path")
    path = root / name
    if path.is_symlink() or not path.is_dir() or path.resolve().parent != root:
        raise ValidationError("Unsafe bundle directory")
    validate_bundle(path)
    return path


def export_zip(job):
    root = job.output_dir if isinstance(job, ReservedJob) else Path(job)
    bundle = completed_bundle(root)
    archive = root / f"{bundle.name}.zip"
    partial = root / f"{bundle.name}.zip.partial"
    update_metadata(root, export_status="running", export_started=timestamp())
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as output:
            for path in sorted(bundle.rglob("*")):
                if path.is_symlink():
                    raise ValidationError("Bundle contains a symlink")
                if path.is_file() and not path.name.endswith(".local.jbrowse"):
                    output.write(path, arcname=str(Path(bundle.name) / path.relative_to(bundle)))
        with zipfile.ZipFile(partial) as output:
            bad = output.testzip()
            if bad:
                raise ValidationError(f"ZIP verification failed: {bad}")
        with partial.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(partial, archive)
        _fsync_dir(root)
        update_metadata(root, export_status="completed", archive=archive.name, export_finished=timestamp())
        return archive
    except BaseException as exc:
        update_metadata(root, export_status="failed", export_error=str(exc), export_finished=timestamp())
        raise


def discover_jobs(output_root, active_job_id=None):
    """Bounded metadata discovery. Never reconcile/delete during discovery."""
    root = Path(output_root)
    if not root.is_dir():
        return []
    results = []
    for directory in sorted(root.iterdir(), reverse=True):
        if directory.is_symlink() or not directory.is_dir() or directory.name.startswith("."):
            continue
        try:
            data = read_metadata(directory)
            if data["job_id"] != directory.name:
                continue
            item = dict(data)
            item["display_status"] = ("interrupted" if data["status"] == "running" and data["job_id"] != active_job_id
                                      else "completed_with_warnings" if data["status"] == "completed" and data.get("warnings")
                                      else data["status"])
            item["bundle_available"] = False
            if data["status"] == "completed":
                try:
                    completed_bundle(directory)
                    item["bundle_available"] = True
                except (OSError, ValueError, ValidationError):
                    item["validation_error"] = "Bundle validation failed"
            if data.get("export_status") == "running" and data["job_id"] != active_job_id:
                item["export_display_status"] = "interrupted"
            else:
                item["export_display_status"] = data.get("export_status", "not_requested")
            results.append(item)
        except (OSError, ValueError, ValidationError):
            continue
    return results


def reconcile_work(output_root, work_root, active_job_id=None):
    """Startup-only cleanup; unknown work and keep-work jobs are preserved."""
    outputs, work = Path(output_root).resolve(), Path(work_root).resolve()
    removed = []
    if not work.is_dir():
        return removed
    for directory in work.iterdir():
        if directory.is_symlink() or not directory.is_dir() or directory.name == active_job_id:
            continue
        if not JOB_ID.fullmatch(directory.name):
            continue
        durable = outputs / directory.name
        try:
            if durable.is_symlink() or durable.resolve().parent != outputs:
                continue
            data = read_metadata(durable)
            if data["job_id"] != directory.name or data.get("keep_work") is not False or data.get("work_reserved") is not True:
                continue
            if Path(data.get("work_dir", "")) != directory or Path(data.get("output_dir", "")) != durable:
                continue
            shutil.rmtree(directory)
            removed.append(directory)
        except (OSError, ValueError, ValidationError):
            continue
    return removed


def downloadable_archive(output_dir, max_bytes):
    """Return only a bounded finished export of a validated completed bundle."""
    root = Path(output_dir)
    completed_bundle(root)
    data = read_metadata(root)
    name = data.get("archive")
    if data.get("export_status") != "completed" or not isinstance(name, str):
        return None
    if Path(name).name != name or not name.endswith(".jbrowse.zip"):
        return None
    path = root / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        return None
    return path
