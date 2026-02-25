# TDFPSDesigner - Barcode design and selection for nanopore sequencing
# https://github.com/junhaiqi/TDFPSDesigner
# Nextflow compatible container with multi-stage build for smaller image

# Stage 1: Build CUDA code
FROM nvidia/cuda:11.8.0-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    python3 \
    python3-pip \
    python3-dev \
    libhdf5-dev \
    libhdf5-serial-dev \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/bin/python
RUN pip3 install --no-cache-dir --upgrade pip setuptools wheel

WORKDIR /opt
RUN git clone --recursive https://github.com/junhaiqi/TDFPSDesigner.git

# Compile CUDA programs
WORKDIR /opt/TDFPSDesigner
RUN bash compile.sh

# Stage 2: Runtime image
FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04

LABEL maintainer="JT"
LABEL description="TDFPSDesigner - barcode design and selection for nanopore sequencing"
LABEL version="0.1.0"

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    libhdf5-103 \
    libzstd1 \
    zlib1g \
    libbz2-1.0 \
    libgomp1 \
    procps \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/bin/python
RUN pip3 install --no-cache-dir --upgrade pip setuptools wheel

# Install Python dependencies
RUN pip3 install --no-cache-dir \
    scipy \
    numpy \
    h5py \
    pandas \
    edlib \
    ont-fast5-api \
    pod5 \
    pyslow5 \
    matplotlib \
    scikit-learn

# Copy compiled binaries from builder
COPY --from=builder /opt/TDFPSDesigner /opt/TDFPSDesigner

# Make Python scripts and binaries executable
RUN chmod +x /opt/TDFPSDesigner/*.py && \
    chmod -R +x /opt/TDFPSDesigner/bin/

WORKDIR /opt/TDFPSDesigner
ENV PATH="/opt/TDFPSDesigner:${PATH}"

# Add shebang to Python scripts if missing
RUN for f in /opt/TDFPSDesigner/*.py; do \
    if ! head -1 "$f" | grep -q '^#!'; then \
        sed -i '1i#!/usr/bin/env python3' "$f"; \
    fi; \
    done

# Nextflow compatible - no fixed entrypoint
CMD ["/bin/bash"]
