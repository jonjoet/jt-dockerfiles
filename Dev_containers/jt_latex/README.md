# LaTeX Dev Container

A devcontainer for writing LaTeX documents with LuaLaTeX or pdfLaTeX, using the full TeX Live distribution.

## Prerequisites

- Docker
- VS Code with the [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) extension

## Usage

1. Open this folder in VS Code.
2. When prompted, click **Reopen in Container** (or run the command **Dev Containers: Reopen in Container** from the command palette).
3. VS Code will pull the `texlive/texlive:latest` image and install extensions automatically.

## Included Extensions

- **LaTeX Workshop** — build, preview, and navigate LaTeX documents
- **LaTeX Utilities** — extra features like live snippets and formatted paste
- **Code Spell Checker** — spell checking for LaTeX source files

## Build Recipes

Two recipes are preconfigured in LaTeX Workshop:

- **latexmk (lualatex)** — default, uses `latexmk -lualatex`
- **latexmk (pdflatex)** — uses `latexmk -pdf`

To switch recipes, use the LaTeX Workshop sidebar or change `latex-workshop.latex.recipe.default` in settings.

## Examples

The `examples/` folder contains a sample `main.tex` and `references.bib` to verify the setup is working.
