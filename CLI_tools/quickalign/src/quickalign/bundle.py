"""Build and validate relocatable JBrowse Desktop bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlsplit

from . import __version__
from .errors import ValidationError
from .models import InputWarning, PreparedInputs, ReservedJob, TrackResult

SCHEMA_VERSION = 1
ANNOTATION_TRACK_ID = "annotation"
TEXT_ATTRIBUTES = "Name,ID,gene,gene_name,locus_tag,Alias"
REQUIRED_FILES = (
    "config.json",
    "README.html",
    "README.txt",
    "local.template.jbrowse",
    "resolve-local.sh",
    "resolve-local.ps1",
    "resolve-local.cmd",
    "reference/assembly.fasta",
    "reference/assembly.fasta.fai",
    "annotation/features.gff3.gz",
    "annotation/features.gff3.gz.tbi",
)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_json_bytes(value))


def _location(uri: str) -> dict[str, str]:
    return {"locationType": "UriLocation", "uri": uri}


def _display_name(path: Path) -> str:
    return Path(path).name


def _read_display(group: Any, which: str) -> str | None:
    path = getattr(group, which)
    if path is None:
        return None
    return getattr(group, f"{which}_display", None) or _display_name(path)


def _config(prepared: PreparedInputs, tracks: Iterable[TrackResult]) -> dict[str, Any]:
    tracks = tuple(tracks)
    if not prepared.contigs:
        raise ValidationError("The reference has no contigs")
    assembly_name = "assembly"
    ref_track_id = "assembly-ReferenceSequenceTrack"
    jbrowse_tracks: list[dict[str, Any]] = [
        {
            "type": "FeatureTrack",
            "trackId": ANNOTATION_TRACK_ID,
            "name": getattr(prepared, "annotation_display", None) or _display_name(prepared.annotation),
            "assemblyNames": [assembly_name],
            "adapter": {
                "type": "Gff3TabixAdapter",
                "gffGzLocation": _location("annotation/features.gff3.gz"),
                "index": {
                    "indexType": "TBI",
                    "location": _location("annotation/features.gff3.gz.tbi"),
                },
            },
        }
    ]
    for track in tracks:
        group = track.group
        jbrowse_tracks.append(
            {
                "type": "AlignmentsTrack",
                "trackId": track.track_id,
                "name": f"{group.label} ({group.layout})",
                "assemblyNames": [assembly_name],
                "category": ["Alignments", group.technology.title()],
                "metadata": {
                    "technology": group.technology,
                    "layout": group.layout,
                    "read1": _read_display(group, "read1"),
                    "read2": _read_display(group, "read2"),
                    "readGroupId": track.track_id,
                },
                "adapter": {
                    "type": "BamAdapter",
                    "bamLocation": _location(f"alignments/{track.track_id}.bam"),
                    "index": {
                        "indexType": "BAI",
                        "location": _location(f"alignments/{track.track_id}.bam.bai"),
                    },
                },
            }
        )

    first_contig, first_length = next(iter(prepared.contigs.items()))
    visible = [
        {"id": "reference", "type": "ReferenceSequenceTrack", "configuration": ref_track_id},
        {"id": "annotation", "type": "FeatureTrack", "configuration": ANNOTATION_TRACK_ID},
    ]
    if tracks:
        visible.append(
            {"id": tracks[0].track_id, "type": "AlignmentsTrack", "configuration": tracks[0].track_id}
        )
    return {
        "assemblies": [
            {
                "name": assembly_name,
                "sequence": {
                    "type": "ReferenceSequenceTrack",
                    "trackId": ref_track_id,
                    "adapter": {
                        "type": "IndexedFastaAdapter",
                        "fastaLocation": _location("reference/assembly.fasta"),
                        "faiLocation": _location("reference/assembly.fasta.fai"),
                    },
                },
            }
        ],
        "configuration": {"disableAnalytics": True},
        "tracks": jbrowse_tracks,
        "defaultSession": {
            "name": "quickalign default",
            "view": {
                "id": "linearGenomeView",
                "type": "LinearGenomeView",
                "displayedRegions": [
                    {
                        "assemblyName": assembly_name,
                        "refName": first_contig,
                        "start": 0,
                        "end": min(first_length, 100_000),
                    }
                ],
                "tracks": visible,
            },
        },
    }


_SH_RESOLVER = r'''#!/bin/sh
set -eu
bundle_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec python3 - "$bundle_dir" <<'PY'
import json, os, pathlib, sys, tempfile
root = pathlib.Path(sys.argv[1]).resolve(strict=True)
source = root / "local.template.jbrowse"
name = root.name[:-8] if root.name.endswith(".jbrowse") else root.name
target = root / (name + ".local.jbrowse")

def convert(value):
    if isinstance(value, list):
        return [convert(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "uri" in value:
        uri = value["uri"]
        if not isinstance(uri, str) or not uri or "\\" in uri:
            raise SystemExit("unsafe bundle URI")
        parts = pathlib.PurePosixPath(uri).parts
        if not parts or uri.startswith("/") or ".." in parts or ":" in parts[0]:
            raise SystemExit("unsafe bundle URI")
        resolved = (root / pathlib.Path(*parts)).resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError:
            raise SystemExit("bundle URI escapes bundle")
        result = {k: convert(v) for k, v in value.items() if k not in ("uri", "locationType")}
        result.update(locationType="LocalPathLocation", localPath=str(resolved))
        return result
    return {key: convert(item) for key, item in value.items()}

data = convert(json.loads(source.read_text(encoding="utf-8")))
fd, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=root)
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)
finally:
    try: os.unlink(temporary)
    except FileNotFoundError: pass
print(target)
PY
'''


_PS1_RESOLVER = r'''$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath($PSScriptRoot)
$Template = Join-Path $Root 'local.template.jbrowse'
$Leaf = Split-Path $Root -Leaf
$Stem = if ($Leaf.EndsWith('.jbrowse')) { $Leaf.Substring(0, $Leaf.Length - 8) } else { $Leaf }
$Target = Join-Path $Root ($Stem + '.local.jbrowse')

function Convert-Node($Node) {
    if ($null -eq $Node -or $Node -is [string] -or $Node -is [ValueType]) { return $Node }
    if ($Node -is [System.Collections.IEnumerable] -and $Node -isnot [PSCustomObject]) {
        return @($Node | ForEach-Object { Convert-Node $_ })
    }
    $Properties = @($Node.PSObject.Properties)
    $UriProperty = $Properties | Where-Object Name -eq 'uri'
    if ($UriProperty) {
        $Uri = [string]$UriProperty.Value
        if ([string]::IsNullOrWhiteSpace($Uri) -or [IO.Path]::IsPathRooted($Uri) -or $Uri.Contains('\') -or $Uri.Contains('://')) {
            throw 'Unsafe bundle URI'
        }
        $Segments = $Uri.Split('/')
        if ($Segments -contains '..' -or $Segments -contains '') { throw 'Unsafe bundle URI' }
        $Relative = $Segments -join [IO.Path]::DirectorySeparatorChar
        $Resolved = (Resolve-Path -LiteralPath (Join-Path $Root $Relative)).Path
        $Prefix = $Root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
        if (-not $Resolved.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Bundle URI escapes bundle' }
        $Out = [ordered]@{}
        foreach ($Property in $Properties) {
            if ($Property.Name -notin @('uri', 'locationType')) { $Out[$Property.Name] = Convert-Node $Property.Value }
        }
        $Out['locationType'] = 'LocalPathLocation'
        $Out['localPath'] = $Resolved
        return [PSCustomObject]$Out
    }
    $Out = [ordered]@{}
    foreach ($Property in $Properties) { $Out[$Property.Name] = Convert-Node $Property.Value }
    return [PSCustomObject]$Out
}

$Data = Convert-Node (Get-Content -LiteralPath $Template -Raw -Encoding UTF8 | ConvertFrom-Json)
$Temporary = Join-Path $Root ($Stem + '.local.jbrowse.' + [Guid]::NewGuid().ToString('N') + '.tmp')
try {
    $Data | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $Temporary -Encoding UTF8
    Move-Item -LiteralPath $Temporary -Destination $Target -Force
} finally {
    if (Test-Path -LiteralPath $Temporary) { Remove-Item -LiteralPath $Temporary -Force }
}
Write-Output $Target
'''


_CMD_RESOLVER = r'''@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0resolve-local.ps1"
exit /b %ERRORLEVEL%
'''


def _warnings_text(warnings: Iterable[InputWarning]) -> list[str]:
    return [f"[{item.code}] {item.group_label} / {item.input_name}: {item.message}" for item in warnings]


def _write_readmes(root: Path, sample: str, warnings: tuple[InputWarning, ...]) -> None:
    warning_lines = _warnings_text(warnings)
    warning_text = "\n".join(f"- {line}" for line in warning_lines) if warning_lines else "- None"
    text = f"""quickalign JBrowse Desktop bundle: {sample}

