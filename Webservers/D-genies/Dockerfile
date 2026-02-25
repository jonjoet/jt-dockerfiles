# Use a stable Python version (avoid 3.14 for now)
FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install specific compatible versions of Flask/Jinja/MarkupSafe
# then install dgenies
RUN pip install --no-cache-dir \
    "MarkupSafe<2.1.0" \
    "Flask<2.3.0" \
    "Werkzeug<3.0.0" \
    "Jinja2<3.1.0" \
    dgenies


CMD ["dgenies", "run", "--host", "0.0.0.0"]
