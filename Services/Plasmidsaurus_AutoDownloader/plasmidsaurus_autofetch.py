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

    Each deliverable zip is buffered on fast local scratch, extracted straight
    to a hidden staging folder on the share, and exposed with a same-share
    rename. The zip never touches the share and extracted file data is written
    there only once. pod5 (raw signal) is intentionally not fetched.

WHY IT EXISTS / WHO SET IT UP
    Stopgap set up by <YOUR NAME / TEAM> on <DATE SET UP> so results land
    automatically instead of being fetched by hand. Questions: <YOUR CONTACT>.
    If you found this and have no idea what it is: it is safe to turn off (see
    "HOW TO DISABLE"). It touches nothing except the destination folder.

HOW IT RUNS
    Invoked on a schedule by a systemd timer (plasmidsaurus-autofetch.timer),
    as a dedicated unprivileged user. See the setup guide for the install.
    Each run handles at most MAX_DOWNLOADS_PER_RUN orders (to stay
    friendly with the API); anything still pending is picked up next run.
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

DEPENDENCIES
    Python 3.8+ standard library only. No pip packages, no virtualenv.

SAFE TO RE-RUN
    Idempotent. An order counts as "done" only once its `.complete` marker is
    written, which happens after every available file has fully downloaded. A
    partial/interrupted download leaves no marker and is retried next run, so
    you never get a half-downloaded zip masquerading as finished. Run by hand:
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
from datetime import datetime, timezone
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

# Cap per run so a first-time backfill doesn't hammer the API. Leftovers roll
# over to the next scheduled run.
MAX_DOWNLOADS_PER_RUN = 5

# Only consider orders completed on/after this date, if set (env override).
_since_env = os.getenv("PLASMIDSAURUS_SINCE")

# Per-socket-operation timeout (seconds) and streaming chunk size.
HTTP_TIMEOUT = 120
CHUNK_SIZE = 1 << 20  # 1 MiB

USER_AGENT = "plasmidsaurus-autofetch/2.0 (stdlib)"

# A run older than this is assumed crashed and its lock is reclaimed.
STALE_LOCK_AFTER = 6 * 3600

COMPLETE_MARKER = ".complete"
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
    Raise RetryableError for rate-limiting / server errors so it is retried.
    """
    try:
        payload = _api_get(token, f"/api/item/{code}/{kind}")
    except urllib.error.HTTPError as exc:
        if exc.code == 429 or exc.code >= 500:
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
    url: str, scratch_path: Path, min_free_bytes: int
) -> int:
    """
    Stream a URL to local scratch via a temporary .part file. Returns bytes
    written and verifies Content-Length when supplied.
    """
    # Defence-in-depth: never let a link from the API send urllib to file://,
    # ftp://, data:, etc. (Don't log the URL -- presigned links carry secrets.)
    scheme = urllib.parse.urlparse(url).scheme
    if scheme != "https":
        raise RetryableError(f"refusing download link with non-https scheme {scheme!r}")
    part = scratch_path.with_suffix(scratch_path.suffix + ".part")
    part.unlink(missing_ok=True)
    written = 0
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
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
        return written
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


def extract_zip(scratch_zip: Path, staging_dir: Path) -> dict:
    """
    Validate and extract one local zip directly into a staging directory on the
    share. Reading every member to EOF also verifies its ZIP CRC.
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
            total_bytes = sum(info.file_size for info, _ in file_members)
            ensure_free_space(staging_dir.parent, total_bytes)
            staging_dir.mkdir(parents=True)

            for info, relative in members:
                output = staging_dir / relative
                if info.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as source, open(output, "xb") as destination:
                    shutil.copyfileobj(source, destination, length=CHUNK_SIZE)
        return {"files": len(file_members), "bytes": total_bytes}
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

