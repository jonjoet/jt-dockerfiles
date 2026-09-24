"""Exact external-tool argv construction and durable command execution."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .errors import CommandError
from .models import InputWarning, ReadGroup, ReservedJob


def allocate_threads(total: int) -> tuple[int, int]:
    """Split the ceiling between aligner workers and sort's main+worker threads."""
    if total < 2:
        raise ValueError("Streaming alignment requires at least two threads")
    if total == 2:
        return 1, 0
    sort_threads = max(1, total // 3)
    align_threads = max(1, total - 1 - sort_threads)
    return align_threads, sort_threads


def read_group_header(track_id: str, group: ReadGroup) -> str:
    platform = "ILLUMINA" if group.technology == "illumina" else "ONT"
    sample = group.label.replace("\t", " ").replace("\n", " ").replace("\r", " ")
    return f"@RG\\tID:{track_id}\\tSM:{sample}\\tPL:{platform}"


def align_argv(group: ReadGroup, track_id: str, reference: Path, bwa_prefix: Path, threads: int) -> list[str]:
    rg = read_group_header(track_id, group)
    if group.technology == "illumina":
        argv = ["bwa-mem2", "mem", "-t", str(threads), "-R", rg]
        if group.layout == "interleaved":
            argv.append("-p")
        argv.extend([str(bwa_prefix), str(group.read1)])
        if group.read2 is not None:
            argv.append(str(group.read2))
        return argv
    return [
        "minimap2", "-ax", "map-ont", "-t", str(threads), "-R", rg,
        str(reference), str(group.read1),
    ]


def sort_argv(output: Path, temp_prefix: Path, threads: int, memory: str) -> list[str]:
    return [
        "samtools", "sort", "-@", str(threads), "-m", memory,
        "-T", str(temp_prefix), "-o", str(output), "-",
    ]


def faidx_argv(reference: Path) -> list[str]:
    return ["samtools", "faidx", str(reference)]


def bwa_index_argv(reference: Path, prefix: Path) -> list[str]:
    return ["bwa-mem2", "index", "-p", str(prefix), str(reference)]


def index_argv(bam: Path) -> list[str]:
    return ["samtools", "index", "-b", str(bam), str(Path(f"{bam}.bai"))]


def quickcheck_argv(bam: Path) -> list[str]:
    return ["samtools", "quickcheck", "-v", str(bam)]


def view_header_argv(bam: Path) -> list[str]:
    return ["samtools", "view", "-H", str(bam)]


def flagstat_argv(bam: Path, threads: int) -> list[str]:
    return ["samtools", "flagstat", "-@", str(threads), str(bam)]


def bgzip_argv(source: Path) -> list[str]:
    return ["bgzip", "-c", str(source)]


def tabix_argv(gff: Path) -> list[str]:
    return ["tabix", "-f", "-p", "gff", str(gff)]


class CommandRunner:
    """Run commands without a shell and retain command/log metadata."""

    def __init__(self, job: ReservedJob):
        self.job = job
        self.records: list[dict[str, Any]] = []
        self.warnings: list[InputWarning] = []
        self.env = os.environ.copy()
        self.env["TMPDIR"] = str(job.work)
        (job.output_dir / "logs").mkdir(parents=True, exist_ok=True)

    def record(self, record: dict) -> None:
        self.records.append(dict(record))

    def run(
        self, step: str, argv: list[str], stdout_path: Path | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        log_root = self.job.output_dir / "logs"
        stderr_path = log_root / f"{step}.stderr.log"
        captured = subprocess.PIPE if stdout_path is None else None
        try:
            with stderr_path.open("wb") as stderr_handle:
                if stdout_path is None:
                    result = subprocess.run(argv, stdout=captured, stderr=stderr_handle, env=self.env, check=False)
                else:
                    stdout_path.parent.mkdir(parents=True, exist_ok=True)
                    with stdout_path.open("wb") as stdout_handle:
                        result = subprocess.run(argv, stdout=stdout_handle, stderr=stderr_handle, env=self.env, check=False)
        except OSError as exc:
            self.record({"step": step, "argv": argv, "error": str(exc), "stderr": str(stderr_path)})
            raise CommandError(f"Could not start {step}: {exc}", command=argv, logs=[stderr_path]) from exc
        record = {
            "step": step, "argv": list(argv), "returncode": result.returncode,
            "stderr": str(stderr_path),
        }
        if stdout_path is not None:
            record["stdout"] = str(stdout_path)
        self.record(record)
        if result.returncode:
            raise CommandError(
                f"{step} failed with exit code {result.returncode}", command=argv,
                returncode=result.returncode, logs=[stderr_path] + ([stdout_path] if stdout_path else []),
            )
        return result


def probe_versions(runner: CommandRunner) -> dict[str, str]:
    """Collect concise runtime tool version strings through the common runner."""
    probes = {
        "bwa-mem2": ["bwa-mem2", "version"],
        "minimap2": ["minimap2", "--version"],
        "samtools": ["samtools", "--version"],
        "bgzip": ["bgzip", "--version"],
        "tabix": ["tabix", "--version"],
        "jbrowse": ["jbrowse", "--version"],
    }
    versions: dict[str, str] = {}
    for name, argv in probes.items():
        result = runner.run(f"version-{name}", argv)
        text = (result.stdout or b"").decode("utf-8", "replace").strip()
        versions[name] = text.splitlines()[0] if text else "unknown"
    return versions
