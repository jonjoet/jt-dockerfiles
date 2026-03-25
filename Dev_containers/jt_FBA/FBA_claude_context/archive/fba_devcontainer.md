# Devcontainer: Design Decisions and Compatibility Analysis

## Project Context

This project uses genome-scale metabolic models (GEMs) and flux balance analysis (FBA) for computational strain design. The goal is to identify genetic interventions (knockouts, overexpressions, downregulations) that improve production of target metabolites in microbial cell factories.

The workflow, broadly, is:

1. Load/curate a GEM (stoichiometric matrix of all known metabolic reactions in an organism)
2. Characterize wild-type metabolism with FBA, FVA, and flux sampling
3. Use CFSA to compare sampled flux distributions between growth and production phenotypes
4. Use StrainDesign (MILP-based: OptKnock, RobustKnock, MCS) and/or MEWpy (evolutionary algorithm-based) to identify candidate interventions
5. Simulate and validate candidates with FBA, MOMA, or ROOM
6. Visualize results on metabolic maps with Escher

The devcontainer is designed to provide a reproducible, batteries-included environment for this entire pipeline.

---

## Software Stack

### Core modeling framework

- **COBRApy** (`cobra>=0.30,<1`): The foundational constraint-based modeling package. All other tools in the stack build on or interoperate with COBRApy models. Interfaces solvers through the `optlang` abstraction layer.

### Strain design tools

- **MEWpy** (`mewpy>=1.0,<2`): Metabolic Engineering Workbench. Provides evolutionary algorithm-based strain optimization (GA, SPEA2, NSGA-II/III). Also the home of several phenotype simulation methods that are *not* standalone packages: **MOMA** (Minimization of Metabolic Adjustment), **lMOMA** (linear MOMA), **ROOM** (Regulatory On/Off Minimization), **pFBA**, and **FVA**. Supports both COBRApy and REFRAMED simulation environments.

- **StrainDesign** (`straindesign>=1.15`): MILP-based strain design. Integrates OptKnock, RobustKnock, OptCouple, and the Minimal Cut Sets (MCS) framework. Builds directly on COBRApy. Bundles `efmtool.jar` for elementary flux mode computation via JPype1 — **this is why the devcontainer includes Java 17**. Note: StrainDesign does not expose `__version__` on the module; use `importlib.metadata.version('straindesign')` instead.

- **CFSA** (Comparative Flux Sampling Analysis): Installed from GitLab (`git+https://gitlab.com/wurssb/Modelling/sampling-tools.git`). Not on PyPI. A strain design method based on statistical comparison of sampled flux distributions between growth and production phenotypes. Built on COBRApy's sampling infrastructure. The paper is: "CFSA: Comparative flux sampling analysis as a guide for strain design" (2024).

### Solvers

- **HiGHS** (`highspy>=1.13,<2`): High-performance open-source LP/MIP solver. Integrated with COBRApy through optlang's "hybrid" solver interface (added in COBRApy 0.30). Primary solver for fast LP workloads: FBA, FVA, flux sampling. Set as the solver via `model.solver = 'highs'` or through optlang configuration.

- **SCIP** via **PySCIPOpt** (`pyscipopt>=6.1,<7`): Open-source MILP solver. Used for the hard bilevel optimization problems in StrainDesign (OptKnock, RobustKnock, MCS). Supports indicator constraints, which avoid numerical issues with big-M reformulations. Also usable through COBRApy/optlang, but most relevant as StrainDesign's backend for genome-scale MILPs.

- **GLPK**: Ships with COBRApy by default (via `swiglpk`). Adequate for small models and quick tests, but significantly slower than HiGHS for LP and lacks the MILP capabilities of SCIP for strain design problems.

### Visualization

- **Escher** (`escher>=1.8,<2`): Web-based metabolic pathway map builder and viewer. Renders as a Jupyter widget via ipywidgets. Can overlay flux data, gene expression data, and metabolomics data onto pathway maps. The Jupyter integration requires ipywidgets and Node.js (for JupyterLab extension machinery), both of which are in the devcontainer.

### Jupyter environment

- **JupyterLab** (`jupyterlab>=4.0,<5`), **ipywidgets** (`ipywidgets>=8.1,<9`), **jupyterlab-widgets** (`jupyterlab-widgets>=3.0,<4`). Port 8888 is forwarded in the devcontainer for browser-based access.

### Supporting libraries

- `optlang>=1.8,<2` — solver interface layer (pulled by cobra, pinned for clarity)
- `python-libsbml>=5.20` — SBML model I/O (reading/writing genome-scale models)
- `sympy>=1.12,<2` — symbolic math for inspecting objectives and constraints
- `seaborn>=0.13,<1` — statistical plots, useful for flux sampling distribution comparisons
- `joblib>=1.3,<2` — parallel execution utility (safety net; see parallelism notes below)
- `numpy`, `scipy`, `pandas`, `matplotlib` — standard scientific Python stack

---

