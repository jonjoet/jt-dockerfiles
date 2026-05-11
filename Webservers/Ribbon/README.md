# Ribbon

A containerized wrapper around [Ribbon](https://github.com/MariaNattestad/Ribbon), a web-based visualization tool for structural variants and complex genomic rearrangements. This is not a custom tool — just a Dockerfile serving the existing Ribbon static files via a simple HTTP server.

Ribbon displays read alignments as colored "ribbons" connecting split and supplementary alignments, making translocations, inversions, and other SVs easy to identify visually.

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
