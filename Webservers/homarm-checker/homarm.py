from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

DNA_ALPHABET = frozenset("ACGTRYSWKMBDHVN")
CIGAR_RE = re.compile(r"(\d+)([MIDNSHP=X])")


class HomarmError(RuntimeError):
    """User-facing error raised by the homology-arm checker."""


@dataclass(frozen=True)
class Alignment:
    qname: str
    qlen: int
    qstart: int
    qend: int
    strand: str
    tname: str
    tlen: int
    tstart: int
    tend: int
    nmatch: int
    block_len: int
    mapq: int
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def query_coverage(self) -> float:
        return (self.qend - self.qstart) / self.qlen if self.qlen else 0.0

    @property
    def identity(self) -> float:
        return self.nmatch / self.block_len if self.block_len else 0.0

    @property
    def cigar(self) -> str:
        return self.tags.get("cg", "")

    @property
    def cs(self) -> str:
        return self.tags.get("cs", "")


@dataclass(frozen=True)
class PairedCandidate:
    left: Alignment
    right: Alignment
    gap: int
    span_start: int
    span_end: int
    joined: Alignment | None = None

    @property
    def tname(self) -> str:
        return self.left.tname

    @property
    def strand(self) -> str:
        return self.left.strand

    @property
    def min_identity(self) -> float:
        return min(self.left.identity, self.right.identity)

    @property
    def min_coverage(self) -> float:
        return min(self.left.query_coverage, self.right.query_coverage)


@dataclass(frozen=True)
class RunResult:
    command: list[str]
    stdout: str
    stderr: str


def normalize_sequence(raw: str, label: str) -> str:
    sequence_parts: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(">"):
            continue
        sequence_parts.append(re.sub(r"\s+", "", stripped))
    sequence = "".join(sequence_parts).upper().replace("U", "T")
    if not sequence:
        raise HomarmError(f"{label} is empty.")
    invalid = sorted(set(sequence) - DNA_ALPHABET)
    if invalid:
        raise HomarmError(f"{label} contains unsupported character(s): {', '.join(invalid)}.")
    return sequence


def write_query_fasta(path: Path, left: str, right: str) -> None:
    path.write_text(f">joined\n{left + right}\n>left\n{left}\n>right\n{right}\n", encoding="utf-8")


def build_minimap2_command(reference_path: Path, query_path: Path, *, max_gap: int, kmer: int = 9, window: int = 1, threads: int = 2) -> list[str]:
    if max_gap < 1:
        raise HomarmError("Maximum arm separation must be positive.")
    if not 5 <= kmer <= 28:
        raise HomarmError("Minimizer k-mer length must be between 5 and 28.")
    if window < 1:
        raise HomarmError("Minimizer window must be at least 1.")
    return [
        "minimap2", "-x", "splice", "-c", "--cs=long", "--eqx",
        "-k", str(kmer), "-w", str(window), "-n", "1", "-m", "10", "-s", "10",
        "-G", str(max_gap), "-g", str(max_gap), "-u", "n", "--splice-flank=no",
        "--end-seed-pen", "0", "--no-end-flt", "-f", "1000000", "-U", "1,1000000",
        "--q-occ-frac", "0", "-P", "-t", str(max(1, threads)), str(reference_path), str(query_path),
    ]


