# D-Genies

A containerized wrapper around [D-GENIES](https://dgenies.toulouse.inra.fr/) (Dot plot large Genomes in an Interactive, Efficient and Simple way), a web application for dot-plot visualization of genome alignments. This is not a custom tool — just a Dockerfile packaging the existing D-GENIES software for portable use.

## Prerequisites

- Docker

## Build

```bash
docker build -t dgenies .
```

## Usage

```bash
docker run --rm -p 5000:5000 dgenies
```

Then open http://localhost:5000 in a browser. Upload two FASTA files (or a pre-computed alignment) to generate an interactive dot plot showing synteny and structural rearrangements.

## Files

- `Dockerfile` — Python 3.10-slim with pinned Flask/Jinja2/Werkzeug versions and `dgenies` pip-installed.
- `README.md` — this file.
