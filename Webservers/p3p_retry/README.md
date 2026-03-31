# Primer3Plus dPCR Server

A self-contained Docker image for dPCR primer design. Builds primer3 and primer3plus from source, then runs the Flask API server and a static file server under supervisord.

## Setup on the VM

### 1. Build the image

```bash
cd /path/to/p3p_retry
docker build -t p3p_retry:latest .
```

### 2. Run the container

```bash
docker run -d --name p3p_retry -p 1234:1234 -p 3300:3300 --restart unless-stopped p3p_retry:latest
```

### 3. Stop / restart

```bash
docker stop p3p_retry
docker start p3p_retry

# Or remove and rebuild after changes:
docker rm -f p3p_retry
docker build -t p3p_retry:latest . && docker run -d --name p3p_retry -p 1234:1234 -p 3300:3300 --restart unless-stopped p3p_retry:latest
```

## User access from Windows

1. Edit `connect.bat` and fill in the three values marked `<-- CHANGE THIS`:
   - `VM_USER` — SSH username on the VM
   - `VM_IP` — the VM's IP address
   - `SSH_KEY` — full path to the private key on the Windows machine

2. Double-click `connect.bat`. It opens an SSH tunnel and launches the browser.

3. Close the terminal window to disconnect.

## Loading dPCR settings

The file `Primer3Plus_dPCR.txt` contains pre-configured settings optimized for dPCR primer design (product size 70-140 bp, tight Tm range, etc.).

To load them in Primer3Plus:

1. Connect to the server using `connect.bat`
2. In the Primer3Plus interface, click **Load Settings**
3. Upload `Primer3Plus_dPCR.txt` from this directory
4. The form will populate with the dPCR parameters — you can then paste your sequence and run
