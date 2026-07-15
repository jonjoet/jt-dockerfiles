# askcos2xlsx

A **Dockerized command-line tool** that converts an **ASKCOS Tree Builder** export into
an Excel workbook (or CSVs) summarising the retrosynthetic routes, their steps, and the
chemicals involved — formulae, molecular weights, InChIKeys, and per-route reaction
schemes.

**The only prerequisite on the host is Docker.** You build the image once, then run the
tool with `docker run`; there is no host Python or RDKit installation. It runs **fully
offline** — nothing leaves the container unless you explicitly opt into online lookup.

## Quick start

Edit the variables at the top of `run.sh` (input file, output name, toggles), then:

```bash
./run.sh
```

`run.sh` builds the image on first use, then runs the container. Offline runs are executed
with `--network none`, so no data can leave the container.

## Or run it manually

```bash
docker build -t treejson2xlsx .

docker run --rm --network none -v "$(pwd):/data" \
    treejson2xlsx /data/treeResults.json -o /data/routes.xlsx --reactions
```

Everything after the image name is passed straight to the CLI. Mount the directory that
holds your JSON to `/data`; the output is written back into that same directory.

## Options

| Flag | Description |
|---|---|
| `-o`, `--output` | Output `.xlsx` path (default: `<input>.xlsx`) |
| `--csv-dir DIR` | Also write CSVs to `DIR` (one per sheet; no embedded images) |
| `--no-xlsx` | Skip the xlsx (use with `--csv-dir`) |
| `--reactions` | Add a unique-**Reactions** sheet/CSV |
| `--no-structures` | Drop the `structures pathway` column (lighter, text-only Routes) |
| `--chem-images` | Embed a structure thumbnail per compound on the **Chemicals** sheet |
| `--online` | Fill compound **names + CAS** from PubChem by InChIKey. **Sends InChIKeys to PubChem — do NOT use for proprietary structures.** |

## Input it expects

The JSON exported by the ASKCOS Tree Builder as a **list of trees in networkx node-link
form** — each element has `graph` (pathway metrics), `nodes` (`id`/`smiles`/`type`, where
type is `chemical` or `reaction`), and `edges` (`from`/`to`). Edge direction is
`product-chemical -> reaction -> reactant-chemical`. Node payload is only
`id`/`smiles`/`type`; formula, MW, and InChIKey are all derived locally with RDKit.

> This expects the node-link *list* form. The newer ASKCOS v2 "UDS" export
> (`{"uds": {"node_dict": ..., "pathways": ...}}`) is a different shape and is not parsed
> by this script.

## Output

**Routes** — one row per pathway. It leads with the two endpoints of the route, each
described by a matching trio of columns: `target` / `target_formula` /
`target_mol_weight` (the desired product) and `feedstock` / `feedstock_formula` /
`feedstock_mol_weight` (the route's ultimate starting material along the main scaffold —
the compound at the bottom of the backbone the `structures pathway` image follows).
Minor co-reactants aren't summarised here; every starting material is on the Chemicals
sheet. Then three parallel one-cell views of the whole route:

- `formulae pathway` — each step as `reactants -> product` using molecular formulae
- `names pathway` — the same, using compound names (falls back to formula when a name
  isn't available; see notes)
- `structures pathway` — a vertical reaction scheme: the main scaffold ("backbone") is
  drawn at each step and co-reactants are shown as **text labels on the arrows**
  (e.g. `3 CH4O`). Full per-compound structures live on the Chemicals sheet.

…plus the pathway metrics from the export (`depth`, `num_reactions`, `atom_economy`,
`avg_plausibility`, etc.). `score` and `cluster_id` are often empty because the export
leaves them unset.

**Steps** — one row per reaction, ordered within each route.

**Chemicals** — one row per unique compound (deduped by InChIKey): canonical SMILES, name,
formula, MW, InChIKey, CAS, role (target / intermediate / starting material with per-role
counts), and pathway count.

**Reactions** *(with `--reactions`)* — one row per unique reaction.

## Notes

- **Names and CAS are not in the ASKCOS export** and cannot be derived from structure.
  They are blank unless `--online` is used (PubChem, public compounds only). For
  proprietary work, keep it offline — the `names pathway` column then falls back to
  formulae. (A proprietary-safe alternative would be an internal name table keyed by
  InChIKey; not implemented here.)
- **Stoichiometry** is written coefficient-first (`3 CH4O`), per chemical convention.
- **Backbone / co-reactants:** the route image follows the largest scaffold at each step
  and renders every other reactant as an arrow label. A genuinely convergent route would
  show its minor branch as a text label rather than a second drawn chain; full detail is
  always on the Steps and Chemicals sheets.
- **Deep routes make tall rows** (one structure per step, stacked). Tune `mw`/`mh`/`gap`
  in `route_image_png()` if you want them tighter.

## Files

| File | Purpose |
|---|---|
| `treejson_to_xlsx.py` | The converter (the container's entrypoint) |
| `Dockerfile` | Builds the self-contained image |
| `requirements.txt` | Python deps, installed into the image at build time |
| `run.sh` | Fillable one-shot runner (build + `docker run`) |

## Optional: run without Docker

Not required, but if you already have a Python environment:

```bash
pip install -r requirements.txt
python treejson_to_xlsx.py treeResults.json -o routes.xlsx --reactions
```
