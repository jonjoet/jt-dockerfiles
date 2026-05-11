# Hashdeep

A containerized wrapper around [hashdeep](https://github.com/jessek/hashdeep), a set of tools for computing and auditing file hashes recursively. This is not a custom tool — just a Dockerfile packaging the existing `hashdeep` utility for portable use without host installation.

Used here for verifying the integrity of large-scale file transfers (confirming all files arrived intact).

## Prerequisites

- Docker

## Build

```bash
docker build -t hashdeep .
```

## Usage

Mount the directory you want to hash into the container and run hashdeep commands interactively:

```bash
docker run --rm -it -v /path/to/files:/data hashdeep
```

This drops you into a bash shell with `hashdeep`, `md5deep`, `sha1deep`, `sha256deep`, etc. available.

### Example: generate a manifest then audit against it

On the source machine (or before transfer):

```bash
docker run --rm -v /path/to/files:/data hashdeep \
    hashdeep -r -l /data > /path/to/manifest.txt
```

After transfer, audit the destination against the manifest:

```bash
docker run --rm -v /path/to/destination:/data -v /path/to/manifest.txt:/manifest.txt hashdeep \
    hashdeep -r -l -k /manifest.txt -a /data
```

## Files

- `Dockerfile` — Debian bookworm-slim with `hashdeep` package installed.
- `README.md` — this file.
