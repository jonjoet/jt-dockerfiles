FROM python:3.10-slim

LABEL maintainer="JT"
LABEL description="PRO DNA barcode designer for nanopore sequencing - Nextflow ready"
LABEL version="1.0"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    edlib==1.3.9 \
    tqdm

# Clone PRO repository
RUN git clone https://github.com/rztongr/PRO.git /opt/PRO

# Make scripts executable
RUN chmod +x /opt/PRO/*.sh /opt/PRO/*.py

# Add PRO to PATH and module to PYTHONPATH
ENV PATH="/opt/PRO:${PATH}"
ENV PYTHONPATH="/opt/PRO/module/pro_divergence:/opt/PRO/module/add_error:/opt/PRO/module/Pre_processing"

# Set working directory to PRO for relative path resolution
WORKDIR /opt/PRO

# Default entrypoint for Nextflow compatibility
ENTRYPOINT []
CMD ["/bin/bash"]
