"""Normalize, sort, compress, and index GFF annotation."""
from __future__ import annotations

import gzip
from pathlib import Path

from .commands import bgzip_argv, tabix_argv
from .errors import ValidationError
from .models import PreparedInputs, ReservedJob


def _open_annotation(path: Path):
    if path.name.lower().endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("rt", encoding="utf-8", newline="")


def normalize_annotation(source: Path, destination: Path, contigs: dict[str, int]) -> None:
    """Write directives followed by stably coordinate-sorted feature rows."""
    directives: list[str] = []
    features: list[tuple[int, int, int, int, str]] = []
    saw_feature = False
    order = {name: index for index, name in enumerate(contigs)}
    try:
        with _open_annotation(source) as handle:
            for input_index, line in enumerate(handle):
                if line.startswith("##FASTA"):
                    break
                if not line.strip():
                    continue
                if line.startswith("#"):
                    if not saw_feature:
                        directives.append(line.rstrip("\r\n"))
                    continue
                saw_feature = True
                fields = line.rstrip("\r\n").split("\t")
                if len(fields) != 9:
                    raise ValidationError(f"Annotation line {input_index + 1} must have exactly nine columns")
                seqid = fields[0]
                if seqid not in contigs:
                    raise ValidationError(f"Annotation uses unknown reference sequence {seqid!r}")
                try:
                    start, end = int(fields[3]), int(fields[4])
                except ValueError as exc:
                    raise ValidationError(f"Annotation line {input_index + 1} has invalid coordinates") from exc
                if start < 1 or end < start or end > contigs[seqid]:
                    raise ValidationError(f"Annotation coordinates {start}-{end} are outside {seqid}")
                features.append((order[seqid], start, end, input_index, "\t".join(fields)))
    except ValidationError:
        raise
    except (OSError, UnicodeError, EOFError, gzip.BadGzipFile) as exc:
        raise ValidationError(f"Could not normalize annotation {source.name}: {exc}") from exc
    if not features:
        raise ValidationError("Annotation contains no feature rows before ##FASTA")
    features.sort(key=lambda row: row[:4])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wt", encoding="utf-8", newline="\n") as output:
        for directive in directives:
            output.write(directive + "\n")
        for *_, line in features:
            output.write(line + "\n")


def build_annotation(job: ReservedJob, prepared: PreparedInputs, runner) -> None:
    """Create the fixed portable GFF3 path and its tabix index."""
    annotation_dir = job.partial / "annotation"
    annotation_dir.mkdir(parents=True, exist_ok=True)
    normalized = job.work / "features.sorted.gff3"
    compressed = annotation_dir / "features.gff3.gz"
    normalize_annotation(prepared.annotation, normalized, prepared.contigs)
    runner.run("annotation-bgzip", bgzip_argv(normalized), stdout_path=compressed)
    runner.run("annotation-tabix", tabix_argv(compressed))
