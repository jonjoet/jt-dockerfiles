#!/usr/bin/env bash
set -euo pipefail

echo "==> Upgrading pip and core build tools"
python -m pip install --upgrade pip setuptools wheel

# ---------------------------------------------------------------------------
# Solvers
# ---------------------------------------------------------------------------
echo "==> Installing LP/MILP solvers"

# HiGHS: high-performance LP/MIP solver (used by COBRApy via optlang hybrid interface)
pip install "highspy>=1.13,<2"

# SCIP via PySCIPOpt: MILP solver for bilevel optimization & StrainDesign
pip install "pyscipopt>=6.1,<7"

# ---------------------------------------------------------------------------
# Core scientific stack
# ---------------------------------------------------------------------------
echo "==> Installing scientific Python stack"
pip install "numpy>=1.26,<3"
pip install "scipy>=1.12,<2"
pip install "pandas>=2.1,<3"
pip install "matplotlib>=3.8,<4"

# ---------------------------------------------------------------------------
# Constraint-based modeling: COBRApy
# ---------------------------------------------------------------------------
echo "==> Installing COBRApy"
pip install "cobra>=0.30,<1"

# ---------------------------------------------------------------------------
# Strain design & simulation tools
# ---------------------------------------------------------------------------
echo "==> Installing MEWpy (includes MOMA, lMOMA, ROOM, pFBA, FVA)"
pip install "mewpy>=1.0,<2"

echo "==> Installing StrainDesign (OptKnock, RobustKnock, OptCouple, MCS)"
# StrainDesign bundles efmtool.jar and uses JPype1 to call it — requires Java,
# which is provided by the devcontainer java feature.
pip install "straindesign>=1.15"

echo "==> Installing CFSA (Comparative Flux Sampling Analysis) from GitLab"
pip install "git+https://gitlab.com/wurssb/Modelling/sampling-tools.git"

# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------
echo "==> Installing Escher for metabolic map visualization"
pip install "escher>=1.8,<2"

# ---------------------------------------------------------------------------
# Jupyter environment
# ---------------------------------------------------------------------------
echo "==> Installing Jupyter environment"
pip install "jupyterlab>=4.0,<5"
pip install "ipywidgets>=8.1,<9"
pip install "jupyterlab-widgets>=3.0,<4"

# ---------------------------------------------------------------------------
# Supporting libraries
# ---------------------------------------------------------------------------
echo "==> Installing supporting libraries"
pip install "optlang>=1.8,<2"       # solver interface layer (pulled by cobra, pinned for clarity)
pip install "python-libsbml>=5.20"  # SBML model I/O
pip install "sympy>=1.12,<2"        # symbolic math
pip install "seaborn>=0.13,<1"      # statistical plots (useful for flux sampling comparisons)
pip install "joblib>=1.3,<2"        # parallelism for embarrassingly parallel workloads (knockout screens, etc.)

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
echo ""
echo "==> Verifying key packages"
python -c "
import cobra;        print(f'  COBRApy      {cobra.__version__}')
import mewpy;        print(f'  MEWpy        {mewpy.__version__}')
import straindesign; print(f'  StrainDesign {straindesign.__version__}')
import pyscipopt;    print(f'  PySCIPOpt    {pyscipopt.__version__}')
import highspy;      print(f'  HiGHS        {highspy.__version__}')
import escher;       print(f'  Escher       {escher.__version__}')
import joblib;       print(f'  joblib       {joblib.__version__}')
"

echo ""
echo "==> Parallelism cheat sheet for this machine:"
python -c "
import os
n = os.cpu_count()
print(f'  Detected {n} CPUs.')
print(f'  COBRApy FVA:        flux_variability_analysis(model, processes={n})')
print(f'  COBRApy sampling:   cobra.sampling.sample(model, n=10000, processes={n})')
print(f'  MEWpy EA:           EA(problem, mp=True)')
print(f'  joblib (general):   Parallel(n_jobs={n})(delayed(fn)(x) for x in items)')
"

echo "==> Done."
