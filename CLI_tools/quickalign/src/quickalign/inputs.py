"""Input validation and validating FASTQ streams."""
from __future__ import annotations

import gzip
import csv
import re
import zlib
from collections.abc import Iterator
from pathlib import Path

from .errors import ValidationError
from .models import InputWarning, PreparedInputs, ReadGroup, RunSpec

MAX_CONTIG_LENGTH = 1 << 29
FASTQ_SUFFIXES = (".fastq", ".fq", ".fastq.gz", ".fq.gz")
TRUNCATION_TEXT = "Some input reads could not be processed; these alignments may be incomplete."
GZIP_TRUNCATION_TEXT = (
    " Gzip integrity could not be verified because the final checksum is missing or incomplete; "
    "recovered reads have not passed that integrity check."
)


def _read_group(
    label: str, technology: str, layout: str, read1: Path, read2: Path | None,
    read1_display: str | None = None, read2_display: str | None = None,
) -> ReadGroup:
    kwargs = {}
    if "read1_display" in ReadGroup.__dataclass_fields__:
        kwargs = {"read1_display": read1_display, "read2_display": read2_display}
    return ReadGroup(label, technology, layout, read1, read2, **kwargs)


def _prepared_inputs(
    reference: Path, annotation: Path, groups: tuple[ReadGroup, ...], contigs: dict[str, int],
    reference_display: str | None = None, annotation_display: str | None = None,
) -> PreparedInputs:
    kwargs = {}
    if "reference_display" in PreparedInputs.__dataclass_fields__:
        kwargs = {"reference_display": reference_display, "annotation_display": annotation_display}
    return PreparedInputs(reference, annotation, groups, contigs, **kwargs)


