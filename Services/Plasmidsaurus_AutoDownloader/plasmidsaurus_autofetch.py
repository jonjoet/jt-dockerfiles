#!/usr/bin/env python3
"""
plasmidsaurus_autofetch.py
==========================

WHAT THIS IS
    A small, self-contained script that downloads finished Plasmidsaurus
    sequencing orders and drops them onto a mounted SMB/CIFS file share. It's
    upstream ingestion plumbing that just lands raw deliverables on disk so they
    can be picked up later.

    For each completed order it creates a folder named after the order's item
    code and saves, inside that folder:

        <item_code>/results/      fasta / gbk / reporting files
        <item_code>/reads/        raw reads (the *.fastq.gz members stay gzipped)
        <item_code>/.complete     marker + manifest, written LAST

    Each deliverable zip is buffered on fast local scratch. New/changed members
    are extracted to hidden staging folders on the share and published with
    same-share renames. The zip never touches the share; unchanged files are
    not rewritten. pod5 (raw signal) is intentionally not fetched.

WHY IT EXISTS / WHO SET IT UP
    Stopgap set up by <YOUR NAME / TEAM> on <DATE SET UP> so results land
    automatically instead of being fetched by hand. Questions: <YOUR CONTACT>.
    If you found this and have no idea what it is: it is safe to turn off (see
    "HOW TO DISABLE"). It touches nothing except the destination folder.

HOW IT RUNS
    Invoked on a schedule by a systemd timer (plasmidsaurus-autofetch.timer),
    as a dedicated unprivileged user. See the setup guide for the install.
    Each run downloads archives for at most MAX_DOWNLOADS_PER_RUN orders.
    Unchanged checks do not use download slots; deferred downloads go first
    next run. Recent orders are watched for late deliverables.
    It can also be run by hand for testing -- see the bottom of this header.

HOW TO DISABLE
        sudo systemctl disable --now plasmidsaurus-autofetch.timer
    That stops all scheduled runs. There are no other daemons or packages.
    Removing this file and the two unit files removes it entirely. Data already
    on the share is untouched.

CONFIG (environment variables; supplied by the systemd unit's EnvironmentFile)
    PLASMIDSAURUS_CLIENT_ID       (required)  OAuth client id
    PLASMIDSAURUS_CLIENT_SECRET   (required)  OAuth client secret
    PLASMIDSAURUS_DATA_DIR        (required unless you edit DATA_DIR below)
                                  destination folder on the mounted share
    PLASMIDSAURUS_SCRATCH_DIR     (optional) local scratch for one zip at a time;
                                  defaults to the system temporary directory
    PLASMIDSAURUS_MIN_FREE        (optional) minimum scratch bytes required when
                                  a download has no Content-Length (default:
                                  536870912, or 512 MiB)
    PLASMIDSAURUS_SINCE           (optional)  YYYY-MM-DD. Only fetch orders
                                  completed on/after this date. Leave unset to
                                  backfill the whole order history (a few/run).
    PLASMIDSAURUS_RECHECK_DAYS     (optional) days after first successful download
                                  to watch for added/changed files (default 45;
                                  0 disables new rechecks). SINCE applies only
                                  to new orders, not this local watch list.

DEPENDENCIES
    Python 3.8+ standard library only. No pip packages, no virtualenv.

SAFE TO RE-RUN
    `.complete` describes the latest fully downloaded snapshot, not a promise
    that Plasmidsaurus will never add files. It records member paths, sizes and
    CRC32s, HTTP validators, the original fetched_at, and last_checked_at.
    Refresh failures retain a .refresh.json journal for retry (even after the
    watch window). The old .complete stays valid until publication begins;
    it is removed during publication and rewritten last. Run by hand:
        python3 plasmidsaurus_autofetch.py            # one normal pass
        python3 plasmidsaurus_autofetch.py --dry-run  # list what it WOULD fetch

Built from the request patterns in https://github.com/plasmidsaurus/api_docs
(OAuth2 client-credentials -> /api/items -> /api/item/<code>/{results,reads}).
"""

import argparse
import base64
import http.client
import json
import logging
import math
import os
import shutil
import socket
import stat
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from pathlib import PurePosixPath


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

