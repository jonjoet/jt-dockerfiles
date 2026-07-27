# Plasmidsaurus autofetch — setup guide

Sets up `plasmidsaurus_autofetch.py` to run on a schedule on the VM, as a
dedicated unprivileged user, via a **systemd timer**. Stdlib-only: no pip
packages, no virtualenv, nothing to install beyond the script itself.

This is upstream ingestion plumbing — it lands Plasmidsaurus deliverables on the
share so other tools can pick them up.

---

## 0. Values to fill in before you start

Gather these; they appear as `<<FILL IN: …>>` throughout.

| Placeholder | What it is | Example |
|---|---|---|
| `<<SHARE_MOUNT>>` | Where the SMB/CIFS file share is mounted on the VM | `/mnt/seq-share` |
| `<<DATA_DIR>>` | Destination folder for downloads (under the share) | `/mnt/seq-share/plasmidsaurus_data` |
| `<<SCRATCH_DIR>>` | Fast, **disk-backed local** scratch with room for the largest single ZIP | `/var/tmp/plasmidsaurus-autofetch` |
| `<<SERVICE_USER>>` | Dedicated account name to create | `plasmidsaurus` |
| `<<CLIENT_ID>>` / `<<CLIENT_SECRET>>` | Your Plasmidsaurus API credentials | from your user profile |
| `<<SCHEDULE>>` | How often to run | `*:0/15` (every 15 min) |
| `<<SINCE>>` | *(optional)* only fetch orders on/after this date | `2026-01-01` |
| `<<YOUR_NAME>>` / `<<YOUR_CONTACT>>` / `<<DATE>>` | For the script header | — |

Generate the Client ID / Secret on your Plasmidsaurus **user profile** page
(`https://www.plasmidsaurus.com/user-info`). Store them somewhere safe — the
secret can't be recovered if lost.

Configure scratch explicitly. It must be backed by a real local disk, not
`tmpfs`/`ramfs` (RAM), because reads ZIPs can be multi-GB. Check the filesystem
that backs the intended parent directory before creating the subdirectory:

```bash
findmnt -no SOURCE,TARGET,FSTYPE,OPTIONS -T /var/tmp
```

`/var/tmp` is commonly disk-backed, but verify rather than assume. If the
reported type is `tmpfs` or `ramfs`, choose a path on a local disk. Scratch needs
room for the largest **single** deliverable ZIP.

---

## 1. Confirm Python is present (3.8+)

```bash
python3 --version        # expect 3.8 or newer
command -v python3       # note this path; used in the script shebang
```

---

## 2. Check how the share is mounted — **this is the step that usually bites**

The download user must be able to **write** to the share. CIFS/SMB mounts are
typically mounted with fixed `uid=`/`gid=` options, meaning everything on the
share is owned by one fixed account regardless of which process writes — so a
plain `chown` later may be silently ignored. Look first:

```bash
findmnt -o SOURCE,TARGET,FSTYPE,OPTIONS <<SHARE_MOUNT>>
```

- If `FSTYPE` is `cifs` and you see `uid=NNNN,gid=NNNN` in the options, that
  UID/GID owns everything on the share. Note those numbers.
- Also note the `file_mode=`/`dir_mode=` — they decide whether group/other can
  write.

You have three ways to make the share writable by the service user (pick one in
step 4). If the mount is managed by IT, you may need them for options (a)/(c):

  a. **Match the mount's UID/GID to the service user** (cleanest): whoever owns
     the fstab entry sets `uid=`/`gid=` to `<<SERVICE_USER>>`.
  b. **Join the owning group**: if `dir_mode`/`file_mode` grant group write, add
     `<<SERVICE_USER>>` to the group that owns the mount.
  c. **Widen the mode**: mount with `dir_mode=0775,file_mode=0664` and a shared
     group. (Coordinate with IT if they manage the mount.)

> If none of these are possible yet, you can still complete the install and test
> with `--dry-run` (which writes nothing); real runs will fail on permission
> until the share is writable.

