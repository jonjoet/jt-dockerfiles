# jt_dna

A devcontainer for custom DNA construct design, built on top of the [Edinburgh Genome Foundry](https://edinburgh-genome-foundry.github.io/) (EGF) Python ecosystem. Also used as a sandbox for testing new software and approaches for DNA construct design.

## What's inside

The image is based on `egf-notebook:latest` (a Jupyter-based image with the EGF suite pre-installed), extended with:

### Python packages

| Package | Description |
|---|---|
| **EGF suite** (via base image) | DnaCauldron, DnaChisel, GoldenHinges, Primavera, etc. — modular cloning assembly, sequence optimization, and primer design |
| **pydna** | Simulation of molecular cloning (PCR, Gibson, restriction/ligation) |
| **benchling-sdk** | Programmatic access to Benchling for sequence retrieval and registration |
| **rpy2** | Call R from Python (used for DNABarcodes below) |

### R packages

| Package | Description |
|---|---|
| **DNABarcodes** (Bioconductor) | Design and analysis of DNA barcode sets with error-correction properties |

### Jupyter kernels

- Python 3 (default)
- R (via IRkernel)

## Usage

Open the folder containing this `.devcontainer/` in VS Code with the Dev Containers extension. The container will build from the Dockerfile and attach automatically.

The workspace mounts to `/home/jovyan/work`, and shared data is available at `share_data2/` within the workspace.

## Files

- `Dockerfile` — Extends `egf-notebook:latest` with R, IRkernel, DNABarcodes, pydna, benchling-sdk, and rpy2.
- `devcontainer.json` — VS Code devcontainer configuration (mounts, extensions, user settings).
- `README.md` — this file.
