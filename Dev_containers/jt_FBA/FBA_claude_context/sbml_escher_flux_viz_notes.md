# SBML → Escher Flux Visualization: Setup Notes

## Goal

Visualize pFBA solution fluxes on a metabolic map derived from an SBML file's Layout Extension, using Escher's interactive viewer.

---

## The Core Problem

There is no single pip-installable Python package that cleanly converts SBML Layout → Escher JSON and overlays flux data. The ecosystem is fragmented across several tools that each handle a piece of the workflow.

---

## Key Tools & Papers

### Escher (`pip install escher`)

- Interactive metabolic map viewer (Jupyter widget or standalone HTML).
- `escher.Builder(map_json=..., model=..., reaction_data=flux_dict)` overlays flux data.
- **Does NOT** include `sbml2escher.py` — that script lives in the GitHub repo at `py/io/sbml2escher.py` but is not part of the pip package.
- The pip package contains only: `plots.py` (Builder class), `urls.py`, `util.py`, `validate.py`, and bundled JS.

### sbml2escher.py (standalone script)

- Lives at: `https://github.com/opencobra/escher/blob/master/py/io/sbml2escher.py`
- Must be downloaded manually.
- Extra dependencies: `xmltodict`, `requests` (not installed by `pip install escher`).
- Converts SBML (with Layout Extension) → Escher JSON map format.
- CLI: `python sbml2escher.py --input model.xml --output map.json`
- Importable: `from sbml2escher import sbml2escher; sbml2escher(infile, outfile)`

### SBMLNetwork (`pip install sbmlnetwork`)

- **Paper**: Heydarabadipour et al. (2025), *PLOS Computational Biology* 21(9):e1013128
- GitHub: `https://github.com/sys-bio/SBMLNetwork`
- High-level API for SBML Layout/Render visualization.
- Built-in flux overlay: `net.show_fluxes(flux_dict, log_scale=True)`
- Built-in Escher-style theming: `net.set_style("escher")`
- Exports to PNG, SVG, PDF — **NOT** Escher JSON format.
- Auto-generates layout if SBML file has none.
- **Cannot export to Escher JSON** — no path from SBMLNetwork → Escher Builder.

### SBMLDiagrams (`pip install SBMLDiagrams`)

- **Paper**: Xu et al. (2023), *Bioinformatics* 39(1):btac730
- Predecessor to SBMLNetwork from the same lab (Sauro group, UW).
- Similar capabilities but pure-Python (slower for large models).

### libsbml (comes with `pip install cobra`)

- `python-libsbml` is installed automatically as a COBRApy dependency.
- Has full Layout Extension support (`LayoutModelPlugin`, `SpeciesGlyph`, `ReactionGlyph`, etc.).
- Can be used to manually extract layout data and build Escher JSON — but the API is very verbose.

### EscherConverter (Java)

- Converts Escher JSON → SBML Layout (the **reverse** direction).
- Requires Java Runtime Environment.
- Not useful for SBML → Escher direction.

---

## System Dependencies for SBMLNetwork

SBMLNetwork depends on `skia-python` for rendering, which needs system-level OpenGL/EGL libraries. On headless Linux (servers, containers, devcontainers):

```dockerfile
# Add to your Dockerfile / devcontainer setup
RUN apt-get update && apt-get install -y \
    libegl1 \
    libgl1 \
    libgles2 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*
```

Without these, `import sbmlnetwork` fails with:
```
ImportError: libEGL.so.1: cannot open shared object file: No such file or directory
```
Then after installing `libegl1`:
```
ImportError: libGL.so.1: cannot open shared object file: No such file or directory
```

Install all of them at once to avoid peeling the onion one library at a time.

---

## Python Dependencies

```
# Core
pip install cobra escher sbmlnetwork

# sbml2escher.py extras (only if using that script)
pip install xmltodict requests
```

`python-libsbml` is pulled in by `cobra` automatically.

---

## Practical Workflow Options

### Option 1: SBMLNetwork (simplest, no Escher)

```python
import sbmlnetwork as sb
from cobra.flux_analysis import pfba
import cobra

model = cobra.io.read_sbml_model("my_model.xml")
solution = pfba(model)

net = sb.load("my_model.xml")
net.set_style("escher")
net.show_fluxes(solution.fluxes.to_dict(), log_scale=True)
net.draw("flux_map.png")
```

Requires system libs: `libegl1 libgl1 libgles2 libfontconfig1`

### Option 2: sbml2escher.py → Escher (interactive, more setup)

```bash
# Download the script
wget https://raw.githubusercontent.com/opencobra/escher/master/py/io/sbml2escher.py
pip install xmltodict requests
```

```python
from sbml2escher import sbml2escher
import escher
import cobra
from cobra.flux_analysis import pfba

# Convert SBML layout to Escher map
sbml2escher("my_model.xml", "my_map.json")

# Load model and run pFBA
model = cobra.io.read_sbml_model("my_model.xml")
solution = pfba(model)

# Visualize
builder = escher.Builder(
    map_json="my_map.json",
    model=model,
    reaction_data=solution.fluxes.to_dict(),
)
builder  # renders in Jupyter
# or: builder.save_html("flux_map.html")
```

### Option 3: libsbml extraction → Escher (self-contained, no extra downloads)

Use the `sbml_layout_to_escher()` function from the notebook I generated earlier. It reads layout data via libsbml (already installed with cobra) and builds the Escher JSON structure in pure Python. See the notebook for the full implementation.

### Option 4: Use existing community Escher maps

If your model uses BiGG IDs, check for pre-built maps:
- `https://github.com/SBRG/escher-maps`
- `escher.list_available_maps()` in Python

```python
builder = escher.Builder(
    map_name="iJO1366.Central metabolism",
    model=model,
    reaction_data=solution.fluxes.to_dict(),
)
```

---

## Conversion Direction Summary

| From | To | Tool |
|------|----|------|
| SBML (with layout) → Escher JSON | `sbml2escher.py` or custom libsbml code |
| Escher JSON → SBML Layout | EscherConverter (Java) |
| SBML → PNG/SVG/PDF (with flux overlay) | SBMLNetwork or SBMLDiagrams |
| SBML → SBML (add auto-layout) | SBMLNetwork `net.save()` |
| COBRApy solution → Escher overlay | `escher.Builder(reaction_data=fluxes)` |

---

## Devcontainer Checklist

```dockerfile
# System deps for SBMLNetwork/skia-python
RUN apt-get update && apt-get install -y \
    libegl1 \
    libgl1 \
    libgles2 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# Python deps
RUN pip install cobra escher sbmlnetwork xmltodict requests
```

If also using Escher in Jupyter:
```dockerfile
RUN pip install notebook
RUN jupyter nbextension install --py escher --sys-prefix
RUN jupyter nbextension enable --py escher --sys-prefix
```