# Authoritative API host. (The Plasmidsaurus examples repo is inconsistent about
# this -- the working helpers use app.plasmidsaurus.com, so we do too.)
API_URL = "https://app.plasmidsaurus.com"

# Destination on the mounted share. Either edit this, or set PLASMIDSAURUS_DATA_DIR
# (the systemd unit does the latter). The script refuses to run while this is
# still the placeholder, so it can't silently write to the wrong place.
DATA_DIR = os.getenv("PLASMIDSAURUS_DATA_DIR", "/CHANGE/ME/plasmidsaurus_data")

# Local scratch used to buffer one zip at a time. Under the documented systemd
# service, the default respects PrivateTmp=yes.
SCRATCH_DIR = os.getenv("PLASMIDSAURUS_SCRATCH_DIR", tempfile.gettempdir())

# Used only when a server omits Content-Length. Kept as a string here so a bad
# environment value can produce a friendly configuration error in main().
_min_free_env = os.getenv("PLASMIDSAURUS_MIN_FREE", str(512 * 1024 * 1024))

# Which deliverables to fetch. pod5 is deliberately excluded.
DATA_TYPES = ("results", "reads")

# Cap orders whose archive bodies are downloaded, not metadata-only checks.
# Both deliverables share one slot; interrupted body transfers still count.
MAX_DOWNLOADS_PER_RUN = 5

# Only consider orders completed on/after this date, if set (env override).
_since_env = os.getenv("PLASMIDSAURUS_SINCE")
_recheck_days_env = os.getenv("PLASMIDSAURUS_RECHECK_DAYS", "45")

# Per-socket-operation timeout (seconds) and streaming chunk size.
HTTP_TIMEOUT = 120
CHUNK_SIZE = 1 << 20  # 1 MiB

USER_AGENT = "plasmidsaurus-autofetch/2.1 (stdlib)"

# A run older than this is assumed crashed and its lock is reclaimed.
STALE_LOCK_AFTER = 6 * 3600

COMPLETE_MARKER = ".complete"
REFRESH_MARKER = ".refresh.json"
QUEUE_FILE = "_autofetch.queue.json"
LAYOUT_VERSION = 2
MAX_ZIP_MEMBERS = 100_000

# Network errors we treat as transient (HTTPError is a subclass of URLError).
NET_ERRORS = (urllib.error.URLError, TimeoutError, http.client.HTTPException)

log = logging.getLogger("plasmidsaurus_autofetch")


# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------

def setup_logging(data_dir: Path) -> None:
    """Log to the share (next to the data, easy to find) and to stderr/journal."""
    if log.handlers:  # already configured (e.g. called twice in one process)
        return
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    log.addHandler(stream)

    try:
        fileh = RotatingFileHandler(
            data_dir / "_autofetch.log", maxBytes=1 << 20, backupCount=3
        )
        fileh.setFormatter(fmt)
        log.addHandler(fileh)
    except OSError as exc:
        log.warning("Could not open log file on the share (%s); stderr only.", exc)


# ----------------------------------------------------------------------------
# Locking (atomic mkdir -- reliable over SMB/CIFS, unlike flock)
# ----------------------------------------------------------------------------

class LockBusy(Exception):
    pass


def acquire_lock(data_dir: Path) -> Path:
    lock_dir = data_dir / "_autofetch.lock"
    info_path = lock_dir / "info.json"
    try:
        lock_dir.mkdir()
    except FileExistsError:
        if _lock_is_stale(info_path):
            log.warning("Reclaiming stale lock at %s", lock_dir)
            shutil.rmtree(lock_dir, ignore_errors=True)
            try:
                lock_dir.mkdir()
            except FileExistsError:
                # Another run reclaimed it first; treat as busy and bail cleanly.
                raise LockBusy()
        else:
            raise LockBusy()
    info_path.write_text(
        json.dumps(
            {"pid": os.getpid(), "host": socket.gethostname(), "started": time.time()}
        )
    )
    return lock_dir


