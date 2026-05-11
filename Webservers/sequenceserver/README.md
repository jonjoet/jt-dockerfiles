# SequenceServer

A containerized wrapper around [SequenceServer](https://sequenceserver.com/) ([GitHub](https://github.com/wurmlab/sequenceserver)), a web frontend for NCBI BLAST+. This is not a custom tool — just a Dockerfile packaging the existing SequenceServer software with BLAST+ binaries for portable use.

Point it at your own BLAST databases and get a clean web UI for running blastn, blastp, blastx, tblastn, and tblastx searches.

## Prerequisites

- Docker
- One or more BLAST databases (or FASTA files to create them from)

## Build

```bash
docker build -t sequenceserver .
```

## Usage

On first run, the container launches interactive setup (`sequenceserver -s`) to configure your database path, then starts the server automatically:

```bash
docker run --rm -it -p 4567:4567 -v /path/to/your/databases:/db sequenceserver
```

Then open http://localhost:4567 in a browser.

To skip setup on subsequent runs (if you've already configured databases), override the command:

```bash
docker run --rm -p 4567:4567 -v /path/to/your/databases:/db sequenceserver \
    /bin/sh -c "sequenceserver -d /db"
```

## Files

- `Dockerfile` — Multi-stage build: NCBI BLAST+ 2.16.0 static binaries copied into a Ruby 3.2 image with SequenceServer gem installed.
- `README.md` — this file.
