FROM mambaorg/micromamba@sha256:e0a99b0f17a759e14c2f967dc0ca2d3a3c1ca3c62955f4d20bba770eaaf0184d AS tools
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /opt/environment.yml
RUN micromamba install -y -n base -f /opt/environment.yml && micromamba clean --all --yes
ARG MAMBA_DOCKERFILE_ACTIVATE=1
RUN npm install --global --prefix /opt/conda @jbrowse/cli@4.3.0 && npm cache clean --force
ENV PATH=/opt/conda/bin:$PATH

FROM tools AS runtime
WORKDIR /opt/quickalign
COPY --chown=$MAMBA_USER:$MAMBA_USER pyproject.toml ./
COPY --chown=$MAMBA_USER:$MAMBA_USER src ./src
COPY --chown=$MAMBA_USER:$MAMBA_USER streamlit_app.py ./
RUN pip install --no-deps --no-build-isolation .
LABEL org.opencontainers.image.title="quickalign" \
      org.opencontainers.image.version="0.1.0" \
      org.quickalign.tools="bwa-mem2=2.3 minimap2=2.31 samtools=1.22.1 htslib=1.22.1 jbrowse=4.3.0 python=3.12.12 streamlit=1.59.2 node=22.23.2"
ENV HOME=/tmp/home XDG_CACHE_HOME=/tmp/cache XDG_CONFIG_HOME=/tmp/config QUICKALIGN_MEMORY=256g
WORKDIR /data
EXPOSE 8501
ENTRYPOINT ["/usr/local/bin/_entrypoint.sh", "quickalign"]
CMD ["--help"]