def _lock_is_stale(info_path: Path) -> bool:
    try:
        info = json.loads(info_path.read_text())
    except (OSError, ValueError):
        # No/garbled metadata: fall back to age of the lock directory.
        try:
            return (time.time() - info_path.parent.stat().st_mtime) > STALE_LOCK_AFTER
        except OSError:
            return False

    if (time.time() - info.get("started", 0)) > STALE_LOCK_AFTER:
        return True
    # Same host and the recorded process is gone -> definitely stale.
    if info.get("host") == socket.gethostname():
        pid = info.get("pid")
        if isinstance(pid, int):
            try:
                os.kill(pid, 0)
                return False  # still running
            except ProcessLookupError:
                return True
            except PermissionError:
                return False  # exists but not ours
    return False


# ----------------------------------------------------------------------------
# HTTP helpers (stdlib urllib)
# ----------------------------------------------------------------------------

class RetryableError(Exception):
    """A transient API error -- do not mark the order complete; retry next run."""


class DownloadDeferred(Exception):
    """The run's download budget is full; leave this order for a later run."""


class DownloadBudget:
    def __init__(self, limit: int):
        self.limit = limit
        self.orders = set()

    def claim(self, code: str) -> None:
        if code not in self.orders:
            if len(self.orders) >= self.limit:
                raise DownloadDeferred()
            self.orders.add(code)


def _read_json(req: urllib.request.Request):
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_access_token(client_id: str, client_secret: str) -> str:
    body = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "scope": "item:read"}
    ).encode("utf-8")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        f"{API_URL}/oauth/token",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    return _read_json(req)["access_token"]


