"""Reference indexing and sequential read-group alignment."""
from __future__ import annotations

import shutil
import subprocess
import re
from pathlib import Path

from .commands import (
    align_argv, allocate_threads, bwa_index_argv, faidx_argv, flagstat_argv,
    index_argv, quickcheck_argv, read_group_header, sort_argv, view_header_argv,
)
from .errors import CommandError, ValidationError
from .inputs import track_ids, validating_unpaired_records
from .models import InputWarning, PreparedInputs, ReservedJob, TrackResult


def _pipeline(
    runner, step: str, align: list[str], sort: list[str], records=None
) -> None:
    logs = runner.job.output_dir / "logs"
    align_stderr_path = logs / f"{step}.align.stderr.log"
    sort_stderr_path = logs / f"{step}.sort.stderr.log"
    align_stdin = subprocess.PIPE if records is not None else None
    aligner = sorter = None
    align_code = sort_code = None
    stream_error: BaseException | None = None
    lifecycle_error: BaseException | None = None
    with align_stderr_path.open("wb") as align_err, sort_stderr_path.open("wb") as sort_err:
        try:
            aligner = subprocess.Popen(
                align, stdin=align_stdin, stdout=subprocess.PIPE, stderr=align_err, env=runner.env
            )
            assert aligner.stdout is not None
            sorter = subprocess.Popen(sort, stdin=aligner.stdout, stdout=subprocess.DEVNULL, stderr=sort_err, env=runner.env)
            aligner.stdout.close()
            if records is not None:
                assert aligner.stdin is not None
                pipe_open = True
                try:
                    for record in records:
                        if pipe_open:
                            try:
                                aligner.stdin.write(record)
                            except BrokenPipeError:
                                pipe_open = False
                except BaseException as exc:
                    stream_error = exc
                finally:
                    try:
                        aligner.stdin.close()
                    except BrokenPipeError:
                        pass
            if stream_error is not None:
                for process in (aligner, sorter):
                    if process.poll() is None:
                        process.terminate()
            align_code = aligner.wait()
            sort_code = sorter.wait()
        except OSError as exc:
            lifecycle_error = exc
            raise CommandError(f"Could not start alignment pipeline for {step}: {exc}", logs=[align_stderr_path, sort_stderr_path]) from exc
        except BaseException as exc:
            lifecycle_error = exc
            raise
        finally:
            for stream in (
                getattr(aligner, "stdin", None), getattr(aligner, "stdout", None),
                getattr(sorter, "stdin", None), getattr(sorter, "stdout", None),
            ):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            if stream_error is not None or lifecycle_error is not None:
                for process in (aligner, sorter):
                    if process is not None and process.poll() is None:
                        process.terminate()
                for process in (aligner, sorter):
                    if process is not None:
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
            # Covers interruption and failure while launching the second child.
            if sorter is None:
                if aligner is not None and aligner.poll() is None:
                    aligner.terminate()
                    aligner.wait()
    if align_code is None or sort_code is None:
        raise CommandError(f"Alignment pipeline {step} did not start both processes", logs=[align_stderr_path, sort_stderr_path])
    runner.record({
        "step": f"{step}-align", "argv": align, "returncode": align_code,
        "stderr": str(align_stderr_path), "stdout": "pipe:sort",
    })
    runner.record({
        "step": f"{step}-sort", "argv": sort, "returncode": sort_code,
        "stderr": str(sort_stderr_path), "stdin": "pipe:align",
    })
    if stream_error is not None:
        raise stream_error
    if align_code or sort_code:
        raise CommandError(
            f"Alignment pipeline {step} failed (aligner={align_code}, sort={sort_code})",
            command={"align": align, "sort": sort}, returncode=(align_code, sort_code),
            logs=[align_stderr_path, sort_stderr_path],
        )


def _parse_flagstat(text: str) -> tuple[int, int]:
    total = mapped = 0
    for line in text.splitlines():
        match = re.match(r"^(\d+) \+ (\d+) (.*)$", line)
        if not match:
            continue
        count = int(match.group(1)) + int(match.group(2))
        description = match.group(3)
        if description.startswith("in total "):
            total = count
        elif description.startswith("mapped ("):
            mapped = count
    return mapped, total


def _verify_bam(runner, track_id: str, bam: Path, expected_rg: str, threads: int, flagstat: Path) -> tuple[int, int]:
    runner.run(f"{track_id}.quickcheck", quickcheck_argv(bam))
    header = runner.run(f"{track_id}.header", view_header_argv(bam)).stdout.decode("utf-8", "replace")
    hd_lines = [line for line in header.splitlines() if line.startswith("@HD")]
    if not hd_lines or not any("SO:coordinate" in line.split("\t") for line in hd_lines):
        raise ValidationError(f"BAM for {track_id} does not declare coordinate sort order")
    if expected_rg not in header.splitlines():
        raise ValidationError(f"BAM for {track_id} does not contain its expected read-group header")
    runner.run(f"{track_id}.flagstat", flagstat_argv(bam, threads), stdout_path=flagstat)
    return _parse_flagstat(flagstat.read_text(encoding="utf-8"))


def build_alignments(job: ReservedJob, prepared: PreparedInputs, runner) -> list[TrackResult]:
    """Stage/index the reference and build one checked BAM per read group."""
    reference_dir = job.partial / "reference"
    alignments_dir = job.partial / "alignments"
    bwa_dir = job.work / "bwa"
    sort_dir = job.work / "sort"
    for directory in (reference_dir, alignments_dir, bwa_dir, sort_dir):
        directory.mkdir(parents=True, exist_ok=True)
    reference = reference_dir / "assembly.fasta"
    shutil.copyfile(prepared.reference, reference)
    runner.run("reference-index", faidx_argv(reference))
    bwa_prefix = bwa_dir / "reference"
    if any(group.technology == "illumina" for group in prepared.read_groups):
        runner.run("bwa-index", bwa_index_argv(reference, bwa_prefix))

    align_threads, sort_threads = allocate_threads(job.spec.threads)
    runner.record({
        "step": "thread-allocation", "requested": job.spec.threads,
        "aligner_threads": align_threads, "sort_worker_threads": sort_threads,
        "sort_main_threads": 1,
    })
    results: list[TrackResult] = []
    for group, track_id in zip(prepared.read_groups, track_ids(prepared.read_groups), strict=True):
        bam = alignments_dir / f"{track_id}.bam"
        bai = Path(f"{bam}.bai")
        flagstat = alignments_dir / f"{track_id}.flagstat.txt"
        align = align_argv(group, track_id, reference, bwa_prefix, align_threads)
        records = None
        stream_warnings: list[InputWarning] = []
        if group.layout == "single":
            records, stream_warnings = validating_unpaired_records(group.read1)
            align[-1] = "-"
        sort = sort_argv(bam, sort_dir / track_id, sort_threads, job.spec.sort_memory)
        try:
            _pipeline(runner, track_id, align, sort, records)
        finally:
            for warning in stream_warnings:
                input_name = getattr(group, "read1_display", None) or group.read1.name
                runner.warnings.append(InputWarning(track_id, group.label, input_name, warning.code, warning.message))
        runner.run(f"{track_id}.index", index_argv(bam))
        mapped, total = _verify_bam(
            runner, track_id, bam, read_group_header(track_id, group).replace("\\t", "\t"),
            max(0, job.spec.threads - 1), flagstat,
        )
        results.append(TrackResult(track_id, group, bam, bai, flagstat, mapped, total))
    return results
