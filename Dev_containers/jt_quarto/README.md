# Quarto R + Python Devcontainer

A reproducible VSCode devcontainer for data analysis with Quarto, mixing R and Python in the same notebooks.

## What's included

| Layer | Tool | Purpose |
|---|---|---|
| Notebooks | Quarto `.qmd` | Prose + code, renders to HTML/PDF/slides |
| Python | pip + `requirements.txt` | pandas, seaborn, scipy, jupyter |
| R | renv + `renv.lock` | ggplot2, dplyr, tidyr, broom |
| Bridge | reticulate + IRkernel | Share objects between R and Python chunks |

## Getting started

1. **Prerequisites:** Docker + VSCode + the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

2. **Open in container:**
   ```
   Cmd/Ctrl+Shift+P → "Dev Containers: Reopen in Container"
   ```
   First build takes a few minutes (installs R packages etc.).

3. **Render the example notebook:**
   ```bash
   quarto render example.qmd
   ```
   Or use the Quarto VSCode extension's preview button.

## Adding packages

**Python:**
```bash
pip install somepackage
pip freeze > requirements.txt   # commit the updated lockfile
```

**R:**
```r
renv::install("somepackage")
renv::snapshot()                 # updates renv.lock — commit this
```

## How R ↔ Python interop works

In a `.qmd` file, Python objects are accessible in R via `reticulate::py$`:

````markdown
```{python}
df = pd.DataFrame(...)
```

```{r}
df_r <- reticulate::py$df
```
````

And R objects are accessible in Python via the `r` module:

````markdown
```{r}
result <- some_r_function()
```

```{python}
import r
print(r.result)
```
````

## Gotchas

- **reticulate Python path** is set via `ENV RETICULATE_PYTHON` in the Dockerfile. If you change the Python version, update that too.
- **renv.lock hashes** are validated on restore — if you manually edit the lockfile, run `renv::snapshot()` to regenerate correct hashes.
- **Quarto version** is pinned via `ARG QUARTO_VERSION` in the Dockerfile. Update it deliberately, not automatically.
- R factors come through to Python as pandas `Categorical` — usually fine, but worth knowing.
