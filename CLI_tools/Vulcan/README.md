# Vulcan

A containerized wrapper around [Vulcan](https://gitlab.com/treangenlab/vulcan/-/tree/master), a long-read mapping framework that combines minimap2 and NGMLR for improved alignment quality. This is not a custom tool — just a Dockerfile packaging the existing Vulcan software (and its dependencies: minimap2, ngmlr, samtools) via micromamba for portable use.

Vulcan first maps reads with minimap2, then identifies poorly aligned reads by their normalized edit distance and realigns those with NGMLR (more accurate but slower). This two-pass approach improves both recall and precision over using either mapper alone. Supports PacBio CLR, PacBio HiFi, and Oxford Nanopore reads.

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
    -ont \
    -t 8
```

The output is a sorted BAM file (`output_90.bam` by default, where 90 is the edit distance percentile cutoff).

To get a shell instead (e.g. to use minimap2 or samtools directly):

```bash
docker run --rm -it --entrypoint /usr/local/bin/_entrypoint.sh -v $(pwd):/data vulcan bash
```

## Files

- `Dockerfile` — micromamba-based image with Vulcan and dependencies (minimap2, ngmlr, samtools) from bioconda/conda-forge.
- `README.md` — this file.
