# Dockerized CLI. Only prerequisite on the host is Docker itself.
#
#   docker build -t treejson2xlsx .
#   docker run --rm -v "$(pwd):/data" treejson2xlsx /data/treeResults.json -o /data/routes.xlsx --reactions
#
# Anything after the image name is passed straight to the converter CLI.
# Runs fully offline; do NOT pass --online for proprietary structures.
FROM python:3.12-slim

# RDKit's Cairo drawing (route/structure images) needs these shared libs at runtime.
# libexpat1 provides libexpat.so.1, pulled in by Cairo/Pango during PNG rendering.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxrender1 libxext6 libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY treejson_to_xlsx.py .

ENTRYPOINT ["python", "treejson_to_xlsx.py"]
