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

        <item_code>/<item_code>_results.zip   fasta / gbk / reporting files
        <item_code>/<item_code>_reads.zip     raw reads (fastq)
        <item_code>/.complete                 marker + manifest, written LAST

    The zips are left zipped on purpose. pod5 (raw signal) is intentionally not
    fetched.

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
import json
import logging
import os
import shutil
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


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

USER_AGENT = "plasmidsaurus-autofetch/1.0 (stdlib)"

# A run older than this is assumed crashed and its lock is reclaimed.
STALE_LOCK_AFTER = 6 * 3600

COMPLETE_MARKER = ".complete"

# Network errors we treat as transient (HTTPError is a subclass of URLError).
NET_ERRORS = (urllib.error.URLError, TimeoutError)

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
            lock_dir.mkdir()  # if this races and fails, we correctly bail out
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


def download_stream(url: str, dest: Path) -> int:
    """
    Stream a URL to `dest` via a temporary .part file, then atomically move it
    into place. Returns bytes written. Verifies size against Content-Length when
    the server provides it. The .part file guarantees a half-download is never
    mistaken for a finished one.
    """
    part = dest.with_suffix(dest.suffix + ".part")
    written = 0
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        expected = int(resp.headers.get("Content-Length", 0))  # 0 == unknown
        with open(part, "wb") as fh:
            while True:
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                written += fh.write(chunk)
    if expected and written != expected:
        part.unlink(missing_ok=True)
        raise RetryableError(
            f"{dest.name}: incomplete download ({written}/{expected} bytes)"
        )
    os.replace(part, dest)
    return written


# ----------------------------------------------------------------------------
# Per-order processing
# ----------------------------------------------------------------------------

def process_item(item: dict, token: str, data_dir: Path, dry_run: bool) -> str:
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
        try:
            link = fetch_link(token, code, kind)
            if not link:
                continue
            dest = item_dir / f"{code}_{kind}.zip"
            log.info("  downloading %s ...", dest.name)
            size = download_stream(link, dest)
            fetched[kind] = {"file": dest.name, "bytes": size}
            log.info("  saved %s (%d bytes)", dest.name, size)
        except (RetryableError, *NET_ERRORS) as exc:
            errors.append(f"{kind}: {exc}")
            log.warning("  problem fetching %s for %s: %s", kind, code, exc)

    if errors:
        # Leave the folder marker-less so the whole order is retried next run.
        return "partial-error"

    manifest = {
        "item_code": code,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "order": {k: item.get(k) for k in ("product_name", "done_date", "quantity", "status")},
        "files": fetched,
    }
    (item_dir / COMPLETE_MARKER).write_text(json.dumps(manifest, indent=2))
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


def select_pending(items: list, since):
    pending = []
    for item in items:
        if item.get("status") != "complete":
            continue
        done = item.get("done_date")
        if since and done:
            try:
                if datetime.fromisoformat(done) < since:
                    continue
            except ValueError:
                pass  # unparseable date -> don't exclude it
        pending.append(item)
    return pending


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-fetch Plasmidsaurus results to the share.")
    parser.add_argument("--once", action="store_true", help="Run one pass (default).")
    parser.add_argument("--dry-run", action="store_true", help="List what would be fetched; download nothing.")
    parser.add_argument("--data-dir", help="Override the destination folder for this run.")
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
                status = process_item(item, token, data_dir, args.dry_run)
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