---

## 3. Create the dedicated unprivileged user

A **static** system user (not systemd `DynamicUser`), because the data persists
on a shared mount that other people and tools read — dynamic users can't own
persistent files on shared storage.

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin <<SERVICE_USER>>
```

---

## 4. Make the share destination writable by the service user

Create the folder and apply whichever approach from step 2 fits:

```bash
sudo mkdir -p <<DATA_DIR>>

# If the mount honours ownership (many CIFS mounts do NOT — see step 2):
sudo chown <<SERVICE_USER>>:<<SERVICE_USER>> <<DATA_DIR>>

# Verify the user can actually write (this is the real test):
sudo -u <<SERVICE_USER>> bash -c 'touch <<DATA_DIR>>/.write_test && rm <<DATA_DIR>>/.write_test && echo WRITABLE'
```

If that prints `WRITABLE`, you're good. If it errors, fix the mount ownership
(step 2) before continuing.

---

## 5. Install the script

```bash
sudo install -m 0755 plasmidsaurus_autofetch.py /usr/local/bin/plasmidsaurus-autofetch
```

`/usr/local/bin` is the standard location for locally-installed executables and
is on every user's PATH. Then edit the header block to record who set it up:

```bash
sudoedit /usr/local/bin/plasmidsaurus-autofetch
#   set <<YOUR_NAME>>, <<DATE>>, <<YOUR_CONTACT>> in the "WHY IT EXISTS" section
```

---

## 6. Store the credentials + config (not world-readable)

```bash
sudo mkdir -p /etc/plasmidsaurus-autofetch
sudo tee /etc/plasmidsaurus-autofetch/environment >/dev/null <<'EOF'
PLASMIDSAURUS_CLIENT_ID=<<CLIENT_ID>>
PLASMIDSAURUS_CLIENT_SECRET=<<CLIENT_SECRET>>
PLASMIDSAURUS_DATA_DIR=<<DATA_DIR>>
PLASMIDSAURUS_SCRATCH_DIR=<<SCRATCH_DIR>>
# Used when the server does not report a ZIP size (default: 512 MiB, in bytes).
#PLASMIDSAURUS_MIN_FREE=536870912
# Uncomment to limit the first-run backfill:
#PLASMIDSAURUS_SINCE=<<SINCE>>
EOF

# Readable only by root and the service user:
sudo chown root:<<SERVICE_USER>> /etc/plasmidsaurus-autofetch/environment
sudo chmod 640 /etc/plasmidsaurus-autofetch/environment
```

---

## 7. Create the systemd service unit

`/etc/systemd/system/plasmidsaurus-autofetch.service`:

```ini
[Unit]
Description=Fetch finished Plasmidsaurus orders to the share
Wants=network-online.target
After=network-online.target
# Ensure the share is mounted before we run:
RequiresMountsFor=<<SHARE_MOUNT>>

[Service]
Type=oneshot
User=<<SERVICE_USER>>
Group=<<SERVICE_USER>>
EnvironmentFile=/etc/plasmidsaurus-autofetch/environment
ExecStart=/usr/local/bin/plasmidsaurus-autofetch

# --- Hardening (running as an unprivileged static user already covers a lot) ---
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
# AF_UNIX + AF_NETLINK are needed for hostname resolution (systemd-resolved /
# nscd socket, and getaddrinfo's interface enumeration) — without them DNS
# can fail. AF_INET/AF_INET6 are the actual outbound connections.
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
# ProtectSystem=strict makes the filesystem read-only EXCEPT what you list here.
# The script must be able to write to the destination folder:
ReadWritePaths=<<DATA_DIR>>
```

> If `ProtectSystem=strict` ever interferes with the CIFS mount, downgrade it to
> `ProtectSystem=full` (which only protects `/usr`, `/boot`, `/etc`) and keep the
> rest.
>
> `PrivateTmp=yes` makes `/tmp` and `/var/tmp` private to the service, but it
> does **not** make them disk-backed: they still use the host filesystem beneath
> those paths. Verify the filesystem as described in section 0. A scratch
> directory under verified `/tmp` or `/var/tmp` needs no additional
> `ReadWritePaths` entry. For a path elsewhere, create it, make it writable by
> `<<SERVICE_USER>>`, and add it to `ReadWritePaths=`. Only one ZIP is buffered
> at a time.

---

## 8. Create the systemd timer unit

`/etc/systemd/system/plasmidsaurus-autofetch.timer`:

```ini
[Unit]
Description=Run Plasmidsaurus autofetch on a schedule

