# Adding SAMMI to the Visualization Toolkit

## Problem

Our SBML model has a layout we don't like, and SBMLNetwork's `auto_layout()` is too slow on the full network — even after pinning low-degree nodes. We need a way to quickly visualize subsets of the network without investing hours in map curation, while still keeping Escher for polished, publication-quality output.

## What SAMMI is

SAMMI (Semi-Automated Metabolic Map Illustrator) is a browser-based tool for visualizing metabolic networks as interactive, force-directed bipartite graphs. It has a Python plugin (`sammipy`) that wraps COBRApy models directly. Developed at MD Anderson (Schultz & Akbani, 2019, *Bioinformatics* 36(8):2616–2617).

## Why we're adding it

### 1. Built-in subgraph parsing solves our "subset the network" problem

SAMMI can partition a GEM into subgraphs by `rxn.subsystem`, by metabolite compartment, or by explicit reaction lists passed as `sammi.parser()` objects. Each subgraph gets its own independent force-directed layout. This means we can visualize only the reactions we care about without building a separate COBRApy submodel or manipulating SBML XML — just tell SAMMI which reactions to show.

### 2. Metabolite shelving removes unimportant nodes from the layout calculation

SAMMI's "shelving" feature lets us hide secondary metabolites (ATP, NADH, H₂O, H⁺, CoA, etc.) from the force-directed layout using regex patterns. Shelved nodes are excluded from the physics simulation entirely but can be restored at any time in the GUI. This is exactly the feature we wanted: removing clutter nodes from the layout calculation without removing them from the model.

### 3. No pre-existing map required

Unlike Escher, which requires either a hand-curated map JSON or tedious one-by-one reaction placement, SAMMI generates a usable layout from scratch for any set of reactions. For rapid exploration this eliminates the biggest bottleneck.

### 4. Richer simultaneous data overlays

SAMMI can map data to reaction color, reaction size, metabolite color, metabolite size, and link width all at once, with multiple datasets. Useful for comparing WT vs. knockout flux distributions at a glance.

### 5. Escher-compatible export provides a bridge

SAMMI can export the current subgraph as Escher-compatible JSON ("Download ESCHER" in the GUI). This means we can use SAMMI to rapidly build and position a subnetwork layout, then bring it into Escher for refinement and long-term use.

## Known limitations vs. Escher

- **Aesthetics**: SAMMI's force-directed bipartite graphs look like graph visualizations, not textbook pathway diagrams. Escher's hand-curated maps with Bézier curves are much more publication-ready.
- **Jupyter integration**: SAMMIpy generates an HTML file and opens it in the browser; it does not embed inline in a notebook the way Escher's reactive widget does.
- **Community maps**: Escher has a library of curated maps for *E. coli*, yeast, and human metabolism. SAMMI has no equivalent — every map starts from a force-directed layout.
- **Ecosystem**: Escher JSON is a de facto standard consumed by many COBRA tools. SAMMI's native format is not widely supported elsewhere.
- **Maintenance**: SAMMIpy's last PyPI update was April 2024. It requires an internet connection to render (loads JS from the web). Functional but not under heavy active development.

## Intended use in our workflow

| Task | Tool | Why |
|------|------|-----|
| **Rapid exploration** of flux distributions across subsystems | SAMMI | One-liner subgraph parsing; no map investment needed |
| **Quick visualization** of StrainDesign/MEWpy knockout results | SAMMI | Shelve cofactors, show only affected pathways |
| **Identifying which pathways matter** before building a curated map | SAMMI | Fast iteration, disposable visualizations |
| **Generating a starting layout** for a new Escher map | SAMMI → Escher export | Position nodes with force-directed layout, then refine in Escher |
| **Fixing awkward positions** after adding reactions to an Escher map | SAMMI (pin existing → re-layout new → export) | Fix curated nodes, let force simulation position additions, export back to Escher JSON |
| **Publication-quality figures** of specific pathways | Escher | Hand-curated maps with flux overlays |
| **Iterative FBA comparison** (WT vs. mutant, parameter sweeps) | Escher | Reactive Jupyter widget, reload data without rebuilding map |

## Workflow: Using SAMMI to fix Escher maps after adding reactions

Escher's pre-built community maps (e.g. `iJO1366.Central metabolism` for *E. coli*, `iMM904.Central carbon metabolism` for yeast) are beautifully laid out but only cover a subset of metabolism. When we load our organism's model against one of these maps, reactions shared via BiGG IDs display correctly, but any reactions we add to the map — either through the Escher GUI ("Add reaction mode") or programmatically via JSON manipulation — land at awkward default positions. Escher has no built-in auto-layout to fix this. SAMMI fills that gap.

### Step 1: Start from a community Escher map

Pick the pre-built map with the best pathway overlap. Load it in Escher with our model to assess coverage:

```python
builder = escher.Builder(
    map_name='iJO1366.Central metabolism',
    model=our_cobra_model,
)
builder.highlight_missing = True  # reactions in map but not in model turn red
```

Escher matches reactions and metabolites between map and model by BiGG ID. Core metabolism reactions (PFK, PYK, CS, GAPD, etc.) share IDs across organisms, so a significant fraction of the map "just works." Reactions that exist in our model but not on the map are available to add via the Escher GUI or programmatically.

### Step 2: Programmatically prune unwanted reactions from the map JSON

The Escher map is a two-element JSON array: `[header_dict, {reactions: {...}, nodes: {...}, text_labels: {...}, canvas: {...}}]`. Each reaction has a `bigg_id` field. To remove reactions we don't need:

1. Load the JSON with `json.load()`.
2. Iterate `map_data[1]["reactions"]`, delete entries whose `bigg_id` isn't in our keep-set.
3. Collect all node IDs still referenced by remaining reactions' `segments` (each segment has `from_node_id` and `to_node_id`).
4. Delete orphaned entries from `map_data[1]["nodes"]` — metabolite nodes no longer connected to any reaction.
5. Save the pruned JSON.

This is pure Python dict manipulation; no special library needed.

### Step 3: Add new reactions to the map JSON

To add a reaction programmatically, we need to create entries in both `reactions` and `nodes` dicts that follow Escher's schema. Each reaction entry contains `name`, `bigg_id`, `reversibility`, `label_x`/`label_y`, `gene_reaction_rule`, `metabolites` (list of `{bigg_id, coefficient, node_id}`), and `segments` (edges between nodes, each with `from_node_id`, `to_node_id`, and optional Bézier handles `b1`/`b2`). Each segment routes through `midmarker` and `multimarker` nodes.

The easiest way to get the correct structure is to use the Escher GUI to add one reaction manually (click on a metabolite already on the map → select the reaction from the dropdown → save the JSON), then inspect the diff to see the exact structure Escher produced. Use that as a template for generating additional reactions in code.

At this point, the newly added reactions have placeholder positions — typically wherever the user clicked or whatever coordinates we assigned programmatically. The existing curated portion of the map looks great; the additions look terrible.

### Step 4: Use SAMMI to re-layout the new reactions

This is the key step. Load the modified Escher map into SAMMI, which will apply its interactive force-directed layout to position the new nodes coherently:

1. **Import into SAMMI**: Use the SAMMI web interface at sammitool.com. Click "Load Single Model" or, if starting from an Escher JSON, load it as an SBML/JSON model. Alternatively, load only the *newly added* reactions as a subgraph alongside the existing positioned reactions.

2. **Fix the well-positioned nodes**: In SAMMI's GUI, select all the nodes that came from the original Escher map (they already have good positions) and fix them in place (right-click → "Fix position", or select and press the fix key). The force-directed simulation will then only move the newly added nodes.

3. **Shelve secondary metabolites**: Use the shelving feature to hide cofactors (ATP, NADH, H₂O, etc.) so the layout engine focuses on the primary pathway topology. These can be restored later.

4. **Let the force simulation run**: SAMMI's continuous force-directed layout will position the new nodes relative to their fixed neighbors. Adjust `edge length` and `node repulsion` parameters in the SAMMI interface until the new reactions settle into reasonable positions.

5. **Manually nudge as needed**: SAMMI allows dragging individual nodes, arranging selections in circles or lines, and curving edges. Use these to polish the positions of the newly added reactions.

6. **Export back to Escher JSON**: Click "Download ESCHER" in the Upload/Download tab. SAMMI exports the current subgraph (including all node positions) as Escher-compatible JSON. Set the `Scale` parameter in the export dialog to match Escher's coordinate space if positions look stretched.

### Step 5: Load the fixed map back into Escher

```python
builder = escher.Builder(
    map_json='sammi_exported_map.json',
    model=our_cobra_model,
    reaction_data=pfba_solution.fluxes.to_dict(),
)
builder.highlight_missing = True
builder.hide_secondary_metabolites = True
```

The curated reactions retain their original Escher positions (they were fixed in SAMMI). The newly added reactions now have force-directed positions that are spatially coherent with their neighbors. From here, do any final tweaks in the Escher Builder GUI and save the map JSON for long-term reuse.

### Alternative to Step 4: NetworkX local layout (no GUI)

If a fully programmatic approach is preferred over SAMMI's interactive GUI, we can use NetworkX's `spring_layout` as a headless alternative:

1. Extract x/y coordinates of all existing (well-positioned) nodes from the Escher JSON.
2. Build a NetworkX graph from the stoichiometric connections of only the newly added reactions plus their immediate neighbors already on the map.
3. Run `nx.spring_layout(G, pos=initial_pos, fixed=pinned_nodes, k=optimal_distance, iterations=500)` — the `fixed` parameter pins the already-positioned nodes so only new nodes move.
4. Write the computed x/y coordinates back into the Escher JSON for the new nodes.

This is faster to script but gives less control than SAMMI's interactive approach, and it won't produce Bézier curves for the edges (those would need to be generated separately or left as straight lines).

## Installation

```bash
pip install sammi
```

No system dependencies beyond a web browser. Requires internet connection at render time.

## Key API entry points

```python
import sammi

# Whole model, parsed by subsystem, with secondary metabolites shelved
sammi.plot(model, 'subsystem', secondaries=['^h_c$', '^h2o_c$', '^atp_c$', '^adp_c$'])

# Custom subgraph: only specific reactions
parser = [sammi.parser(reactions=['PFK', 'PYK', 'PGK', 'GAPD', 'TPI'], name='Glycolysis')]
sammi.plot(model, parser)

# With flux data overlay
data = [sammi.data(group='reactions', kind='color', data=flux_dataframe)]
sammi.plot(model, parser, data, secondaries=['^h_c$', '^h2o_c$'])
```

## References

- Schultz, A. & Akbani, R. (2019). SAMMI: A Semi-Automated Tool for the Visualization of Metabolic Networks. *Bioinformatics*, 36(8), 2616–2617.
- Documentation: https://sammi.readthedocs.io
- SAMMIpy docs: https://sammipy.readthedocs.io
- Web tool: https://www.sammitool.com
- GitHub: https://github.com/MD-Anderson-Bioinformatics/SAMMI
