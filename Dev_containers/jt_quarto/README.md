# jt_quarto

A devcontainer for data analysis in R with Quarto for literate programming, plus Python available via reticulate for mixed-language workflows.

## What's inside

Based on the [rocker tidyverse](https://rocker-project.org/) devcontainer image (`ghcr.io/rocker-org/devcontainer/tidyverse:4`), which includes R 4.x, the tidyverse, and common system libraries.

### Added features

| Component | Description |
|---|---|
| **Quarto CLI** | Literate programming / reproducible documents (`.qmd` rendering to HTML, PDF, etc.) |
| **reticulate** | Call Python from R seamlessly |
| **httpgd** | Modern graphics device for VS Code R plot viewing |
| **languageserver** | R LSP for autocompletion and diagnostics in VS Code |
| **Python venv** | Virtual environment at `/home/rstudio/.venv` with jupyter, numpy, pandas, matplotlib |

### VS Code extensions (auto-installed)

- R language support
- Quarto
- Python

## Usage

Open the folder containing this `devcontainer.json` in VS Code with the Dev Containers extension. The container pulls the rocker image and installs features automatically.

Shared data is mounted at `share_data2/` within the workspace.

### Using Python from R

```r
library(reticulate)
use_virtualenv("/home/rstudio/.venv")
pd <- import("pandas")
```

## Files

- `devcontainer.json` — Full devcontainer specification (image, features, mounts, extensions, settings).
- `README.md` — this file.
