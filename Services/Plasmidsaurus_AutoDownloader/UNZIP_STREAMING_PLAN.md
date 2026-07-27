# Implementation plan: unzip deliverables, writing to the SMB share only once

> Implemented on this branch. The downloader, migration script, tests, and
> `SETUP.md` are the source of truth where they differ from this original design
> sketch.

## Context

`plasmidsaurus_autofetch.py` currently streams each order's `results.zip` and
`reads.zip` straight to the SMB share and **leaves them zipped on purpose**. We
now want the contents unzipped, but the share is slow, so we must write to it
only **once** per order — never land the zip on the share and then re-read /
re-expand it there.

Decisions locked in:

- **Unzip both** `results` and `reads`, but for reads **do not decompress the
  members**. The reads zip contains already-gzipped `fastq.gz` files, which every
  downstream pipeline reads as-is. Standard zip extraction does exactly this: it
  bursts the zip container while leaving each inner `fastq.gz` byte-for-byte
  intact.
- **Mechanism: download each zip to fast *local* scratch, then extract members
  straight to the SMB share.** The zip never touches SMB; only the extracted
  files are written to SMB, once. `stream-unzip` (true on-the-fly streaming) was
  rejected: it raises `NotStreamUnzippable` on entries stored *uncompressed with
  a data descriptor* — the likely packing of `fastq.gz` — and it would add a pip
  dependency + Docker deployment. The stdlib `zipfile` route stays
  dependency-free, keeps the systemd-service model, and handles every zip
  variant.
- **One zip on scratch at a time.** Scratch space is limited. Per order:
  download `results.zip` → extract → delete scratch zip → download `reads.zip` →
  extract → delete scratch zip → write `.complete`. Peak scratch usage is the
  size of the single largest individual zip, never more.
- **Free-space preflight before each download** (see below), so a too-small or
  full scratch disk fails the order cleanly for retry instead of writing a
  truncated zip.

No in-repo consumer depends on the old `<code>_results.zip` layout (only the
top-level README table references the service), so the on-share layout is free to
change.

## Output layout (assumption — easily changed)

Extract each deliverable into its own subfolder under the order folder, to avoid
filename collisions between the two zips and any doubled-nesting ambiguity from a
zip that already namespaces its contents:

```
<DATA_DIR>/<code>/results/…        (extracted results tree)
<DATA_DIR>/<code>/reads/…          (extracted reads tree; members stay *.fastq.gz)
<DATA_DIR>/<code>/.complete        (manifest, written LAST — unchanged gate)
```

If pipelines expect a flat layout, this is a one-line change (extract into
`<code>/` directly).

## Changes to `plasmidsaurus_autofetch.py`

1. **New config knob `PLASMIDSAURUS_SCRATCH_DIR`** (near `DATA_DIR`, ~L93).
   Default to `tempfile.gettempdir()` (respects `TMPDIR` / systemd `PrivateTmp`).
   Zips are buffered here; must be **local** and large enough for the biggest
   single zip. Add `import tempfile`.

2. **Free-space preflight — `ensure_free_space(path, needed_bytes, margin=1.05)`**
   (new helper). Uses `shutil.disk_usage(path).free`; raises `RetryableError`
   (so the order retries next run, when space may have freed) if
   `free < needed_bytes * margin`. Called:
   - **Before each scratch download**, using the zip's expected size. The GET
     response exposes `Content-Length` before the body is read (already read at
     L286 as `expected`); check scratch free space against it *before* writing
     the first chunk. If `Content-Length` is absent (`0`/unknown), fall back to
     requiring a configurable floor of free space (e.g. `PLASMIDSAURUS_MIN_FREE`,
     default a few hundred MB) rather than skipping the check entirely.
   - **Before extraction**, against the SMB share using the sum of
     member `file_size`s from the zip's central directory
     (`sum(zi.file_size for zi in zf.infolist())`) — a nice-to-have that catches a
     full share before a long extract.

