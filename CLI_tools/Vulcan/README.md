# Vulcan

A containerized wrapper around [Vulcan](https://github.com/Cas-Cromwel/Vulcan), a structural variant caller that uses long-read alignments. This is not a custom tool — just a Dockerfile packaging the existing Vulcan software (and its dependencies: minimap2, ngmlr, samtools) via micromamba for portable use.

Used here for read alignment and structural variant detection.

## Prerequisites

- Docker

## Build

```bash
docker build -t vulcan .
```

## Usage

The entrypoint is set to the `vulcan` command, so you can pass arguments directly:

```bash
docker run --rm -v $(pwd):/data vulcan --help
```

```bash
docker run --rm -v $(pwd):/data vulcan \
    -r /data/reference.fa \
    -i /data/reads.fastq \
    -o /data/output \
    -t 8
```

To get a shell instead (e.g. to use minimap2 or samtools directly):

```bash
docker run --rm -it --entrypoint /usr/local/bin/_entrypoint.sh -v $(pwd):/data vulcan bash
```

## Files

- `Dockerfile` — micromamba-based image with Vulcan and dependencies (minimap2, ngmlr, samtools) from bioconda/conda-forge.
- `README.md` — this file.