## Python Version: 3.12

**Python 3.12** was chosen as the intersection of compatibility across all packages:

| Package | Python support |
|---|---|
| COBRApy 0.30 | 3.9+ |
| MEWpy 1.0 | 3.9+ |
| StrainDesign 1.15+ | >=3.7, tested 3.10–3.12 |
| PySCIPOpt 6.1 | 3.10–3.14, pre-built manylinux wheels |
| highspy 1.13 | 3.10–3.14, pre-built manylinux wheels |
| Escher 1.8 | depends on ipywidgets |
| ipywidgets 8.1 | 3.9–3.13 |

The binding constraint is ipywidgets (officially supports up to 3.13). Python 3.12 is the most battle-tested version with mature wheels everywhere and avoids 3.13 edge cases with Escher's widget rendering.

---

## Base Image: Microsoft Devcontainer Python Image

```
mcr.microsoft.com/devcontainers/python:1-3.12-bookworm
```

We use the Microsoft image rather than `python:3.12-slim` because the primary development environment is VS Code with the Dev Containers extension. The MS image provides a pre-configured `vscode` user, shell integration, and feature layering that are specifically tested against VS Code's remote container workflows. The extra image size is an acceptable trade-off for smoother integration.

---

## Devcontainer Features

- **Node.js LTS**: Required for Escher's JupyterLab extension widget registration.
- **Java 17**: Required by StrainDesign's bundled `efmtool.jar` (elementary flux mode tool), called via JPype1. Without a JRE, StrainDesign throws `JVMNotFoundException` when attempting EFM-based computations.
- **Git**: For installing CFSA from GitLab and general development.

---

## Parallelism and CPU Utilization

The target machine has 48 CPUs. Here is how the stack uses them:

### Already parallelized (use the `processes` parameter or equivalent)

- **COBRApy FVA**: `flux_variability_analysis(model, processes=48)` — solves 2 LPs per reaction across the whole model.
- **COBRApy OptGP sampler**: `cobra.sampling.sample(model, n=10000, processes=48)` — this is what CFSA relies on. Flux sampling is the most CPU-hungry operation in the workflow. On genome-scale models, millions of samples with heavy thinning are typical.
- **COBRApy gene/reaction essentiality**: `find_essential_genes(model, processes=48)`, `single_gene_deletion(model, processes=48)`.
- **MEWpy evolutionary algorithms**: `EA(problem, mp=True)` — parallel fitness evaluation across the population.
- **StrainDesign FVA**: Also supports parallelized computation.

### Inherently single-threaded

- **SCIP** (PySCIPOpt): Branch-and-bound is single-threaded. ParaSCIP/UG exists but is not exposed through the Python interface. This is the solver for OptKnock/RobustKnock/MCS — it solves one large MILP, not many small ones.
- **HiGHS**: Described by its developers as "generally single-threaded." Some components (first-order LP solver, parts of MIP) can use a few threads via `h.setOptionValue("threads", N)`, but speedup is limited.
- **Individual FBA solves**: Single LP, sub-millisecond. Nothing to parallelize.

### Custom parallelism unlikely to be needed

The scenario where you'd need `joblib` — e.g., screening thousands of independent strain designs — doesn't arise naturally in this workflow. StrainDesign formulates one MILP that internally explores the combinatorial knockout space and returns a set of solutions. Validating the resulting 10–20 candidates is a handful of fast FBA solves. The expensive-and-parallelizable operations (FVA, sampling, evolutionary search, essentiality screening) all have built-in multiprocessing support. `joblib` is included as a safety net but is not expected to be a primary tool.

---

## Known Issues and Quirks

- **CFSA is not on PyPI**. Installed via `pip install git+https://gitlab.com/wurssb/Modelling/sampling-tools.git`. If this fails on build, it's likely a minor packaging issue in their repo since they don't list explicit Python version constraints.
- **StrainDesign's `__version__`** is not set on the module. Use `from importlib.metadata import version; version('straindesign')` to query it.
- **StrainDesign needs Java** for EFM computations. If you see `JVMNotFoundException`, the Java feature didn't install correctly — check `java -version` in the container.
- **Solver selection in COBRApy**: COBRApy auto-selects solvers in priority order (Gurobi > CPLEX > GLPK). Since we don't have commercial solvers, it defaults to GLPK unless you explicitly set `model.solver = 'highs'`. You probably want to do this globally early in your notebooks.
- **Version pins use floor-and-ceiling ranges** (e.g., `>=0.30,<1`) rather than exact pins, so patch fixes are picked up automatically. `straindesign>=1.15` resolved to 1.18 at first install.

---

## File Inventory

```
.devcontainer/
├── devcontainer.json    # Container config: MS Python 3.12 image, features, VS Code settings
└── post-create.sh       # Dependency installation, verification, parallelism cheat sheet
```

The post-create script prints a verification table of all installed package versions and a parallelism cheat sheet showing the detected CPU count and relevant API calls.