def run_minimap2(command: Sequence[str], *, timeout_seconds: int = 300) -> RunResult:
    if shutil.which(command[0]) is None:
        raise HomarmError("minimap2 is not installed or is not on PATH. Build and run the provided Docker image.")
    try:
        completed = subprocess.run(list(command), check=False, capture_output=True, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise HomarmError(f"minimap2 exceeded the {timeout_seconds}-second timeout.") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "No error text was returned."
        raise HomarmError(f"minimap2 failed with exit code {completed.returncode}:\n{detail}")
    return RunResult(list(command), completed.stdout, completed.stderr)


def parse_paf(text: str) -> list[Alignment]:
    alignments: list[Alignment] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.rstrip("\n").split("\t")
        if len(fields) < 12:
            raise HomarmError(f"Malformed PAF line {line_number}: expected at least 12 columns.")
        tags: dict[str, str] = {}
        for field in fields[12:]:
            parts = field.split(":", 2)
            if len(parts) == 3:
                tags[parts[0]] = parts[2]
        try:
            alignments.append(Alignment(fields[0], int(fields[1]), int(fields[2]), int(fields[3]), fields[4], fields[5], int(fields[6]), int(fields[7]), int(fields[8]), int(fields[9]), int(fields[10]), int(fields[11]), tags))
        except ValueError as exc:
            raise HomarmError(f"Malformed numeric value on PAF line {line_number}.") from exc
    return alignments


def parse_cigar(cigar: str) -> list[tuple[int, str]]:
    if not cigar:
        return []
    parsed = [(int(length), op) for length, op in CIGAR_RE.findall(cigar)]
    if "".join(f"{length}{op}" for length, op in parsed) != cigar:
        raise HomarmError(f"Unsupported CIGAR string: {cigar}")
    return parsed


def intron_lengths(alignment: Alignment) -> list[int]:
    return [length for length, op in parse_cigar(alignment.cigar) if op == "N"]


def joined_arm_coverages(alignment: Alignment, left_length: int, right_length: int) -> tuple[float, float]:
    boundary = left_length
    total = left_length + right_length
    aligned_start = max(0, alignment.qstart)
    aligned_end = min(total, alignment.qend)
    left_overlap = max(0, min(aligned_end, boundary) - max(aligned_start, 0))
    right_overlap = max(0, min(aligned_end, total) - max(aligned_start, boundary))
    return left_overlap / left_length, right_overlap / right_length


def filter_arm_hits(alignments: Iterable[Alignment], qname: str, *, min_coverage: float, min_identity: float) -> list[Alignment]:
    hits = [a for a in alignments if a.qname == qname and a.query_coverage >= min_coverage and a.identity >= min_identity]
    return sorted(hits, key=lambda a: (a.tname, a.tstart, a.tend, a.strand, -a.identity, -a.query_coverage))


def _pair_geometry(left: Alignment, right: Alignment) -> tuple[int, int, int] | None:
    if left.tname != right.tname or left.strand != right.strand:
        return None
    if left.strand == "+":
        return right.tstart - left.tend, left.tstart, right.tend
    if left.strand == "-":
        return left.tstart - right.tend, right.tstart, left.tend
    return None


def pair_arm_hits(left_hits: Sequence[Alignment], right_hits: Sequence[Alignment], *, max_gap: int, max_overlap: int = 0, joined_alignments: Sequence[Alignment] = (), left_length: int, right_length: int, joined_min_coverage: float = 0.75) -> list[PairedCandidate]:
    candidates: list[PairedCandidate] = []
    seen: set[tuple[object, ...]] = set()
    for left in left_hits:
        for right in right_hits:
            geometry = _pair_geometry(left, right)
            if geometry is None:
                continue
            gap, span_start, span_end = geometry
            if gap < -max_overlap or gap > max_gap:
                continue
            key = (left.tname, left.strand, left.tstart, left.tend, right.tstart, right.tend)
            if key in seen:
                continue
            seen.add(key)
            joined = None
            span = max(1, span_end - span_start)
            for alignment in joined_alignments:
                if alignment.tname != left.tname or alignment.strand != left.strand:
                    continue
                gaps = intron_lengths(alignment)
                if not gaps or max(gaps) > max_gap:
                    continue
                lcov, rcov = joined_arm_coverages(alignment, left_length, right_length)
                overlap = max(0, min(span_end, alignment.tend) - max(span_start, alignment.tstart)) / span
                if min(lcov, rcov) >= joined_min_coverage and overlap >= 0.8:
                    if joined is None or alignment.identity > joined.identity:
                        joined = alignment
            candidates.append(PairedCandidate(left, right, gap, span_start, span_end, joined))
    return sorted(candidates, key=lambda c: (-c.min_identity, -c.min_coverage, -(c.left.nmatch + c.right.nmatch), c.tname, c.span_start, c.strand))


def arm_hit_rows(hits: Sequence[Alignment], arm: str) -> list[dict[str, object]]:
    return [{"arm": arm, "target": h.tname, "strand": h.strand, "target_start_1based": h.tstart + 1, "target_end_1based": h.tend, "query_coverage_pct": round(h.query_coverage * 100, 2), "identity_pct": round(h.identity * 100, 2), "matches": h.nmatch, "alignment_block_length": h.block_len, "mapq": h.mapq, "cigar": h.cigar, "cs": h.cs} for h in hits]


def candidate_rows(candidates: Sequence[PairedCandidate]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for rank, c in enumerate(candidates, start=1):
        rows.append({"rank": rank, "target": c.tname, "strand": c.strand, "span_start_1based": c.span_start + 1, "span_end_1based": c.span_end, "arm_gap_bp": c.gap, "left_start_1based": c.left.tstart + 1, "left_end_1based": c.left.tend, "left_coverage_pct": round(c.left.query_coverage * 100, 2), "left_identity_pct": round(c.left.identity * 100, 2), "right_start_1based": c.right.tstart + 1, "right_end_1based": c.right.tend, "right_coverage_pct": round(c.right.query_coverage * 100, 2), "right_identity_pct": round(c.right.identity * 100, 2), "joined_support": c.joined is not None, "joined_cigar": c.joined.cigar if c.joined else "", "joined_cs": c.joined.cs if c.joined else ""})
    return rows


def rows_to_tsv(rows: Sequence[dict[str, object]]) -> str:
    if not rows:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
