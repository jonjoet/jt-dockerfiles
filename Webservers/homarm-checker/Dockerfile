FROM debian:bookworm-slim AS minimap2-builder

ARG MINIMAP2_VERSION=2.31
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        build-essential \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN curl -fsSL "https://github.com/lh3/minimap2/archive/refs/tags/v${MINIMAP2_VERSION}.tar.gz" \
    | tar -xz --strip-components=1 \
    && make -j"$(nproc)"

FROM python:3.12-slim-bookworm

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY --from=minimap2-builder /build/minimap2 /usr/local/bin/minimap2
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py homarm.py ./
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"

ENTRYPOINT ["python", "-m", "streamlit", "run", "app.py", \
    "--server.port=8501", \
    "--server.address=0.0.0.0", \
    "--server.headless=true", \
    "--browser.gatherUsageStats=false"]
