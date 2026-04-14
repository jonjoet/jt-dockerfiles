FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

COPY vendor/ /app/vendor/
RUN pip install --no-cache-dir /app/vendor/Escher-1.7.3.tar.gz

COPY pyproject.toml /app/
COPY src/ /app/src/

RUN pip install --no-cache-dir /app

WORKDIR /data

ENTRYPOINT ["escher-cli"]