def _api_get(token: str, path: str):
    req = urllib.request.Request(
        f"{API_URL}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    return _read_json(req)


def get_items(token: str) -> list:
    """Own items + items shared with you. Most-recent-first per the API."""
    return _api_get(token, "/api/items") + _api_get(token, "/api/items?shared=true")


def fetch_link(token: str, code: str, kind: str):
    """
    Return the presigned download URL for one deliverable, or None if the order
    simply has no file of that kind (e.g. custom projects have no 'results').
    Only 404/410 mean absent; authentication/rate-limit/server errors retry.
    """
    try:
        payload = _api_get(token, f"/api/item/{code}/{kind}")
    except urllib.error.HTTPError as exc:
        if exc.code not in (404, 410):
            raise RetryableError(f"{kind} for {code}: HTTP {exc.code}")
        log.info("  no %s available for %s (HTTP %s)", kind, code, exc.code)
        return None
    return payload.get("link")


def ensure_free_space(path: Path, needed_bytes: int, margin: float = 1.05) -> None:
    """Raise RetryableError unless `path` has enough free bytes plus margin."""
    required = math.ceil(needed_bytes * margin)
    try:
        free = shutil.disk_usage(path).free
    except OSError as exc:
        raise RetryableError(f"cannot check free space at {path}: {exc}") from exc
    if free < required:
        raise RetryableError(
            f"not enough free space at {path}: need {required} bytes, have {free}"
        )


def download_to_scratch(
    url: str, scratch_path: Path, min_free_bytes: int, previous=None,
    before_download=None,
):
    """
    Conditional GET to scratch. Return byte count and validators, or None for
    HTTP 304. Invoke before_download only before reading an archive body; it
    may raise DownloadDeferred to close the response without downloading it.
    Presigned URLs are neither stored nor compared: they expire.
    """
    # Defence-in-depth: never let a link from the API send urllib to file://,
    # ftp://, data:, etc. (Don't log the URL -- presigned links carry secrets.)
    scheme = urllib.parse.urlparse(url).scheme
    if scheme != "https":
        raise RetryableError(f"refusing download link with non-https scheme {scheme!r}")
    part = scratch_path.with_suffix(scratch_path.suffix + ".part")
    part.unlink(missing_ok=True)
    written = 0
    headers = {"User-Agent": USER_AGENT}
    previous = previous or {}
    if previous.get("etag"):
        headers["If-None-Match"] = previous["etag"]
    elif previous.get("last_modified"):
        headers["If-Modified-Since"] = previous["last_modified"]
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            metadata = {
                "etag": resp.headers.get("ETag"),
                "last_modified": resp.headers.get("Last-Modified"),
            }
            raw_length = resp.headers.get("Content-Length")
            try:
                expected = int(raw_length) if raw_length else 0
            except (TypeError, ValueError) as exc:
                raise RetryableError(
                    f"invalid Content-Length for {scratch_path.name}: {raw_length!r}"
                ) from exc
            if expected < 0:
                raise RetryableError(
                    f"invalid Content-Length for {scratch_path.name}: {expected}"
                )
            ensure_free_space(
                scratch_path.parent,
                expected if expected else min_free_bytes,
                margin=1.05 if expected else 1.0,
            )
            if before_download is not None:
                before_download()
            with open(part, "wb") as fh:
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    written += fh.write(chunk)
        if expected and written != expected:
            raise RetryableError(
                f"{scratch_path.name}: incomplete download ({written}/{expected} bytes)"
            )
        os.replace(part, scratch_path)
        return {"archive_bytes": written, **metadata}
    except urllib.error.HTTPError as exc:
        if exc.code == 304 and len(headers) > 1:
            return None
        # HTTPError.__str__ omits the signed URL, unlike some transport errors.
        raise RetryableError(f"download HTTP {exc.code}") from exc
    except NET_ERRORS:
        raise
    except OSError as exc:
        raise RetryableError(
            f"cannot write scratch download {scratch_path.name}: {exc}"
        ) from exc
    finally:
        part.unlink(missing_ok=True)


def _remove_path(path: Path) -> None:
    """Remove a file, symlink, or directory if present."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _validated_zip_members(zf: zipfile.ZipFile):
    """Return safe archive members and reject ambiguous/unsafe layouts."""
    members = zf.infolist()
    if len(members) > MAX_ZIP_MEMBERS:
        raise RetryableError(
            f"archive has {len(members)} entries; limit is {MAX_ZIP_MEMBERS}"
        )

    validated = []
    seen = set()
    for info in members:
        name = info.filename
        if not name or "\x00" in name or "\\" in name:
            raise RetryableError(f"archive contains unsafe member name {name!r}")
        pure = PurePosixPath(name)
        parts = pure.parts
        if (
            pure.is_absolute()
            or not parts
            or any(part in ("", ".", "..") for part in parts)
            or (len(parts[0]) >= 2 and parts[0][1] == ":")
        ):
            raise RetryableError(f"archive contains unsafe member path {name!r}")
        if info.flag_bits & 0x1:
            raise RetryableError(f"archive member is encrypted: {name!r}")

        unix_mode = info.external_attr >> 16
        file_type = stat.S_IFMT(unix_mode)
        if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise RetryableError(f"archive member has unsupported type: {name!r}")

        relative = Path(*parts)
        collision_key = unicodedata.normalize("NFC", relative.as_posix()).casefold()
        if collision_key in seen:
            raise RetryableError(
                f"archive has duplicate/colliding member path {name!r}"
            )
        seen.add(collision_key)
        validated.append((info, relative))
    return validated


def extract_zip(scratch_zip: Path, staging_dir: Path, previous=None, destination=None) -> dict:
    """
    Validate and extract one local zip directly into a staging directory on the
    share, skipping unchanged members. Reading each extracted member to EOF
    also verifies its ZIP CRC; CRC32 is change detection, not a security hash.
    """
    _remove_path(staging_dir)
    try:
        with zipfile.ZipFile(scratch_zip) as zf:
            members = _validated_zip_members(zf)
            file_members = [
                (info, relative)
                for info, relative in members
                if not info.is_dir()
            ]
            inventory = {
                relative.as_posix(): {"bytes": info.file_size, "crc32": info.CRC}
                for info, relative in file_members
            }
            previous = previous or {}
            changed = [
                (info, relative) for info, relative in file_members
                if previous.get(relative.as_posix()) != inventory[relative.as_posix()]
                or destination is None
                or not (destination / relative).is_file()
                or (destination / relative).stat().st_size != info.file_size
            ]
            total_bytes = sum(info.file_size for info, _ in file_members)
            ensure_free_space(staging_dir.parent, sum(info.file_size for info, _ in changed))
            staging_dir.mkdir(parents=True)

            for info, relative in changed:
                output = staging_dir / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as source, open(output, "xb") as target:
                    shutil.copyfileobj(source, target, length=CHUNK_SIZE)
        return {"files": len(file_members), "bytes": total_bytes,
                "members": inventory, "written": len(changed)}
    except RetryableError:
        try:
            _remove_path(staging_dir)
        except OSError:
            pass
        raise
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile) as exc:
        try:
            _remove_path(staging_dir)
        except OSError:
            pass
        raise RetryableError(f"cannot extract {scratch_zip.name}: {exc}") from exc


def write_manifest_atomic(path: Path, manifest: dict) -> None:
    """Write a completion manifest atomically in the destination directory."""
    part = path.with_name(path.name + ".part")
    try:
        with open(part, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)


# ----------------------------------------------------------------------------
# Per-order processing
# ----------------------------------------------------------------------------

def load_manifest(item_dir: Path):
    """Use the pre-refresh snapshot after an interruption, even without .complete."""
    path = item_dir / REFRESH_MARKER
    if not path.exists():
        path = item_dir / COMPLETE_MARKER
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise RetryableError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("files"), dict):
        raise RetryableError(f"invalid manifest at {path}")
    return value


def within_recheck_window(manifest: dict, days: int, now=None) -> bool:
    # Never slide this window forward when late files arrive.
    fetched = _parse_done(manifest.get("fetched_at"))
    if fetched is None:
        log.warning("Cannot recheck %s: missing/invalid fetched_at in manifest.",
                    manifest.get("item_code", "order"))
        return False
    return days > 0 and (now or datetime.now(timezone.utc)) - fetched <= timedelta(days=days)


def inventory_directory(directory: Path) -> dict:
    """One-time inventory for older layout-2 manifests without member records."""
    inventory = {}
    if directory.is_symlink():
        raise RetryableError(f"refusing symlink directory {directory}")
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise RetryableError(f"refusing symlink {path}")
        if path.is_file():
            crc, size = 0, 0
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
                    crc = zlib.crc32(chunk, crc)
                    size += len(chunk)
            inventory[path.relative_to(directory).as_posix()] = {"bytes": size, "crc32": crc}
    return inventory


def validate_merge(destination: Path, inventory: dict) -> None:
    """Reject symlinks, file/directory conflicts and case collisions before writes."""
    paths = {}
    for name in inventory:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise RetryableError(f"unsafe inventory path {name!r}")
        for part in (relative, *relative.parents):
            key = unicodedata.normalize("NFC", part.as_posix()).casefold()
            if key in paths and paths[key] != part:
                raise RetryableError(f"colliding file paths at {name!r}")
            paths[key] = part
        if any(parent.as_posix() in inventory for parent in relative.parents):
            raise RetryableError(f"file/directory conflict at {name!r}")
        target = destination / relative
        for path in (target, *target.parents):
            if path.is_symlink():
                raise RetryableError(f"refusing symlink {path}")
            if path == destination.parent:
                break
        if target.exists() and not target.is_file():
            raise RetryableError(f"not a regular file: {target}")
        if any(path.exists() and not path.is_dir()
               for path in (destination, *(destination / p for p in relative.parents))):
            raise RetryableError(f"not a directory above {target}")


def process_item(
    item: dict,
    token: str,
    data_dir: Path,
    scratch_dir: Path,
    min_free_bytes: int,
    dry_run: bool,
    recheck_days: int = 45,
    budget=None,
) -> str:
    """Fetch new or changed deliverables; publish the manifest after all files."""
    code = item["code"]
    item_dir = data_dir / code
    previous = load_manifest(item_dir)
    retry = (item_dir / REFRESH_MARKER).exists()
    if previous is not None:
        if previous.get("layout_version") != LAYOUT_VERSION:
            log.warning("%s needs migrate_legacy_zips.py before rechecking.", code)
            return "skip-legacy"
        if not retry and not within_recheck_window(previous, recheck_days):
            return "skip-done"

    if dry_run:
        action = "recheck" if previous is not None else "fetch"
        log.info("[dry-run] would %s %s (%s)", action, code, item.get("product_name", "?"))
        return "would-" + action

    item_dir.mkdir(parents=True, exist_ok=True)
    def begin_download():
        if budget is not None:
            budget.claim(code)
        # A deferred or unchanged check must not create a retry journal: that
        # would disable its validators next time and force needless downloads.
        if previous is not None and not (item_dir / REFRESH_MARKER).exists():
            write_manifest_atomic(item_dir / REFRESH_MARKER, previous)

    fetched = dict(previous["files"]) if previous is not None else {}
    staged = []
    changed = False
    try:
        for kind in DATA_TYPES:
            staging = item_dir / f".{kind}.partial"
            _remove_path(staging)
            link = fetch_link(token, code, kind)
            if not link:
                if kind in fetched:
                    raise RetryableError(f"previously downloaded {kind} is unavailable")
                continue
            old = fetched.get(kind, {})
            destination = item_dir / kind
            members = old.get("members")
            if members is not None:
                validate_merge(destination, members)
            # Missing local files must be recoverable even if remote bytes did
            # not change. Old manifests need a first unconditional download.
            intact = members is not None and all(
                (destination / name).is_file()
                and (destination / name).stat().st_size == info["bytes"]
                for name, info in members.items()
            )
            with tempfile.TemporaryDirectory(
                prefix=f"plasmidsaurus-{code}-{kind}-", dir=scratch_dir
            ) as work:
                scratch_zip = Path(work) / f"{code}_{kind}.zip"
                log.info("  checking %s for %s ...", kind, code)
                remote = download_to_scratch(
                    link, scratch_zip, min_free_bytes,
                    previous=old.get("remote") if intact and not retry else None,
                    before_download=begin_download,
                )
                if remote is None:
                    log.info("  %s unchanged (HTTP 304)", kind)
                    continue
                # Inventory old installations only once a download is admitted,
                # not for every deferred order on a slow share.
                if members is None:
                    members = inventory_directory(destination)
                validate_merge(destination, members)
                stats = extract_zip(scratch_zip, staging, {} if retry else members, destination)
                # Remote omission is not an instruction to delete earlier data.
                merged = {**members, **stats["members"]}
                validate_merge(destination, merged)
                staged.append((staging, destination))
                fetched[kind] = {
                    "directory": kind,
                    "files": len(merged),
                    "bytes": sum(info["bytes"] for info in merged.values()),
                    "archive_bytes": remote["archive_bytes"],
                    "remote": remote,
                    "members": merged,
                }
                changed = changed or stats["written"] > 0 or kind not in (previous or {}).get("files", {})
                log.info("  staged %d new/changed %s files", stats["written"], kind)

        # All downloads/extractions passed. During publication the order is
        # marker-less, so consumers cannot mistake a partial refresh for success.
        if staged:
            (item_dir / COMPLETE_MARKER).unlink(missing_ok=True)
        for staging, destination in staged:
            destination.mkdir(exist_ok=True)
            for source in sorted(staging.rglob("*")):
                if source.is_file():
                    target = destination / source.relative_to(staging)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(source, target)
        now = datetime.now(timezone.utc).isoformat()
        manifest = dict(previous or {})
        manifest.update({
            "layout_version": LAYOUT_VERSION,
            "item_code": code,
            "fetched_at": previous["fetched_at"] if previous is not None else now,
            "last_checked_at": now,
            "updated_at": now if changed else manifest.get("updated_at", now),
            "order": {k: item.get(k) for k in ("product_name", "done_date", "quantity", "status")},
            "files": fetched,
        })
        write_manifest_atomic(item_dir / COMPLETE_MARKER, manifest)
        (item_dir / REFRESH_MARKER).unlink(missing_ok=True)
        if previous is not None:
            return "updated" if changed else "unchanged"
        return "done" if fetched else "done-empty"
    except DownloadDeferred:
        log.info("  download budget full; deferring %s", code)
        return "deferred"
    except (RetryableError, OSError, *NET_ERRORS) as exc:
        if previous is not None and not (item_dir / REFRESH_MARKER).exists():
            write_manifest_atomic(item_dir / REFRESH_MARKER, previous)
        log.warning("  problem fetching %s: %s", code, exc)
        return "partial-error"
    finally:
        for kind in DATA_TYPES:
            try:
                _remove_path(item_dir / f".{kind}.partial")
            except OSError:
                pass


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def parse_since():
    if not _since_env:
        return None
    try:
        return datetime.strptime(_since_env, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        log.error("PLASMIDSAURUS_SINCE=%r is not YYYY-MM-DD; ignoring.", _since_env)
        return None


def _parse_done(done: str):
    """API done_date -> aware UTC datetime, or None if unparseable.

    Handles a trailing 'Z' (Python <3.11 fromisoformat can't) and assumes UTC
    for naive timestamps, so comparisons against `since` never raise TypeError.
    """
    if not isinstance(done, str):
        return None
    s = done.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _usable_code(code) -> bool:
    """True if `code` is safe as a single folder / filename component.

    Rejects missing/empty values and anything that could escape DATA_DIR
    (path separators, '.'/'..', NULs). Codes come from the API -- including
    items other people shared with you -- so we don't assume they're well-formed.
    """
    return (
        isinstance(code, str)
        and code not in ("", ".", "..")
        and not any(c in code for c in ("/", "\\", "\x00"))
    )


def select_pending(items: list, since):
    pending = []
    seen = set()
    for item in items:
        if item.get("status") != "complete":
            continue
        if not _usable_code(item.get("code")):
            log.warning("Skipping item with missing/unsafe code: %r", item.get("code"))
            continue
        done = item.get("done_date")
        if since and done:
            dt = _parse_done(done)
            if dt is not None and dt < since:
                continue
        if item["code"] not in seen:
            pending.append(item)
            seen.add(item["code"])
    return pending


def select_work(items: list, since, data_dir: Path, recheck_days: int):
    """New orders obey SINCE; local recent downloads are watched independently."""
    pending = [
        item for item in select_pending(items, since)
        if not any((data_dir / item["code"] / name).exists()
                   for name in (COMPLETE_MARKER, REFRESH_MARKER))
    ]
    by_code = {i["code"]: i for i in items if _usable_code(i.get("code"))}
    rechecks = []
    for folder in sorted(data_dir.iterdir()):
        if folder.is_symlink() or not folder.is_dir():
            continue
        try:
            manifest = load_manifest(folder)
            if manifest is None:
                continue
            if manifest.get("layout_version") != LAYOUT_VERSION:
                log.warning("%s needs migrate_legacy_zips.py before rechecking.", folder.name)
                continue
            if (folder / REFRESH_MARKER).exists() or within_recheck_window(manifest, recheck_days):
                rechecks.append(by_code.get(folder.name, {
                    **manifest.get("order", {}), "code": folder.name,
                }))
        except RetryableError as exc:
            log.warning("Skipping %s: %s", folder.name, exc)
    return pending, rechecks


def work_queue(pending: list, rechecks: list, data_dir: Path) -> list:
    """Keep eligible queued orders in order, then append newly eligible ones.

    Initially interleave new downloads and rechecks. Persisted order wins on
    subsequent runs so fresh arrivals cannot jump ahead of waiting work.
    """
    try:
        saved = json.loads((data_dir / QUEUE_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        saved = {"orders": []}
    except (OSError, ValueError) as exc:
        raise RetryableError(f"cannot read {QUEUE_FILE}: {exc}") from exc
    if (not isinstance(saved, dict) or not isinstance(saved.get("orders"), list)
            or any(not _usable_code(code) for code in saved["orders"])):
        raise RetryableError(f"invalid scheduling queue in {QUEUE_FILE}")
    arrivals = []
    for index in range(max(len(pending), len(rechecks))):
        for group in (pending, rechecks):
            if index < len(group):
                arrivals.append(group[index]["code"])
    eligible = set(arrivals)
    seen = set()
    queue = []
    for code in saved["orders"] + arrivals:
        if code in eligible and code not in seen:
            queue.append(code)
            seen.add(code)
    return queue


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-fetch Plasmidsaurus results to the share.")
    parser.add_argument("--once", action="store_true", help="Run one pass (default).")
    parser.add_argument("--dry-run", action="store_true", help="List what would be fetched; download nothing.")
    parser.add_argument("--data-dir", help="Override the destination folder for this run.")
    parser.add_argument(
        "--scratch-dir",
        help="Override the local scratch directory for this run.",
    )
    parser.add_argument(
        "--recheck-days", default=_recheck_days_env,
        help="Watch orders this many days after first download (default: 45; 0 disables).",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir or DATA_DIR)
    if str(data_dir) == "/CHANGE/ME/plasmidsaurus_data":
        print(
            "Refusing to run: destination not configured. Set PLASMIDSAURUS_DATA_DIR "
            "or edit DATA_DIR at the top of this script.",
            file=sys.stderr,
        )
        return 2
    data_dir.mkdir(parents=True, exist_ok=True)

    setup_logging(data_dir)

    try:
        recheck_days = int(args.recheck_days)
        if not 0 <= recheck_days <= 999999999:
            raise ValueError
    except (ValueError, OverflowError):
        log.error("PLASMIDSAURUS_RECHECK_DAYS / --recheck-days must be a non-negative integer (at most 999999999).")
        return 2

    scratch_dir = Path(args.scratch_dir or SCRATCH_DIR)
    try:
        min_free_bytes = int(_min_free_env)
        if min_free_bytes < 0:
            raise ValueError
    except ValueError:
        log.error(
            "PLASMIDSAURUS_MIN_FREE=%r is not a non-negative byte count.",
            _min_free_env,
        )
        return 2
    if not args.dry_run:
        try:
            scratch_dir.mkdir(parents=True, exist_ok=True)
            if not scratch_dir.is_dir():
                raise OSError("path is not a directory")
        except OSError as exc:
            log.error("Cannot use scratch directory %s: %s", scratch_dir, exc)
            return 2

    client_id = os.getenv("PLASMIDSAURUS_CLIENT_ID")
    client_secret = os.getenv("PLASMIDSAURUS_CLIENT_SECRET")
    if not client_id or not client_secret:
        log.error("PLASMIDSAURUS_CLIENT_ID / PLASMIDSAURUS_CLIENT_SECRET not set.")
        return 2

    try:
        lock_dir = acquire_lock(data_dir)
    except LockBusy:
        log.info("Another run is in progress; exiting.")
        return 0

    try:
        since = parse_since()
        log.info("Run start -> %s%s", data_dir, f" (since {since.date()})" if since else "")

        token = get_access_token(client_id, client_secret)
        items = get_items(token)
        pending, rechecks = select_work(items, since, data_dir, recheck_days)
        queue = work_queue(pending, rechecks, data_dir)
        by_code = {item["code"]: item for item in pending + rechecks}
        batch = [by_code[code] for code in queue]
        if not batch:
            log.info("Nothing new to fetch (%d complete orders already on disk).", len(items))
            return 0

        log.info(
            "%d new order(s) pending, %d recheck(s); checking %d with a %d-order download limit",
            len(pending), len(rechecks), len(batch), MAX_DOWNLOADS_PER_RUN,
        )

        summary = {}
        budget = DownloadBudget(MAX_DOWNLOADS_PER_RUN)
        deferred = []
        for item in batch:
            if not args.dry_run:
                # Save before the attempt: failures and cancellation must not
                # monopolize the first slots. Unattempted orders stay in front.
                queue.remove(item["code"])
                queue.append(item["code"])
                write_manifest_atomic(data_dir / QUEUE_FILE, {"orders": queue})
            try:
                status = process_item(
                    item,
                    token,
                    data_dir,
                    scratch_dir,
                    min_free_bytes,
                    args.dry_run,
                    recheck_days,
                    budget=budget,
                )
            except Exception as exc:  # never let one order kill the whole run
                status = "error"
                log.exception("Unexpected error on %s: %s", item.get("code"), exc)
            if status == "deferred" and not args.dry_run:
                deferred.append(item["code"])
                queue = deferred + [code for code in queue if code not in deferred]
                write_manifest_atomic(data_dir / QUEUE_FILE, {"orders": queue})
            summary[status] = summary.get(status, 0) + 1

        log.info("Run summary: %s", ", ".join(f"{k}={v}" for k, v in sorted(summary.items())))
        log.info("Download slots used: %d/%d; %d order(s) deferred.",
                 len(budget.orders), budget.limit, len(deferred))
        return 1 if summary.get("partial-error") or summary.get("error") else 0

    except (RetryableError, OSError, *NET_ERRORS) as exc:
        log.error("Run failed, will retry next run: %s", exc)
        return 1
    finally:
        shutil.rmtree(lock_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
