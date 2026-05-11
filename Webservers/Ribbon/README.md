# Ribbon

A containerized wrapper around [Ribbon/SplitThreader](https://github.com/MariaNattestad/Ribbon), a web-based visualization suite for exploring complex genomic rearrangements and long-range structural variants. This is not a custom tool — just a Dockerfile serving the existing Ribbon 2.1.0 static files via a simple HTTP server.

Ribbon visualizes individual read alignments to help investigate SVs, while SplitThreader (bundled since v2.0) provides a genome-wide view of rearrangements. Especially useful with long reads.

## Prerequisites

- Docker

## Build

```bash
docker build -t ribbon .
```

## Usage

```bash
docker run --rm -p 8000:8000 ribbon
```

Then open http://localhost:8000 in a browser. Load a BAM file and reference to visualize structural variants interactively.

## Files

- `Dockerfile` — Python 3.9-slim serving the Ribbon 2.1.0 release as static files with `python3 -m http.server`.
- `README.md` — this file.
