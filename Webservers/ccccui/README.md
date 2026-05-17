# ccccui — CHOPCHOP Cpf1 Web Interface

A Streamlit-based web frontend for designing Cpf1 (Cas12a) guide RNAs using [CHOPCHOP](https://chopchop.cbu.uib.no/). Users upload a target FASTA, adjust PAM/guide parameters, and download scored guide candidates as a TSV. Optionally annotates guides back onto a GenBank file.

Runs as a single Docker container built on top of a local `chopchop:ATCC13032` image (CHOPCHOP configured with a *C. glutamicum* ATCC 13032 genome index).

## Setup on the VM

### 1. Build the image

Copy this directory to the VM, then:

```bash
cd /path/to/ccccui
docker build -t ccccui:latest .
```

### 2. Run the container

```bash
docker run -d --name ccccui -p 1721:8501 --restart unless-stopped ccccui:latest
```

The web interface will be available at `http://<VM_IP>:1721`.

### 3. Stop / restart

```bash
docker stop ccccui
docker start ccccui

# Or remove and rebuild after changes:
docker rm -f ccccui
docker build -t ccccui:latest . && docker run -d --name ccccui -p 1721:8501 --restart unless-stopped ccccui:latest
```

## User access from Windows

1. Edit `connect.bat` and fill in the three values marked `<-- CHANGE THIS`:
   - `VM_USER` — SSH username on the Azure VM
   - `VM_IP` — the VM's IP address
   - `SSH_KEY` — full path to the private key on the Windows machine

2. Double-click `connect.bat`. It opens an SSH tunnel and launches the browser.

3. Close the terminal window to disconnect.

## What it does

1. User uploads a FASTA file containing the target sequence
2. Optionally uploads a GenBank file for guide annotation
3. Sets parameters (PAM, guide length, max mismatches) — sensible defaults are pre-filled
4. Clicks "Run CHOPCHOP"
5. Downloads the results TSV (and annotated GenBank, if applicable)

## Configuration reference

Values baked into `app.py` that may need changing:

| Setting | Current value | Where |
|---------|--------------|-------|
| Genome identifier | `ATCC13032` | `app.py`, the `-G` argument |
| Scoring method | `KIM_2018` | `app.py`, the `-scoringMethod` argument |
| Default PAM | `TTTM` | `app.py`, form default |
| Default guide length | `21` | `app.py`, form default |
| Default max mismatches | `3` | `app.py`, form default |
