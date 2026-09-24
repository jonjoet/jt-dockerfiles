"""Build and validate relocatable JBrowse Desktop bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlsplit

from . import __version__
from .errors import ValidationError
from .models import InputWarning, PreparedInputs, ReservedJob, TrackResult

SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_CONFIG_BYTES = 16 * 1024 * 1024
ANNOTATION_TRACK_ID = "annotation"
LOCAL_ROOT_TOKEN = "__QUICKALIGN_BUNDLE_ROOT__"
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
    visible = [ref_track_id, ANNOTATION_TRACK_ID]
    if tracks:
        visible.append(tracks[0].track_id)
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
            "views": [{
                "id": "linearGenomeView",
                "type": "LinearGenomeView",
                "init": {
                    "assembly": assembly_name,
                    "loc": f"{first_contig}:1..{min(first_length, 100_000)}",
                    "tracks": visible,
                },
            }],
        },
    }


def _localize_config(value: Any) -> Any:
    """Create the Desktop template without changing portable configuration."""
    if isinstance(value, list):
        return [_localize_config(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _localize_config(item) for key, item in value.items()}
    if "localPath" in result or result.get("locationType") == "LocalPathLocation":
        raise ValidationError("Portable config must not contain local filesystem locations")
    if "uri" in result:
        relative = _safe_relative(result["uri"], context="local template")
        if "baseUri" in result:
            raise ValidationError("Portable config locations must not contain baseUri")
        result.pop("uri")
        result.update(locationType="LocalPathLocation", localPath=f"{LOCAL_ROOT_TOKEN}/{relative}")
    return result


_SH_RESOLVER = r'''#!/usr/bin/env bash
set -euo pipefail
shopt -u patsub_replacement 2>/dev/null || true
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
bundle_name=${root##*/}
sample=${bundle_name%.jbrowse}
template="$root/local.template.jbrowse"
out="$root/$sample.local.jbrowse"
tmp="$out.tmp.$$"
trap 'rm -f "$tmp"' EXIT HUP INT TERM
escaped=$root
escaped=${escaped//\\/\\\\}
escaped=${escaped//\"/\\\"}
escaped=${escaped//$'\t'/\\t}
escaped=${escaped//$'\r'/\\r}
escaped=${escaped//$'\n'/\\n}
for ((code=1; code<32; code++)); do
  printf -v character '%b' "\\$(printf '%03o' "$code")"
  printf -v replacement '\\u%04x' "$code"
  escaped=${escaped//"$character"/$replacement}
done
while IFS= read -r line || [[ -n "$line" ]]; do
  printf '%s\n' "${line//__QUICKALIGN_BUNDLE_ROOT__/$escaped}"
done < "$template" > "$tmp"
mv -f -- "$tmp" "$out"
trap - EXIT HUP INT TERM
printf '%s\n' "$out"
'''


_PS1_RESOLVER = r'''$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$bundleName = Split-Path -Leaf $root
$sample = $bundleName -replace '\.jbrowse$', ''
$template = Join-Path $root 'local.template.jbrowse'
$out = Join-Path $root ($sample + '.local.jbrowse')
$tmp = $out + '.tmp.' + $PID
$rootJson = ConvertTo-Json -Compress $root
$escaped = $rootJson.Substring(1, $rootJson.Length - 2)
$content = [IO.File]::ReadAllText($template).Replace('__QUICKALIGN_BUNDLE_ROOT__', $escaped)
try {
    [IO.File]::WriteAllText($tmp, $content, [Text.UTF8Encoding]::new($false))
    Move-Item -Force -LiteralPath $tmp -Destination $out
} finally {
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
}
Write-Host "Created $out"
Write-Host 'Open this file in JBrowse Desktop 4.3.0.'
'''


_CMD_RESOLVER = r'''@echo off
setlocal
where pwsh >nul 2>nul
if %errorlevel% equ 0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0resolve-local.ps1"
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0resolve-local.ps1"
)
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
2. On Linux/macOS, run bash resolve-local.sh from a terminal (Bash required; no Python needed).
3. On Windows, double-click resolve-local.cmd (prefers PowerShell 7/pwsh, falls back to Windows PowerShell),
   or run resolve-local.ps1 in PowerShell.
4. Open the generated {sample}.local.jbrowse file in JBrowse Desktop 4.3.0.
   If the folder was renamed, the generated filename uses its current name.

The initial view shows the reference, annotation and first BAM at the first contig
(up to 100,000 bases). Select additional BAM tracks through the track selector.
config.json stays portable and unchanged; local.template.jbrowse uses a bundle-root token.

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
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValidationError(f"Symlinks are forbidden in bundles: {relative.as_posix()}")
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValidationError(f"Unsupported filesystem entry in bundle: {relative.as_posix()}")
        if stat.S_ISREG(mode) and relative.as_posix() != "manifest.json" and not relative.name.endswith(".local.jbrowse"):
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
    runner: Any,
    warnings: tuple[InputWarning, ...],
    tool_versions: dict[str, str],
) -> dict[str, Any]:
    root = job.partial
    allocation = next(
        (record for record in reversed(runner.records) if record.get("step") == "thread-allocation"),
        None,
    )
    if allocation is None:
        from .commands import allocate_threads

        aligner_threads, sort_worker_threads = allocate_threads(job.spec.threads)
    else:
        aligner_threads = allocation["aligner_threads"]
        sort_worker_threads = allocation["sort_worker_threads"]
    try:
        from .jobs import resource_metadata

        container_memory = resource_metadata()
    except ImportError:  # Allows the standalone bundle contract tests to run before jobs is integrated.
        container_memory = {
            "configured_memory": os.environ.get("QUICKALIGN_MEMORY", "256g"),
            "effective_memory_bytes": None,
        }
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
        "run": {
            "requested_threads": job.spec.threads,
            "aligner_threads": aligner_threads,
            "sort_worker_threads": sort_worker_threads,
            "sort_main_threads": 1,
            "sort_memory_per_worker": job.spec.sort_memory,
            "container_memory": container_memory,
        },
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
    (root / "local.template.jbrowse").write_bytes(_json_bytes(_localize_config(config)))
    (root / "resolve-local.sh").write_text(_SH_RESOLVER, encoding="utf-8", newline="\n")
    os.chmod(root / "resolve-local.sh", 0o755)
    (root / "resolve-local.ps1").write_text(_PS1_RESOLVER, encoding="utf-8", newline="\n")
    (root / "resolve-local.cmd").write_text(_CMD_RESOLVER, encoding="utf-8", newline="\r\n")
    _write_readmes(root, job.spec.name, warnings_tuple)
    _write_json(
        root / "manifest.json",
        _manifest(job, prepared, tracks_tuple, runner, warnings_tuple, tool_versions),
    )
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
        if "localPath" in value or value.get("locationType") == "LocalPathLocation":
            raise ValidationError("Portable config must not contain local filesystem locations")
        if "uri" in value:
            yield value["uri"]
        for nested in value.values():
            yield from _config_uris(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _config_uris(nested)


def _read_json(path: Path, *, label: str, maximum: int) -> Any:
    try:
        if path.stat().st_size > maximum:
            raise ValidationError(f"{label} exceeds the {maximum}-byte limit")
        with path.open("rb") as stream:
            payload = stream.read(maximum + 1)
        if len(payload) > maximum:
            raise ValidationError(f"{label} exceeds the {maximum}-byte limit")
        return json.loads(payload.decode("utf-8"))
    except ValidationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValidationError(f"{label} is not valid bounded UTF-8 JSON") from exc


def _validate_config_contract(config: dict[str, Any], manifest: dict[str, Any]) -> None:
    assemblies = config.get("assemblies")
    tracks = config.get("tracks")
    search = config.get("aggregateTextSearchAdapters")
    groups = manifest.get("read_groups")
    if not isinstance(assemblies, list) or len(assemblies) != 1 or not isinstance(assemblies[0], dict):
        raise ValidationError("config.json must contain one assembly")
    if not isinstance(tracks, list) or not all(isinstance(item, dict) for item in tracks):
        raise ValidationError("config.json tracks must be a list of objects")
    if not isinstance(search, list) or len(search) != 1 or not isinstance(search[0], dict) or search[0].get(
        "type"
    ) != "TrixTextSearchAdapter":
        raise ValidationError("config.json is missing its Trix text-search adapter")
    if not isinstance(groups, list) or not all(isinstance(item, dict) for item in groups):
        raise ValidationError("Manifest read_groups must be a list of objects")
    reference = manifest.get("reference")
    annotation_manifest = manifest.get("annotation")
    if not isinstance(reference, dict) or reference.get("files") != [
        "reference/assembly.fasta",
        "reference/assembly.fasta.fai",
    ]:
        raise ValidationError("Manifest reference files do not match the bundle contract")
    if not isinstance(annotation_manifest, dict) or annotation_manifest.get("files") != [
        "annotation/features.gff3.gz",
        "annotation/features.gff3.gz.tbi",
    ]:
        raise ValidationError("Manifest annotation files do not match the bundle contract")

    def uri(value: Any) -> Any:
        return value.get("uri") if isinstance(value, dict) else None

    trix = search[0]
    if (
        uri(trix.get("ixFilePath")) != "trix/assembly.ix"
        or uri(trix.get("ixxFilePath")) != "trix/assembly.ixx"
        or uri(trix.get("metaFilePath")) != "trix/assembly_meta.json"
    ):
        raise ValidationError("config.json Trix paths do not match the bundle contract")

    assembly = assemblies[0]
    sequence = assembly.get("sequence")
    adapter = sequence.get("adapter") if isinstance(sequence, dict) else None
    if not isinstance(adapter, dict) or adapter.get("type") != "IndexedFastaAdapter":
        raise ValidationError("config.json is missing the indexed FASTA adapter")
    if uri(adapter.get("fastaLocation")) != "reference/assembly.fasta" or uri(
        adapter.get("faiLocation")
    ) != "reference/assembly.fasta.fai":
        raise ValidationError("config.json reference adapter paths do not match the bundle contract")

    by_id = {item.get("trackId"): item for item in tracks if isinstance(item.get("trackId"), str)}
    if len(by_id) != len(tracks):
        raise ValidationError("config.json track IDs must be present and unique")
    annotation = by_id.get(ANNOTATION_TRACK_ID)
    annotation_adapter = annotation.get("adapter") if isinstance(annotation, dict) else None
    if not isinstance(annotation_adapter, dict) or annotation_adapter.get("type") != "Gff3TabixAdapter":
        raise ValidationError("config.json is missing the tabix annotation track")
    if uri(annotation_adapter.get("gffGzLocation")) != "annotation/features.gff3.gz":
        raise ValidationError("config.json annotation path does not match the bundle contract")
    annotation_index = annotation_adapter.get("index")
    if not isinstance(annotation_index, dict) or uri(annotation_index.get("location")) != (
        "annotation/features.gff3.gz.tbi"
    ):
        raise ValidationError("config.json annotation index path does not match the bundle contract")

    seen_track_ids: set[str] = set()
    for group in groups:
        track_id = group.get("track_id")
        if not isinstance(track_id, str) or not track_id or track_id in seen_track_ids:
            raise ValidationError("Manifest read group has an invalid track_id")
        seen_track_ids.add(track_id)
        expected_files = [
            f"alignments/{track_id}.bam",
            f"alignments/{track_id}.bam.bai",
            f"alignments/{track_id}.flagstat.txt",
        ]
        if group.get("files") != expected_files:
            raise ValidationError(f"Manifest files do not match track {track_id}")
        track = by_id.get(track_id)
        track_adapter = track.get("adapter") if isinstance(track, dict) else None
        if not isinstance(track_adapter, dict) or track_adapter.get("type") != "BamAdapter":
            raise ValidationError(f"config.json is missing BAM track {track_id}")
        if uri(track_adapter.get("bamLocation")) != expected_files[0]:
            raise ValidationError(f"config.json BAM path does not match track {track_id}")
        index = track_adapter.get("index")
        if not isinstance(index, dict) or uri(index.get("location")) != expected_files[1]:
            raise ValidationError(f"config.json BAI path does not match track {track_id}")
    bam_track_ids = {
        track_id
        for track_id, track in by_id.items()
        if isinstance(track.get("adapter"), dict) and track["adapter"].get("type") == "BamAdapter"
    }
    if bam_track_ids != seen_track_ids:
        raise ValidationError("config.json alignment tracks do not match manifest read groups")

    session = config.get("defaultSession")
    views = session.get("views") if isinstance(session, dict) else None
    if not isinstance(views, list) or len(views) != 1 or not isinstance(views[0], dict):
        raise ValidationError("config.json must initialize one defaultSession.views entry")
    view = views[0]
    init = view.get("init")
    contigs = reference.get("contigs")
    if not isinstance(contigs, list) or not contigs or not isinstance(contigs[0], dict):
        raise ValidationError("Manifest reference contigs are missing")
    first = contigs[0]
    length = first.get("length")
    if not isinstance(first.get("name"), str) or type(length) is not int or length < 1:
        raise ValidationError("Manifest reference contig is invalid")
    visible = [sequence.get("trackId"), ANNOTATION_TRACK_ID]
    if groups:
        visible.append(groups[0]["track_id"])
    if (
        view.get("type") != "LinearGenomeView"
        or not isinstance(init, dict)
        or init.get("assembly") != assembly.get("name")
        or init.get("loc") != f"{first['name']}:1..{min(length, 100_000)}"
        or init.get("tracks") != visible
    ):
        raise ValidationError("config.json default view must initialize the bounded locus and visible track IDs")


def validate_bundle(path: Path) -> dict[str, Any]:
    """Check availability using bounded metadata and tracked-file safety/sizes.

    Hashes are creation provenance. Availability intentionally does not read
    payloads or detect same-size corruption, and tolerates untracked additions.
    """
    root = Path(path)
    if not root.is_dir() or root.is_symlink():
        raise ValidationError("Bundle path must be a non-symlink directory")
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise ValidationError(f"Could not resolve bundle path: {exc}") from exc
    manifest_path = _contained_regular_file(root, PurePosixPath("manifest.json"), context="manifest")
    manifest = _read_json(manifest_path, label="manifest.json", maximum=MAX_MANIFEST_BYTES)
    if not isinstance(manifest, dict):
        raise ValidationError("manifest.json must contain an object")
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
        if type(record.get("size")) is not int or record["size"] < 0 or record["size"] != candidate.stat().st_size:
            raise ValidationError(f"Size mismatch for {name}")
        if not isinstance(record.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
            raise ValidationError(f"Invalid SHA-256 provenance for {name}")

    required = set(REQUIRED_FILES) | {"trix/assembly.ix", "trix/assembly.ixx", "trix/assembly_meta.json"}
    if not required.issubset(seen):
        raise ValidationError(f"Required assets missing from manifest: {sorted(required - seen)}")
    config = _read_json(root / "config.json", label="config.json", maximum=MAX_CONFIG_BYTES)
    if not isinstance(config, dict):
        raise ValidationError("config.json must contain an object")
    _validate_config_contract(config, manifest)
    for group in manifest["read_groups"]:
        if not set(group["files"]).issubset(seen):
            raise ValidationError(f"Required track assets missing from manifest: {group['track_id']}")
    uris = list(_config_uris(config))
    if not uris:
        raise ValidationError("config.json has no portable asset URIs")
    for uri in uris:
        relative = _safe_relative(uri, context="config.json")
        if relative.as_posix() not in seen:
            raise ValidationError(f"Config asset missing from manifest: {relative.as_posix()}")
    template = _read_json(
        root / "local.template.jbrowse", label="local.template.jbrowse", maximum=MAX_CONFIG_BYTES
    )
    if template != _localize_config(config):
        raise ValidationError("Local template does not match localized portable config")
    return manifest
