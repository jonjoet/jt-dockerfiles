# TDFPS

A containerized wrapper around [TDFPSDesigner](https://github.com/junhaiqi/TDFPSDesigner), a GPU-accelerated barcode design and selection tool for nanopore sequencing. This is not a custom tool — just a Dockerfile packaging the existing TDFPSDesigner software for portable, Nextflow-compatible use.

## Prerequisites

- Docker
- NVIDIA GPU with CUDA support
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

## Build

```bash
docker build -t tdfps .
```

The Dockerfile uses a multi-stage build: CUDA dev image compiles the GPU kernels, then only the runtime libraries are copied into the final image.

## Usage

Run with GPU access:

```bash
docker run --rm -it --gpus all -v $(pwd):/data tdfps
```

This drops you into a bash shell with TDFPSDesigner scripts on PATH. See the [upstream documentation](https://github.com/junhaiqi/TDFPSDesigner) for specific commands.

### Nextflow integration

The container has no fixed entrypoint, making it compatible with Nextflow process definitions:

```groovy
process DESIGN_BARCODES {
    container 'tdfps'
    containerOptions '--gpus all'

    script:
    """
    python3 /opt/TDFPSDesigner/[script].py [args]
    """
}
```

## Files

- `Dockerfile` — Multi-stage build: NVIDIA CUDA 11.8 devel (builder) + runtime, with scipy, numpy, h5py, pandas, edlib, ont-fast5-api, pod5, and TDFPSDesigner compiled from source.
- `README.md` — this file.
