# PRO-barcodes

A containerized wrapper around [PRO](https://github.com/rztongr/PRO) (Phylogenetically Robust Oligos), a DNA barcode designer optimized for nanopore sequencing. This is not a custom tool — just a Dockerfile packaging the existing PRO software for portable, Nextflow-compatible use.

Used here for generating nanopore-compatible sequence barcodes.

## Prerequisites

- Docker

## Build

```bash
docker build -t pro-barcodes .
```

## Usage

Drop into a bash shell with PRO available:

```bash
docker run --rm -it -v $(pwd):/data pro-barcodes
```

From there, run PRO scripts (e.g. `PRO.py`) per the [upstream documentation](https://github.com/rztongr/PRO).

### Nextflow integration

The container has no fixed entrypoint, making it compatible with Nextflow process definitions:

```groovy
process DESIGN_BARCODES {
    container 'pro-barcodes'

    script:
    """
    python3 /opt/PRO/PRO.py [args]
    """
}
```

## Files

- `Dockerfile` — Python 3.10-slim with edlib, tqdm, and the PRO repository cloned to `/opt/PRO`.
- `README.md` — this file.
