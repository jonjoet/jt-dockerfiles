# escher-cli

CLI tool for generating standalone Escher metabolic pathway HTML files. Pins **escher 1.7.3** (later versions broke drag-to-merge metabolites).

## Quick Start (Docker)

```bash
# Build
docker build -t escher-cli .

# Generate HTML from a community map
docker run --rm -v $(pwd):/data escher-cli output.html \
    --map-name "e_coli_core.Core metabolism"

# Local map + SBML model + flux overlay
docker run --rm -v $(pwd):/data escher-cli output.html \
    --map-file my_map.json \
    --model-sbml model.xml \
    --reaction-data fluxes.csv \
    --metabolite-data concentrations.json
```

## Quick Start (pip)

```bash
pip install .
escher-cli output.html --map-name "iJO1366.Central metabolism" --reaction-data fluxes.csv
```

## CLI Reference

```
escher-cli OUTPUT [options]

Positional:
  output                  Output HTML file path

Map source (mutually exclusive):
  --map-name NAME         Community map name (e.g. "iJO1366.Central metabolism")
  --map-file PATH         Path to local Escher map JSON file

Model source (mutually exclusive):
  --model-sbml PATH       SBML model file (loaded via COBRApy, converted to JSON)
  --model-json PATH       Escher-compatible model JSON file

Data overlays:
  --reaction-data PATH    Reaction data file (CSV/TSV or JSON)
  --metabolite-data PATH  Metabolite data file (CSV/TSV or JSON)
```

## Data Formats

### CSV (reaction or metabolite data)

```csv
reaction_id,value
PFK,1.5
PYK,3.2
GAPD,8.1
```

First column = IDs, second column = values. Header row required.

### TSV

Same as CSV but tab-delimited. Auto-detected by `.tsv` extension.

### JSON

```json
{"PFK": 1.5, "PYK": 3.2, "GAPD": 8.1}
```

Flat `{id: value}` mapping.

## Why 1.7.3?

Escher versions after 1.7.3 broke the ability to merge metabolites by dragging in the interactive editor. This is tracked in open issues on the escher GitHub repo. Version 1.7.3 is the last known-good release for this feature.
