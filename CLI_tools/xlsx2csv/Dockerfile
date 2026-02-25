FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    procps \
    bash \
    && pip install xlsx2csv --break-system-packages \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["/bin/bash"]