Opening the bundle
1. Keep this entire directory together.
2. On Linux/macOS, run ./resolve-local.sh from a terminal.
3. On Windows, double-click resolve-local.cmd, or run resolve-local.ps1 in PowerShell.
4. Open the generated {sample}.local.jbrowse file in JBrowse Desktop.

The generated local file contains paths for the bundle's current location. Run the resolver
again after moving the directory. Browser-downloaded archives may be blocked by Windows
Mark-of-the-Web; unblock the archive or scripts in Windows Properties if necessary.

Input warnings
{warning_text}
"""
    (root / "README.txt").write_text(text, encoding="utf-8", newline="\n")
    escaped = (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    (root / "README.html").write_text(
        "<!doctype html><meta charset=\"utf-8\"><title>quickalign bundle</title>"
        f"<pre>{escaped}</pre>\n",
        encoding="utf-8",
        newline="\n",
    )


def _iter_inventory_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if path.is_symlink():
            raise ValidationError(f"Symlinks are forbidden in bundles: {relative.as_posix()}")
        if path.is_file() and relative.as_posix() != "manifest.json" and not relative.name.endswith(".local.jbrowse"):
            yield path


def _file_record(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(
    job: ReservedJob,
    prepared: PreparedInputs,
    tracks: tuple[TrackResult, ...],
    warnings: tuple[InputWarning, ...],
    tool_versions: dict[str, str],
) -> dict[str, Any]:
    root = job.partial
    return {
        "schema": "quickalign-bundle",
        "schema_version": SCHEMA_VERSION,
        "application": {"name": "quickalign", "version": __version__},
        "sample_name": job.spec.name,
        "reference": {
            "display_name": getattr(prepared, "reference_display", None) or _display_name(job.spec.reference),
            "files": ["reference/assembly.fasta", "reference/assembly.fasta.fai"],
            "contigs": [{"name": name, "length": length} for name, length in prepared.contigs.items()],
        },
        "annotation": {
            "display_name": getattr(prepared, "annotation_display", None) or _display_name(job.spec.annotation),
            "track_id": ANNOTATION_TRACK_ID,
            "files": ["annotation/features.gff3.gz", "annotation/features.gff3.gz.tbi"],
        },
        "read_groups": [
            {
                "label": track.group.label,
                "technology": track.group.technology,
                "layout": track.group.layout,
                "track_id": track.track_id,
                "input_display_names": [
                    _read_display(track.group, "read1"),
                    *([_read_display(track.group, "read2")] if track.group.read2 else []),
                ],
                "files": [
                    f"alignments/{track.track_id}.bam",
                    f"alignments/{track.track_id}.bam.bai",
                    f"alignments/{track.track_id}.flagstat.txt",
                ],
                "counts": {"mapped": track.mapped, "total": track.total},
                "preset": "bwa-mem2 mem" if track.group.technology == "illumina" else "minimap2 map-ont",
            }
            for track in tracks
        ],
        "warnings": [asdict(item) for item in warnings],
        "tool_versions": dict(sorted(tool_versions.items())),
        "run": {"requested_threads": job.spec.threads, "sort_memory": job.spec.sort_memory},
        "jbrowse": {
            "cli_version": tool_versions.get("jbrowse", "unknown"),
            "compatibility": "JBrowse 2 Desktop",
            "annotation_track_id": ANNOTATION_TRACK_ID,
            "text_index_attributes": TEXT_ATTRIBUTES.split(","),
        },
        "files": [_file_record(root, path) for path in _iter_inventory_files(root)],
    }


def build_bundle(
    job: ReservedJob,
    prepared: PreparedInputs,
    tracks: Iterable[TrackResult],
    runner: Any,
    warnings: list[InputWarning],
    tool_versions: dict[str, str],
) -> None:
    """Finish the already-staged partial bundle and validate its contents."""
    root = job.partial
    tracks_tuple = tuple(tracks)
    warnings_tuple = tuple(warnings)
    if not root.is_dir() or root.is_symlink():
        raise ValidationError("Bundle staging directory is missing or unsafe")

    _write_json(root / "config.json", _config(prepared, tracks_tuple))
    runner.run(
        "jbrowse-text-index",
        [
            "jbrowse",
            "text-index",
            "--target",
            str(root / "config.json"),
            "--tracks",
            ANNOTATION_TRACK_ID,
            "--attributes",
            TEXT_ATTRIBUTES,
            "--force",
            "--quiet",
        ],
    )
    # text-index adds the aggregate textSearchAdapter to config.json.
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    _write_json(root / "config.json", config)
    (root / "local.template.jbrowse").write_bytes(_json_bytes(config))
    (root / "resolve-local.sh").write_text(_SH_RESOLVER, encoding="utf-8", newline="\n")
    os.chmod(root / "resolve-local.sh", 0o755)
    (root / "resolve-local.ps1").write_text(_PS1_RESOLVER, encoding="utf-8", newline="\n")
    (root / "resolve-local.cmd").write_text(_CMD_RESOLVER, encoding="utf-8", newline="\r\n")
    _write_readmes(root, job.spec.name, warnings_tuple)
    _write_json(root / "manifest.json", _manifest(job, prepared, tracks_tuple, warnings_tuple, tool_versions))
    validate_bundle(root)


def _safe_relative(value: Any, *, context: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValidationError(f"Unsafe relative path in {context}")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or value.startswith("/"):
        raise ValidationError(f"Non-relative URI in {context}: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValidationError(f"Unsafe relative path in {context}: {value!r}")
    if not path.parts or re.match(r"^[A-Za-z]:", path.parts[0]):
        raise ValidationError(f"Unsafe relative path in {context}: {value!r}")
    return path


def _contained_regular_file(root: Path, relative: PurePosixPath, *, context: str) -> Path:
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as exc:
            raise ValidationError(f"Missing file in {context}: {relative.as_posix()}") from exc
        if stat.S_ISLNK(mode):
            raise ValidationError(f"Symlink is forbidden in {context}: {relative.as_posix()}")
    if not candidate.is_file():
        raise ValidationError(f"Expected regular file in {context}: {relative.as_posix()}")
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise ValidationError(f"Path escapes bundle in {context}: {relative.as_posix()}") from exc
    return candidate


def _config_uris(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        if "uri" in value:
            yield value["uri"]
        for nested in value.values():
            yield from _config_uris(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _config_uris(nested)


def validate_bundle(path: Path) -> dict[str, Any]:
    """Validate inventory integrity and all portable adapter paths."""
    root = Path(path)
    if not root.is_dir() or root.is_symlink():
        raise ValidationError("Bundle path must be a non-symlink directory")
    for entry in root.rglob("*"):
        if entry.is_symlink():
            raise ValidationError(f"Symlinks are forbidden in bundles: {entry.relative_to(root)}")

    for relative in REQUIRED_FILES:
        _contained_regular_file(root, PurePosixPath(relative), context="required assets")
    trix_files = [item for item in (root / "trix").rglob("*") if item.is_file()] if (root / "trix").is_dir() else []
    if not trix_files:
        raise ValidationError("JBrowse text index is missing")

    manifest_path = _contained_regular_file(root, PurePosixPath("manifest.json"), context="manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("manifest.json is not valid UTF-8 JSON") from exc
    if manifest.get("schema") != "quickalign-bundle" or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError("Unsupported quickalign bundle manifest")
    records = manifest.get("files")
    if not isinstance(records, list):
        raise ValidationError("Manifest file inventory must be a list")
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValidationError("Invalid manifest file record")
        relative = _safe_relative(record.get("path"), context="manifest inventory")
        name = relative.as_posix()
        if name in seen or name == "manifest.json" or relative.name.endswith(".local.jbrowse"):
            raise ValidationError(f"Invalid manifest inventory entry: {name}")
        seen.add(name)
        candidate = _contained_regular_file(root, relative, context="manifest inventory")
        if type(record.get("size")) is not int or record["size"] != candidate.stat().st_size:
            raise ValidationError(f"Size mismatch for {name}")
        digest = _sha256(candidate)
        if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))) or digest != record["sha256"]:
            raise ValidationError(f"SHA-256 mismatch for {name}")

    actual = {item.relative_to(root).as_posix() for item in _iter_inventory_files(root)}
    if seen != actual:
        missing = sorted(actual - seen)
        extra = sorted(seen - actual)
        raise ValidationError(f"Manifest inventory mismatch (missing={missing}, extra={extra})")

    try:
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("config.json is not valid UTF-8 JSON") from exc
    uris = list(_config_uris(config))
    if not uris:
        raise ValidationError("config.json has no portable asset URIs")
    for uri in uris:
        relative = _safe_relative(uri, context="config.json")
        _contained_regular_file(root, relative, context="config.json")
    template = json.loads((root / "local.template.jbrowse").read_text(encoding="utf-8"))
    if template != config:
        raise ValidationError("Local template does not match portable config")
    return manifest
