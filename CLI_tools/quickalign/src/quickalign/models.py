"""Immutable contracts shared by every quickalign entry point."""
from dataclasses import dataclass, field
from pathlib import Path
from .errors import ValidationError

@dataclass(frozen=True)
class ReadGroup:
    label: str
    technology: str
    layout: str
    read1: Path
    read2: Path | None = None
    read1_display: str | None = None
    read2_display: str | None = None

    def __post_init__(self):
        if not self.label.strip():
            raise ValidationError("Read-group labels must not be empty")
        valid = {("illumina", "single"), ("illumina", "paired"),
                 ("illumina", "interleaved"), ("nanopore", "single")}
        if (self.technology, self.layout) not in valid:
            raise ValidationError("Unsupported read-group technology/layout")
        if (self.layout == "paired") != (self.read2 is not None):
            raise ValidationError("Only separate paired reads require read2")
        object.__setattr__(self, "read1", Path(self.read1))
        if self.read2 is not None:
            object.__setattr__(self, "read2", Path(self.read2))

@dataclass(frozen=True)
class RunSpec:
    reference: Path
    annotation: Path
    read_groups: tuple[ReadGroup, ...]
    name: str
    threads: int = 4
    sort_memory: str = "256M"
    keep_work: bool = False
    origin: str = "cli"
    zip_export: bool = False

    def __post_init__(self):
        object.__setattr__(self, "reference", Path(self.reference))
        object.__setattr__(self, "annotation", Path(self.annotation))
        object.__setattr__(self, "read_groups", tuple(self.read_groups))

@dataclass(frozen=True)
class InputWarning:
    group_id: str
    group_label: str
    input_name: str
    code: str
    message: str

@dataclass(frozen=True)
class PreparedInputs:
    reference: Path
    annotation: Path
    read_groups: tuple[ReadGroup, ...]
    contigs: dict[str, int] = field(default_factory=dict)
    reference_display: str | None = None
    annotation_display: str | None = None

@dataclass(frozen=True)
class ReservedJob:
    job_id: str
    output_dir: Path
    work: Path
    partial: Path
    bundle: Path
    spec: RunSpec

@dataclass(frozen=True)
class TrackResult:
    track_id: str
    group: ReadGroup
    bam: Path
    bai: Path
    flagstat: Path
    mapped: int
    total: int

@dataclass(frozen=True)
class JobResult:
    job_id: str
    output_dir: Path
    bundle: Path
    warnings: tuple[InputWarning, ...] = ()
    tracks: tuple[TrackResult, ...] = ()
    export_status: str = "not_requested"
    archive: Path | None = None
