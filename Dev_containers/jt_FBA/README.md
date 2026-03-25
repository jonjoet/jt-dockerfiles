# FBA Metabolic Modeling Devcontainer

A reproducible environment for genome-scale metabolic modeling, flux balance analysis (FBA), and computational strain design.

## Workflow

1. Load/curate a genome-scale metabolic model (GEM)
2. Characterize wild-type metabolism with FBA, FVA, and flux sampling
3. Use CFSA to compare sampled flux distributions between growth and production phenotypes
4. Use StrainDesign (MILP-based: OptKnock, RobustKnock, MCS) and/or MEWpy (evolutionary algorithms) to identify candidate interventions
5. Simulate and validate candidates with FBA, MOMA, or ROOM
6. Visualize results on metabolic maps with Escher, SBMLNetwork, and SAMMI

## Installed packages

### Core modeling

| Package | Description |
|---|---|
| **COBRApy** | Constraint-based metabolic modeling (FBA, FVA, sampling, essentiality) |
| **optlang** | Solver interface layer used by COBRApy |
| **python-libsbml** | SBML model I/O |

### Strain design tools

| Package | Description |
|---|---|
| **MEWpy** | Evolutionary algorithm-based strain optimization (GA, SPEA2, NSGA-II/III). Also provides MOMA, lMOMA, ROOM, pFBA |
| **StrainDesign** | MILP-based strain design: OptKnock, RobustKnock, OptCouple, Minimal Cut Sets. Requires Java for EFM computations |
| **CFSA** | Comparative Flux Sampling Analysis (installed from [GitLab](https://gitlab.com/wurssb/Modelling/sampling-tools), not on PyPI) |

### Solvers

| Package | Description |
|---|---|
| **HiGHS** (`highspy`) | High-performance LP/MIP solver. Primary solver for FBA, FVA, flux sampling |
| **SCIP** (`pyscipopt`) | MILP solver for bilevel optimization problems in StrainDesign |
| **GLPK** | Ships with COBRApy. Adequate for small models but slower than HiGHS |

### Visualization and Jupyter

| Package | Description |
|---|---|
| **Escher** | Web-based metabolic pathway map viewer (Jupyter widget). Nbextension enabled for inline rendering |
| **SBMLNetwork** | SBML Layout/Render visualization with flux overlays. Exports PNG/SVG/PDF. Requires system OpenGL/EGL libs (installed automatically) |
| **SAMMI** | Semi-Automated Metabolic Map Illustrator. Force-directed bipartite graphs with subgraph parsing, metabolite shelving, and Escher-compatible export. Good for rapid exploration before investing in curated Escher maps |
| **JupyterLab** | Notebook environment (port 8888 forwarded) |
| **ipywidgets** | Widget framework for Escher and interactive notebooks |

### Supporting libraries

numpy, scipy, pandas, matplotlib, seaborn, sympy, joblib, xmltodict, requests

## Parallelism cheat sheet

This machine has **48 CPUs**. Here's how to use them:

```python
# COBRApy FVA
from cobra.flux_analysis import flux_variability_analysis
flux_variability_analysis(model, processes=48)

# COBRApy flux sampling
cobra.sampling.sample(model, n=10000, processes=48)

# COBRApy essentiality screens
find_essential_genes(model, processes=48)
single_gene_deletion(model, processes=48)

# MEWpy evolutionary algorithms
EA(problem, mp=True)

# joblib (general parallel workloads)
from joblib import Parallel, delayed
Parallel(n_jobs=48)(delayed(fn)(x) for x in items)
```

**Inherently single-threaded** (no parallelism knob):
- SCIP (branch-and-bound) -- solves one large MILP for OptKnock/RobustKnock/MCS
- HiGHS -- generally single-threaded; limited multi-thread support via `h.setOptionValue("threads", N)`
- Individual FBA solves -- single LP, sub-millisecond

## Solver selection

COBRApy auto-selects solvers in priority order: Gurobi > CPLEX > GLPK. Since this container has no commercial solvers, it defaults to GLPK unless you explicitly switch:

```python
model.solver = 'highs'
```

Set this early in your notebooks for best performance.

## Known quirks

- **CFSA** is not on PyPI -- installed from GitLab. If it fails during container build, it's likely a packaging issue in their repo.
- **StrainDesign needs Java** for EFM computations. If you see `JVMNotFoundException`, check `java -version` in the container.
- **SBMLNetwork** depends on `skia-python`, which requires `libegl1`, `libgl1`, `libgles2`, and `libfontconfig1`. These are installed via `apt-get` in `post-create.sh`.
- **SAMMI** requires an internet connection at render time (loads JS from the web). It opens visualizations in the browser rather than embedding inline in Jupyter.
- **Version pins use floor-and-ceiling ranges** (e.g., `>=0.30,<1`) so patch fixes are picked up automatically on rebuild.

## Data mount

The container mounts `/mnt/share_data2/JT` to `share_data2/` in the workspace for access to shared data.
