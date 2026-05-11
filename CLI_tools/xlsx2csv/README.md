# xlsx2csv

A containerized wrapper around [xlsx2csv](https://github.com/dilshod/xlsx2csv), a Python utility that converts Excel (.xlsx) files to CSV. This is not a custom tool — just a Dockerfile packaging the existing `xlsx2csv` utility for portable use without host installation.

Used here for accepting Excel spreadsheets from colleagues without requiring them to manually export to CSV.

## Prerequisites

- Docker

## Build

```bash
docker build -t xlsx2csv .
```

## Usage

Drop into a bash shell with `xlsx2csv` available:

```bash
docker run --rm -it -v $(pwd):/data xlsx2csv
```

Then convert files:

```bash
xlsx2csv /data/input.xlsx /data/output.csv
```

Or run a one-liner directly:

```bash
docker run --rm -v $(pwd):/data xlsx2csv \
    xlsx2csv /data/input.xlsx /data/output.csv
```

### Common options

```bash
xlsx2csv -s 0 /data/input.xlsx /data/output/    # all sheets to separate files
xlsx2csv -s 2 /data/input.xlsx /data/output.csv  # specific sheet by index
xlsx2csv -n "Sheet Name" /data/input.xlsx /data/output.csv  # specific sheet by name
```

## Files

- `Dockerfile` — Python 3.12-slim with `xlsx2csv` pip-installed.
- `README.md` — this file.