[Timer]
OnCalendar=<<SCHEDULE>>
# Persistent: run once on boot if a scheduled run was missed
Persistent=true
# RandomizedDelaySec: small jitter so we don't hit the API on the exact tick
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
```

(`OnCalendar=*:0/15` = every 15 minutes. `systemd-analyze calendar '<<SCHEDULE>>'`
prints the next trigger times so you can sanity-check the expression.)

---

## 9. Test before enabling the schedule

```bash
sudo systemctl daemon-reload

# 9a. Dry run as the service user — writes nothing, just lists what it would fetch.
sudo -u <<SERVICE_USER>> bash -c \
  'set -a; . /etc/plasmidsaurus-autofetch/environment; set +a; \
   /usr/local/bin/plasmidsaurus-autofetch --dry-run'

# 9b. One real run via systemd, then read the log:
sudo systemctl start plasmidsaurus-autofetch.service
sudo journalctl -u plasmidsaurus-autofetch.service -n 50 --no-pager
```

Confirm files landed:

```bash
find <<DATA_DIR>>/<ITEM_CODE> -maxdepth 2 -type f
# Results are under results/; reads remain compressed under reads/ as *.fastq.gz.
cat <<DATA_DIR>>/<ITEM_CODE>/.complete   # manifest for a finished order
```

---

## 10. Enable the schedule

```bash
sudo systemctl enable --now plasmidsaurus-autofetch.timer
systemctl list-timers plasmidsaurus-autofetch.timer   # shows next run time
```

---

## 11. Day-to-day: where to look

- **Live status / recent runs:** `systemctl status plasmidsaurus-autofetch.timer`
- **Logs (system):** `sudo journalctl -u plasmidsaurus-autofetch.service`
- **Logs (on the share, next to the data):** `<<DATA_DIR>>/_autofetch.log`
- **What's been fetched:** one folder per order code under `<<DATA_DIR>>`, each
  with extracted `results/` and/or `reads/` folders and a `.complete` manifest
  once fully downloaded. Files in `reads/` remain `*.fastq.gz`.

---

## 12. Upgrade from the legacy ZIP layout

Version 2 downloads each ZIP to local scratch and extracts its members directly
to the share. Existing completed orders are skipped based on `.complete`, so
installing the new downloader alone will **not** redownload or convert them.
Use the included one-time migration script to make old folders match the new
layout.

The migration script must remain beside `plasmidsaurus_autofetch.py` when run;
it reuses the downloader's ZIP validation and extraction code.

1. Stop scheduled and active runs:

   ```bash
   sudo systemctl stop plasmidsaurus-autofetch.timer
   sudo systemctl stop plasmidsaurus-autofetch.service
   ```

2. Take a share snapshot or other backup if one is available. Check destination
   free space before migrating:

   ```bash
   df -h <<DATA_DIR>>
   ```

   The default safe migration preserves every legacy ZIP during the first pass,
   so the share must temporarily hold the ZIPs **and** all extracted files.
   Results text/sequence files can expand several-fold. The script preflights
   each order and fails cleanly if space runs out, but the migration cannot
   finish until space is available. After inspection, step 5's `--delete-zips`
   pass reclaims the archive space.

   Then install the updated downloader:

   ```bash
   sudo install -m 0755 plasmidsaurus_autofetch.py /usr/local/bin/plasmidsaurus-autofetch
   ```

3. Add an explicit, verified disk-backed `PLASMIDSAURUS_SCRATCH_DIR` to the
   environment file. Apply the permissions and systemd `ReadWritePaths`
   guidance in step 7 when using a path outside `/tmp` or `/var/tmp`, then run:

   ```bash
   sudo systemctl daemon-reload
   ```

4. From this repository directory, inventory the legacy folders and migrate
   them as the service account:

   ```bash
   sudo -u <<SERVICE_USER>> python3 migrate_legacy_zips.py \
     --data-dir <<DATA_DIR>> --dry-run

   sudo -u <<SERVICE_USER>> python3 migrate_legacy_zips.py \
     --data-dir <<DATA_DIR>>
   ```

   Extraction is staged on the share and then renamed into `results/` and
   `reads/`; no extracted file is copied a second time. The script rewrites
   `.complete` to layout version 2 only after an order succeeds. It is safe to
   rerun after interruption.

5. Inspect several orders and their manifests. Legacy ZIPs are intentionally
   retained on the first pass:

   ```bash
   find <<DATA_DIR>>/<ITEM_CODE> -maxdepth 2 -type f
   python3 -m json.tool <<DATA_DIR>>/<ITEM_CODE>/.complete
   ```

   Once satisfied, remove only the successfully migrated legacy ZIPs:

   ```bash
   sudo -u <<SERVICE_USER>> python3 migrate_legacy_zips.py \
     --data-dir <<DATA_DIR>> --delete-zips
   ```

   No downloader hashes need updating: `.complete` records counts and byte
   sizes, not checksums. Regenerate any separately maintained hashdeep/checksum
   inventory because paths and the set of files have changed.

6. Test one normal run and restart the timer:

   ```bash
   sudo systemctl start plasmidsaurus-autofetch.service
   sudo journalctl -u plasmidsaurus-autofetch.service -n 50 --no-pager
   sudo systemctl start plasmidsaurus-autofetch.timer
   ```

---

## 13. Disable / uninstall

Turn off the schedule (leaves everything else in place):

```bash
sudo systemctl disable --now plasmidsaurus-autofetch.timer
```

Full removal:

```bash
sudo systemctl disable --now plasmidsaurus-autofetch.timer
sudo rm /etc/systemd/system/plasmidsaurus-autofetch.service
sudo rm /etc/systemd/system/plasmidsaurus-autofetch.timer
sudo systemctl daemon-reload
sudo rm /usr/local/bin/plasmidsaurus-autofetch
sudo rm -rf /etc/plasmidsaurus-autofetch
sudo userdel <<SERVICE_USER>>
# Downloaded data on the share is left untouched — delete by hand if you want it gone.
```

---

## 14. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Permission denied` writing to the share | Mount ownership (step 2). Run the write-test in step 4; fix `uid=`/`gid=`/mode. |
| `Refusing to run: destination not configured` | `PLASMIDSAURUS_DATA_DIR` not set / still the placeholder. |
| `CLIENT_ID / CLIENT_SECRET not set` | Env file not loaded or keys missing (step 6). |
| First run tries to pull years of old orders | Expected — it does 5/run. To bound it, set `PLASMIDSAURUS_SINCE` (step 6). |
| An order shows a folder but no `.complete` | A download was interrupted; it will retry on the next run. Safe. |
| `not enough free space` / an order retries | The disk-backed local scratch or destination share is too full. Scratch must hold the largest individual ZIP; verify it is not `tmpfs`/`ramfs` (section 0). |
| Legacy ZIP folders remain after migration | Expected unless `--delete-zips` was explicitly supplied after verification (step 12). |
| Timer never fires | `systemctl list-timers`; check `OnCalendar` with `systemd-analyze calendar`. |
| Runs but fetches nothing | Normal if everything complete is already on disk (see the log line). |

---

## 15. Repository checks

The focused offline suite uses only the standard library and creates temporary
files under this service directory:

```bash
python3 -m unittest discover -s tests -v
```