def process_item(
    item: dict,
    token: str,
    data_dir: Path,
    scratch_dir: Path,
    min_free_bytes: int,
    dry_run: bool,
) -> str:
    """
    Download every available deliverable for one order into its own folder, then
    write the .complete marker. Returns a short status string for the run summary.
    """
    code = item["code"]
    item_dir = data_dir / code

    if (item_dir / COMPLETE_MARKER).exists():
        return "skip-done"

    if dry_run:
        log.info("[dry-run] would fetch %s (%s)", code, item.get("product_name", "?"))
        return "would-fetch"

    item_dir.mkdir(parents=True, exist_ok=True)
    fetched, errors = {}, []

    for kind in DATA_TYPES:
        work_dir = None
        try:
            link = fetch_link(token, code, kind)
            if not link:
                _remove_path(item_dir / kind)
                continue
            work_dir = Path(
                tempfile.mkdtemp(prefix=f"plasmidsaurus-{code}-{kind}-", dir=scratch_dir)
            )
            scratch_zip = work_dir / f"{code}_{kind}.zip"
            log.info("  downloading %s to local scratch ...", scratch_zip.name)
            archive_bytes = download_to_scratch(
                link, scratch_zip, min_free_bytes=min_free_bytes
            )

            staging = item_dir / f".{kind}.partial"
            destination = item_dir / kind
            # A marker-less order has no committed output. Removing an earlier
            # attempt first avoids needing space for two extracted copies.
            _remove_path(destination)
            stats = extract_zip(scratch_zip, staging)
            os.replace(staging, destination)
            fetched[kind] = {
                "directory": kind,
                "files": stats["files"],
                "bytes": stats["bytes"],
                "archive_bytes": archive_bytes,
            }
            log.info(
                "  extracted %s (%d files, %d bytes)",
                destination,
                stats["files"],
                stats["bytes"],
            )
        except (RetryableError, OSError, *NET_ERRORS) as exc:
            errors.append(f"{kind}: {exc}")
            log.warning("  problem fetching %s for %s: %s", kind, code, exc)
            try:
                _remove_path(item_dir / f".{kind}.partial")
            except OSError:
                pass
        finally:
            if work_dir is not None:
                shutil.rmtree(work_dir, ignore_errors=True)

    if errors:
        # Leave the folder marker-less so the whole order is retried next run.
        return "partial-error"

    manifest = {
        "layout_version": LAYOUT_VERSION,
        "item_code": code,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "order": {k: item.get(k) for k in ("product_name", "done_date", "quantity", "status")},
        "files": fetched,
    }
    write_manifest_atomic(item_dir / COMPLETE_MARKER, manifest)
    return "done" if fetched else "done-empty"


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
        pending.append(item)
    return pending


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-fetch Plasmidsaurus results to the share.")
    parser.add_argument("--once", action="store_true", help="Run one pass (default).")
    parser.add_argument("--dry-run", action="store_true", help="List what would be fetched; download nothing.")
    parser.add_argument("--data-dir", help="Override the destination folder for this run.")
    parser.add_argument(
        "--scratch-dir",
        help="Override the local scratch directory for this run.",
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
        pending = select_pending(items, since)
        pending = [i for i in pending if not (data_dir / i["code"] / COMPLETE_MARKER).exists()]

        batch = pending[:MAX_DOWNLOADS_PER_RUN]
        if not batch:
            log.info("Nothing new to fetch (%d complete orders already on disk).", len(items))
            return 0

        log.info(
            "%d order(s) pending; handling %d this run: %s",
            len(pending), len(batch), ", ".join(i["code"] for i in batch),
        )

        summary = {}
        for item in batch:
            try:
                status = process_item(
                    item,
                    token,
                    data_dir,
                    scratch_dir,
                    min_free_bytes,
                    args.dry_run,
                )
            except Exception as exc:  # never let one order kill the whole run
                status = "error"
                log.exception("Unexpected error on %s: %s", item.get("code"), exc)
            summary[status] = summary.get(status, 0) + 1

        log.info("Run summary: %s", ", ".join(f"{k}={v}" for k, v in sorted(summary.items())))
        if len(pending) > len(batch):
            log.info("%d more will be fetched on the next run.", len(pending) - len(batch))
        return 0

    except NET_ERRORS as exc:
        log.error("API error, will retry next run: %s", exc)
        return 1
    finally:
        shutil.rmtree(lock_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