3. **Split `download_stream` (L270-299)** into:
   - `download_to_scratch(url, scratch_path) -> int`: keep the existing https
     scheme check, `.part`-then-rename, and Content-Length verification — but the
     `.part`/final live in the **scratch dir**, not on the share. Add the
     free-space preflight right after reading `Content-Length`, before the write
     loop. Returns bytes written.
   - `extract_zip(scratch_zip, dest_dir) -> dict`: open with `zipfile.ZipFile`
     and stream members into `dest_dir` via `zf.extractall(dest_dir)` (or an
     explicit `open()` + `shutil.copyfileobj` loop). Both decompress each member
     in bounded-memory chunks, so multi-GB `fastq.gz` members never load fully
     into RAM. `extractall` also sanitizes member paths (zip-slip protection),
     which matters now that zip *contents* come from the API. Return
     `{ "files": <count>, "bytes": <uncompressed total> }`. Add `import zipfile`
     (`shutil` already imported).

4. **Rework `process_item` (L306-349)** — per `kind` in `DATA_TYPES`:
   - `link = fetch_link(...)`; skip if none (unchanged).
   - `scratch_zip = Path(scratch_dir) / f"{code}_{kind}.zip"`.
   - `download_to_scratch(link, scratch_zip)` inside a `try/finally` that
     `unlink(missing_ok=True)` the scratch zip — gone before the next download
     regardless of success/failure (honors one-zip-at-a-time).
   - Extract to `<item_dir>/.<kind>.partial`, then rename it to
     `<item_dir>/<kind>` on the same share. This rename is metadata-only:
     extracted file contents are still written to SMB exactly once.
   - Record extracted stats in `fetched[kind]`.
   - Keep existing error handling: any `RetryableError`/net error (now including
     insufficient-space) leaves the order **marker-less** so the whole order
     retries next run. `.complete` remains the atomicity gate — no half-extracted
     order ever looks finished.
   - Thread a new `scratch_dir` param from `main`.

5. **Manifest (L342-349)**: `files` maps each kind to
   `{ "files": <count>, "bytes": <total> }` instead of the single zip's name.

6. **Header docstring (L6-21) + `DATA_TYPES` comment**: update "WHAT THIS IS" to
   describe the extracted `results/` and `reads/` folders, note reads members are
   left as `fastq.gz` (not decompressed), and drop "The zips are left zipped on
   purpose."

## Changes to `SETUP.md`

- Add `PLASMIDSAURUS_SCRATCH_DIR` (and optional `PLASMIDSAURUS_MIN_FREE`) to the
  config table (§0) and env file (§6), with a sizing note: **local disk with room
  for your largest single zip** (reads can be multi-GB); one zip at a time, so
  that's the peak.
- If scratch stays on `PrivateTmp`'s default, no extra `ReadWritePaths` needed; if
  pointed elsewhere, add it to `ReadWritePaths=` in the systemd unit (§7).
- Update "what gets written" (§9, §11) to describe `results/` + `reads/` folders
  instead of `<code>_results.zip`.
- Add troubleshooting rows (§13): `No space left`/order stuck retrying →
  scratch dir too small or not local; free-space preflight is defending the run.
- The "stdlib-only, no pip" framing stays accurate — `zipfile`, `tempfile`,
  `shutil.disk_usage` are all stdlib.
- Add an upgrade procedure and a one-time, idempotent migration script for
  legacy ZIP folders. Preserve ZIPs by default; delete them only with an
  explicit flag after verification.

## Verification

- **Unit-level, offline (no API/creds needed).** Use a scratch test folder under
  the working directory. The existing HTTPS download path is already deployed,
  so this change does not build a local download service. Build a small
  `results.zip` (a couple text files) and a `reads.zip` containing a real
  `*.fastq.gz` member, then assert: (a) the share dir gets `results/` + `reads/`;
  (b) the `fastq.gz` member is byte-identical to the original (still gzipped);
  (c) the scratch zip is deleted afterward; (d) `.complete` is written only when
  both kinds succeed; (e) a forced mid-extract failure leaves no `.complete` and a
  re-run completes cleanly; (f) the free-space preflight raises `RetryableError`
  (order retried, no `.complete`) when `shutil.disk_usage` is stubbed to report
  less free space than the incoming zip.
- **End-to-end.** `python3 plasmidsaurus_autofetch.py --dry-run` (unchanged
  listing path), then a real run against live creds: confirm per-order folders
  contain extracted trees and peak scratch never exceeds one zip (watch the
  scratch dir during the run).
