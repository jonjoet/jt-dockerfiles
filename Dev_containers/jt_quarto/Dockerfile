FROM rocker/verse:4.4.0

# ── Python ────────────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# ── Python virtual environment + packages ────────────────────────────────────
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── Additional R packages via renv ───────────────────────────────────────────
RUN Rscript -e "install.packages('renv', repos='https://cloud.r-project.org')"

COPY renv.lock /tmp/renv.lock
RUN Rscript -e " \
    options(renv.config.pak.enabled = FALSE); \
    renv::restore(lockfile = '/tmp/renv.lock', library = .libPaths()[1]) \
"

# ── Register IRkernel for Jupyter ────────────────────────────────────────────
# Symlink jupyter into a standard bin so R's system2() can find it
RUN ln -s /opt/venv/bin/jupyter /usr/local/bin/jupyter
RUN Rscript -e "IRkernel::installspec(user = FALSE)"

# ── Tell reticulate which Python to use ──────────────────────────────────────
ENV RETICULATE_PYTHON=/opt/venv/bin/python

# ── Working directory ────────────────────────────────────────────────────────
WORKDIR /workspace
