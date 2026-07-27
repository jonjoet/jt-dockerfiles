#!/usr/bin/env python3
"""
Convert completed Plasmidsaurus order folders from the legacy ZIP layout to the
layout produced by plasmidsaurus_autofetch.py version 2.

Run this file beside plasmidsaurus_autofetch.py. It needs no API credentials and
does not download anything. Legacy ZIPs are preserved unless --delete-zips is
explicitly supplied.
"""

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import plasmidsaurus_autofetch as autofetch


log = logging.getLogger("plasmidsaurus_migrate")


class MigrationError(Exception):
    pass


def _load_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MigrationError(
            "no .complete marker; legacy download is incomplete"
        ) from exc
    except (OSError, ValueError) as exc:
        raise MigrationError(f"cannot read .complete marker: {exc}") from exc
    if not isinstance(value, dict):
        raise MigrationError(".complete marker is not a JSON object")
    return value


def _legacy_archives(item_dir: Path) -> dict:
    code = item_dir.name
    return {
        kind: item_dir / f"{code}_{kind}.zip"
        for kind in autofetch.DATA_TYPES
        if (item_dir / f"{code}_{kind}.zip").is_file()
    }


def _delete_archives(archives: dict) -> None:
    for archive in archives.values():
        archive.unlink(missing_ok=True)


def migrate_order(
    item_dir: Path, delete_zips: bool = False, dry_run: bool = False
) -> str:
    """Migrate one order folder; return a short status for the summary."""
    marker = item_dir / autofetch.COMPLETE_MARKER
    manifest = _load_manifest(marker)
    archives = _legacy_archives(item_dir)
    if not archives:
        return "no-legacy-zips"

    if manifest.get("layout_version") == autofetch.LAYOUT_VERSION:
        missing = [kind for kind in archives if not (item_dir / kind).is_dir()]
        if missing:
            raise MigrationError(
                "version-2 marker exists but extracted folders are missing: "
                + ", ".join(missing)
            )
        if dry_run:
            action = "delete" if delete_zips else "preserve"
            log.info(
                "[dry-run] %s already migrated; would %s legacy ZIPs",
                item_dir.name,
                action,
            )
            return "would-clean" if delete_zips else "already-migrated"
        if delete_zips:
            try:
                _delete_archives(archives)
            except OSError as exc:
                raise MigrationError(f"cannot delete a legacy ZIP: {exc}") from exc
            return "archives-deleted"
        return "already-migrated"

    if dry_run:
        log.info(
            "[dry-run] would migrate %s (%s)",
            item_dir.name,
            ", ".join(path.name for path in archives.values()),
        )
        return "would-migrate"

    extracted = {}
    for kind, archive in archives.items():
        staging = item_dir / f".{kind}.migrating"
        destination = item_dir / kind
        try:
            archive_bytes = archive.stat().st_size
            # Until the version-2 marker is committed, an existing destination
            # is only residue from an interrupted migration.
            autofetch._remove_path(destination)
            stats = autofetch.extract_zip(archive, staging)
            os.replace(staging, destination)
        except (autofetch.RetryableError, OSError) as exc:
            try:
                autofetch._remove_path(staging)
            except OSError:
                pass
            raise MigrationError(f"{kind}: {exc}") from exc
        extracted[kind] = {
            "directory": kind,
            "files": stats["files"],
            "bytes": stats["bytes"],
            "archive_bytes": archive_bytes,
        }

    updated = dict(manifest)
    updated.update(
        {
            "layout_version": autofetch.LAYOUT_VERSION,
            "item_code": manifest.get("item_code", item_dir.name),
            "migrated_at": datetime.now(timezone.utc).isoformat(),
            "files": extracted,
        }
    )
    try:
        autofetch.write_manifest_atomic(marker, updated)
    except OSError as exc:
        raise MigrationError(f"cannot update .complete marker: {exc}") from exc

    if delete_zips:
        try:
            _delete_archives(archives)
        except OSError as exc:
            raise MigrationError(
                f"migration completed but a legacy ZIP could not be deleted: {exc}"
            ) from exc
    return "migrated-and-deleted" if delete_zips else "migrated"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert completed Plasmidsaurus ZIP folders to layout version 2."
    )
    parser.add_argument(
        "--data-dir",
        default=os.getenv("PLASMIDSAURUS_DATA_DIR"),
        help="Plasmidsaurus data directory (or set PLASMIDSAURUS_DATA_DIR).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List legacy folders without changing them.",
    )
    parser.add_argument(
        "--delete-zips",
        action="store_true",
        help="Delete each legacy ZIP only after extraction and marker update succeed.",
    )
    args = parser.parse_args()

    if not args.data_dir:
        parser.error("--data-dir or PLASMIDSAURUS_DATA_DIR is required")
    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        parser.error(f"data directory does not exist: {data_dir}")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )

    lock_dir = None
    if not args.dry_run:
        try:
            lock_dir = autofetch.acquire_lock(data_dir)
        except autofetch.LockBusy:
            log.error(
                "The downloader or another migration is running. Stop the timer "
                "and wait for the current service run to finish."
            )
            return 1

    summary = {}
    failures = 0
    try:
        for item_dir in sorted(data_dir.iterdir(), key=lambda path: path.name):
            if (
                not item_dir.is_dir()
                or item_dir.is_symlink()
                or not autofetch._usable_code(item_dir.name)
            ):
                continue
            if not _legacy_archives(item_dir):
                continue
            try:
                status = migrate_order(
                    item_dir,
                    delete_zips=args.delete_zips,
                    dry_run=args.dry_run,
                )
                log.info("%s: %s", item_dir.name, status)
            except MigrationError as exc:
                status = "error"
                failures += 1
                log.error("%s: %s", item_dir.name, exc)
            summary[status] = summary.get(status, 0) + 1
    finally:
        if lock_dir is not None:
            shutil.rmtree(lock_dir, ignore_errors=True)

    if summary:
        log.info(
            "Migration summary: %s",
            ", ".join(f"{key}={value}" for key, value in sorted(summary.items())),
        )
    else:
        log.info("No legacy ZIP folders found.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
