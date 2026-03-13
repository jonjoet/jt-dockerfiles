FROM python:3.12-slim

# ── System dependencies ────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    # R
    r-base r-base-dev \
    # Quarto / pandoc deps
    curl wget gdebi-core \
    # Common R package compilation deps
    libcurl4-openssl-dev libssl-dev libxml2-dev \
    libfontconfig1-dev libharfbuzz-dev libfribidi-dev \
    libfreetype6-dev libpng-dev \
    libtiff5-dev libjpeg-dev \
    # Git (useful in devcontainers)
    git \
    && rm -rf /var/lib/apt/lists/*

# ── Quarto ─────────────────────────────────────────────────────────────────────
# Pin version for reproducibility — check https://github.com/quarto-dev/quarto-cli/releases
ARG QUARTO_VERSION=1.5.57
RUN wget -q https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-amd64.deb \
    && dpkg -i quarto-${QUARTO_VERSION}-linux-amd64.deb \
    && rm quarto-${QUARTO_VERSION}-linux-amd64.deb

# ── Python environment ─────────────────────────────────────────────────────────
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── R: renv bootstrap ──────────────────────────────────────────────────────────
# Install renv globally so it's available before the project is mounted
RUN Rscript -e "install.packages('renv', repos='https://cloud.r-project.org')"

# Install packages from renv.lock (copied in at build time)
COPY renv.lock /tmp/renv.lock
RUN Rscript -e " \
    options(renv.config.pak.enabled = FALSE); \
    renv::restore(lockfile = '/tmp/renv.lock', library = .libPaths()[1]) \
"

# Register IRkernel so Jupyter can use R
RUN Rscript -e "IRkernel::installspec(user = FALSE)"

# ── Tell reticulate which Python to use ────────────────────────────────────────
ENV RETICULATE_PYTHON=/usr/local/bin/python

# ── Working directory ──────────────────────────────────────────────────────────
WORKDIR /workspace