def safe_id(value: str, *, default: str = "track") -> str:
    """Return a stable identifier suitable for read groups and filenames."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._").lower()
    return cleaned or default


def safe_name(value: str) -> str:
    """Public naming helper shared by CLI, jobs, and bundle code."""
    return safe_id(value, default="sample")


def track_ids(groups: tuple[ReadGroup, ...]) -> list[str]:
    """Create deterministic, collision-free IDs in input order."""
    used: set[str] = set()
    result: list[str] = []
    for group in groups:
        base = safe_id(group.label)
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}-{suffix}"
            suffix += 1
        used.add(candidate)
        result.append(candidate)
    return result


def parse_manifest(path: Path) -> tuple[ReadGroup, ...]:
    """Parse the documented read-groups TSV with paths relative to the TSV."""
    manifest = _require_file(Path(path), "Read-groups manifest")
    groups: list[ReadGroup] = []
    labels: set[str] = set()
    try:
        with manifest.open("rt", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, delimiter="\t")
            header = next(reader, None)
            if header != ["label", "technology", "layout", "read1", "read2"]:
                raise ValidationError("Read-groups manifest must begin with: label, technology, layout, read1, read2")
            for line_number, row in enumerate(reader, 2):
                if len(row) != 5:
                    raise ValidationError(f"Manifest line {line_number} must have exactly five tab-separated fields")
                label, technology, layout, read1, read2 = row
                if label in labels:
                    raise ValidationError(f"Manifest contains duplicate read-group label {label!r}")
                labels.add(label)
                if not read1:
                    raise ValidationError(f"Manifest line {line_number} has an empty read1 path")
                first = Path(read1)
                second = Path(read2) if read2 else None
                if not first.is_absolute():
                    first = manifest.parent / first
                if second is not None and not second.is_absolute():
                    second = manifest.parent / second
                groups.append(_read_group(label, technology, layout, first, second, read1, read2 or None))
    except (OSError, UnicodeError) as exc:
        raise ValidationError(f"Could not read manifest {manifest.name}: {exc}") from exc
    if not groups:
        raise ValidationError("Read-groups manifest contains no read groups")
    return tuple(groups)


def _require_file(path: Path, description: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValidationError(f"{description} does not exist or cannot be resolved: {path}") from exc
    if not resolved.is_file():
        raise ValidationError(f"{description} is not a regular file: {path}")
    try:
        with resolved.open("rb"):
            pass
    except OSError as exc:
        raise ValidationError(f"{description} is not readable: {path}") from exc
    return resolved


def _validate_reference(path: Path) -> dict[str, int]:
    contigs: dict[str, int] = {}
    current: str | None = None
    length = 0
    try:
        with path.open("rt", encoding="utf-8", newline=None) as handle:
            for line_number, line in enumerate(handle, 1):
                line = line.rstrip("\r\n")
                if line.startswith(">"):
                    if current is not None:
                        _store_contig(contigs, current, length)
                    current = line[1:].split(None, 1)[0] if line[1:].strip() else ""
                    if not current:
                        raise ValidationError(f"Reference FASTA has an empty identifier at line {line_number}")
                    if current in contigs:
                        raise ValidationError(f"Reference FASTA has duplicate sequence identifier: {current}")
                    length = 0
                elif not line:
                    continue
                elif current is None:
                    raise ValidationError("Reference FASTA contains sequence before its first header")
                else:
                    length += len(line)
                    if length > MAX_CONTIG_LENGTH:
                        raise ValidationError(
                            f"Reference contig {current!r} is longer than the supported {MAX_CONTIG_LENGTH} bases"
                        )
            if current is not None:
                _store_contig(contigs, current, length)
    except (OSError, UnicodeError) as exc:
        raise ValidationError(f"Could not read reference FASTA: {path.name}: {exc}") from exc
    if not contigs:
        raise ValidationError("Reference FASTA contains no sequences")
    return contigs


def _store_contig(contigs: dict[str, int], name: str, length: int) -> None:
    if length == 0:
        raise ValidationError(f"Reference FASTA sequence {name!r} is empty")
    if name in contigs:
        raise ValidationError(f"Reference FASTA has duplicate sequence identifier: {name}")
    if length > MAX_CONTIG_LENGTH:
        raise ValidationError(f"Reference contig {name!r} is longer than the supported {MAX_CONTIG_LENGTH} bases")
    contigs[name] = length


def _open_text(path: Path):
    if path.name.lower().endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("rt", encoding="utf-8", newline="")


def _validate_annotation(path: Path, contigs: dict[str, int]) -> None:
    feature_count = 0
    try:
        with _open_text(path) as handle:
            for line_number, line in enumerate(handle, 1):
                if line.startswith("##FASTA"):
                    break
                if not line.strip() or line.startswith("#"):
                    continue
                fields = line.rstrip("\r\n").split("\t")
                if len(fields) != 9:
                    raise ValidationError(f"Annotation line {line_number} must have exactly nine tab-separated columns")
                seqid = fields[0]
                if seqid not in contigs:
                    raise ValidationError(f"Annotation line {line_number} uses unknown reference sequence {seqid!r}")
                try:
                    start, end = int(fields[3]), int(fields[4])
                except ValueError as exc:
                    raise ValidationError(f"Annotation line {line_number} has non-integer coordinates") from exc
                if start < 1 or end < start or end > contigs[seqid]:
                    raise ValidationError(
                        f"Annotation line {line_number} coordinates {start}-{end} are outside {seqid} (length {contigs[seqid]})"
                    )
                feature_count += 1
    except ValidationError:
        raise
    except (OSError, UnicodeError, gzip.BadGzipFile, EOFError) as exc:
        raise ValidationError(f"Could not read annotation {path.name}: {exc}") from exc
    if feature_count == 0:
        raise ValidationError("Annotation contains no feature rows before ##FASTA")


def normalize_mate_name(header: bytes) -> tuple[bytes, int | None]:
    """Return the conservative template name and optional mate number."""
    if not header.startswith(b"@"):
        raise ValidationError("FASTQ header must begin with '@'")
    parts = header[1:].rstrip(b"\r\n").split(None, 1)
    if not parts or not parts[0]:
        raise ValidationError("FASTQ header has an empty read identifier")
    name = parts[0]
    mate: int | None = None
    if name.endswith((b"/1", b"/2")):
        mate = int(chr(name[-1]))
        name = name[:-2]
    if len(parts) == 2:
        field = parts[1].split(b":", 1)[0]
        if field in (b"1", b"2"):
            whitespace_mate = int(field)
            if mate is not None and mate != whitespace_mate:
                raise ValidationError("FASTQ header has conflicting mate designators")
            mate = whitespace_mate
    return name, mate


class _TruncatedInput(Exception):
    def __init__(self, gzip_integrity_missing: bool = False):
        self.gzip_integrity_missing = gzip_integrity_missing


class _ByteSource:
    def __init__(self, handle, pending: bytes = b""):
        self.handle = handle
        self.pending = bytearray(pending)

    def read(self, size: int) -> bytes:
        while len(self.pending) < size:
            chunk = self.handle.read(max(65536, size - len(self.pending)))
            if not chunk:
                break
            self.pending.extend(chunk)
        result = bytes(self.pending[:size])
        del self.pending[:size]
        return result

    def read_byte(self) -> bytes:
        return self.read(1)


def _gzip_decoded_chunks(path: Path) -> Iterator[bytes]:
    """Decode gzip while reporting missing trailers separately from bad integrity."""
    try:
        with path.open("rb") as raw:
            source = _ByteSource(raw)
            while True:
                fixed = source.read(10)
                if not fixed:
                    return
                if len(fixed) < 10:
                    raise _TruncatedInput(True)
                if fixed[:3] != b"\x1f\x8b\x08" or fixed[3] & 0xE0:
                    raise ValidationError(f"FASTQ {path.name} has an invalid gzip header")
                flags = fixed[3]
                if flags & 4:
                    xlen_raw = source.read(2)
                    if len(xlen_raw) < 2:
                        raise _TruncatedInput(True)
                    xlen = int.from_bytes(xlen_raw, "little")
                    if len(source.read(xlen)) < xlen:
                        raise _TruncatedInput(True)
                for flag in (8, 16):
                    if flags & flag:
                        while True:
                            char = source.read_byte()
                            if not char:
                                raise _TruncatedInput(True)
                            if char == b"\0":
                                break
                if flags & 2 and len(source.read(2)) < 2:
                    raise _TruncatedInput(True)

                decoder = zlib.decompressobj(-zlib.MAX_WBITS)
                crc = size = 0
                while not decoder.eof:
                    compressed = source.read(65536)
                    if not compressed:
                        raise _TruncatedInput(True)
                    try:
                        decoded = decoder.decompress(compressed)
                    except zlib.error as exc:
                        raise ValidationError(f"FASTQ {path.name} has invalid DEFLATE data: {exc}") from exc
                    if decoded:
                        crc = zlib.crc32(decoded, crc)
                        size = (size + len(decoded)) & 0xFFFFFFFF
                        yield decoded
                    if decoder.unused_data:
                        source.pending[:0] = decoder.unused_data
                trailer = source.read(8)
                if len(trailer) < 8:
                    raise _TruncatedInput(True)
                expected_crc = int.from_bytes(trailer[:4], "little")
                expected_size = int.from_bytes(trailer[4:], "little")
                if expected_crc != crc or expected_size != size:
                    raise ValidationError(f"FASTQ {path.name} has a gzip CRC or length mismatch")
    except _TruncatedInput:
        raise
    except ValidationError:
        raise
    except OSError as exc:
        raise ValidationError(f"Could not read FASTQ {path.name}: {exc}") from exc


def _decoded_chunks(path: Path) -> Iterator[bytes]:
    if path.name.lower().endswith(".gz"):
        yield from _gzip_decoded_chunks(path)
    else:
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(65536):
                    yield chunk
        except OSError as exc:
            raise ValidationError(f"Could not read FASTQ {path.name}: {exc}") from exc


def _records(path: Path) -> Iterator[bytes]:
    """Yield complete validated records while always validating the gzip trailer."""
    lines: list[bytes] = []
    buffer = bytearray()
    try:
        for chunk in _decoded_chunks(path):
            buffer.extend(chunk)
            while True:
                newline = buffer.find(b"\n")
                if newline < 0:
                    break
                lines.append(bytes(buffer[: newline + 1]))
                del buffer[: newline + 1]
                _validate_partial_lines(path, lines)
                if len(lines) == 4:
                    yield _validated_record(path, lines)
                    lines = []
    except _TruncatedInput:
        # Already emitted records remain usable; an incomplete buffered record is discarded.
        raise
    if buffer:
        lines.append(bytes(buffer))
        _validate_partial_lines(path, lines)
    if lines:
        # A final quality line without a newline is complete when its length matches.
        if len(lines) == 4:
            yield _validated_record(path, lines)
        else:
            raise _TruncatedInput(False)


def _validated_record(path: Path, lines: list[bytes]) -> bytes:
    header, sequence, plus, quality = lines
    if not header.startswith(b"@"):
        raise ValidationError(f"FASTQ {path.name} has a record whose header does not begin with '@'")
    normalize_mate_name(header)
    if not plus.startswith(b"+"):
        raise ValidationError(f"FASTQ {path.name} has a record whose separator does not begin with '+'")
    if len(sequence.rstrip(b"\r\n")) != len(quality.rstrip(b"\r\n")):
        if not quality.endswith((b"\n", b"\r")):
            raise _TruncatedInput(False)
        raise ValidationError(f"FASTQ {path.name} has unequal sequence and quality lengths")
    return b"".join(lines)


def _validate_partial_lines(path: Path, lines: list[bytes]) -> None:
    if len(lines) == 1:
        if not lines[0].startswith(b"@"):
            raise ValidationError(f"FASTQ {path.name} has a record whose header does not begin with '@'")
        normalize_mate_name(lines[0])
    elif len(lines) == 3 and not lines[2].startswith(b"+"):
        raise ValidationError(f"FASTQ {path.name} has a record whose separator does not begin with '+'")


def validate_pair(group: ReadGroup) -> None:
    """Strictly validate separate or interleaved Illumina pairing."""
    try:
        if group.layout == "paired":
            assert group.read2 is not None
            left, right = iter(_records(group.read1)), iter(_records(group.read2))
            index = 0
            while True:
                r1 = next(left, None)
                r2 = next(right, None)
                if r1 is None or r2 is None:
                    if r1 is not r2:
                        raise ValidationError(f"Paired FASTQ files for {group.label!r} have unequal record counts")
                    return
                index += 1
                _require_mates(r1, r2, group.label, index)
        elif group.layout == "interleaved":
            records = iter(_records(group.read1))
            index = 0
            while True:
                r1 = next(records, None)
                if r1 is None:
                    return
                r2 = next(records, None)
                if r2 is None:
                    raise ValidationError(f"Interleaved FASTQ for {group.label!r} has an odd record count")
                index += 1
                _require_mates(r1, r2, group.label, index)
    except _TruncatedInput as exc:
        kind = "gzip stream" if exc.gzip_integrity_missing else "FASTQ record"
        raise ValidationError(f"Paired input for {group.label!r} has a truncated {kind}") from exc


def _require_mates(r1: bytes, r2: bytes, label: str, pair_number: int) -> None:
    name1, mate1 = normalize_mate_name(r1.splitlines()[0])
    name2, mate2 = normalize_mate_name(r2.splitlines()[0])
    if name1 != name2 or (mate1 is not None and mate1 != 1) or (mate2 is not None and mate2 != 2):
        raise ValidationError(f"Read pair {pair_number} in {label!r} has incompatible mate identifiers")


def validating_unpaired_records(path: Path) -> tuple[Iterator[bytes], list[InputWarning]]:
    """Return a single-pass complete-record stream and its mutable warning sink."""
    warnings: list[InputWarning] = []

    def stream() -> Iterator[bytes]:
        try:
            yield from _records(path)
        except _TruncatedInput as exc:
            code = "truncated_gzip" if exc.gzip_integrity_missing else "truncated_fastq"
            message = TRUNCATION_TEXT + (GZIP_TRUNCATION_TEXT if exc.gzip_integrity_missing else "")
            warnings.append(InputWarning("", "", path.name, code, message))
            return

    return stream(), warnings


def prepare_inputs(spec: RunSpec, prepared: PreparedInputs | None = None) -> PreparedInputs:
    """Resolve and validate all inputs before external tools run."""
    source = prepared or PreparedInputs(spec.reference, spec.annotation, spec.read_groups)
    reference = _require_file(source.reference, "Reference FASTA")
    if reference.name.lower().endswith(".gz"):
        raise ValidationError("Compressed reference FASTA is not supported")
    annotation = _require_file(source.annotation, "Annotation")
    if not annotation.name.lower().endswith((".gff", ".gff3", ".gff.gz", ".gff3.gz")):
        raise ValidationError("Annotation must use a .gff, .gff3, .gff.gz, or .gff3.gz suffix")
    if not source.read_groups:
        raise ValidationError("At least one read group is required")
    contigs = _validate_reference(reference)
    _validate_annotation(annotation, contigs)
    resolved_groups: list[ReadGroup] = []
    for group in source.read_groups:
        read1 = _require_file(group.read1, f"Read input for {group.label!r}")
        if not read1.name.lower().endswith(FASTQ_SUFFIXES):
            raise ValidationError(f"Unsupported FASTQ suffix: {read1.name}")
        read2 = _require_file(group.read2, f"Read 2 input for {group.label!r}") if group.read2 else None
        if read2 and not read2.name.lower().endswith(FASTQ_SUFFIXES):
            raise ValidationError(f"Unsupported FASTQ suffix: {read2.name}")
        if read2 and read1 == read2:
            raise ValidationError(f"Read group {group.label!r} uses the same file for both mates")
        resolved = _read_group(
            group.label, group.technology, group.layout, read1, read2,
            getattr(group, "read1_display", None), getattr(group, "read2_display", None),
        )
        if resolved.layout in {"paired", "interleaved"}:
            validate_pair(resolved)
        resolved_groups.append(resolved)
    return _prepared_inputs(
        reference, annotation, tuple(resolved_groups), contigs,
        getattr(source, "reference_display", None), getattr(source, "annotation_display", None),
    )
