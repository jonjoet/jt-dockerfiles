FROM pytorch/pytorch:2.4.0-cuda12.1-cudnn9-devel

ENV DEBIAN_FRONTEND=noninteractive
ENV AM_I_DOCKER=True
ENV BUILD_WITH_CUDA=0
ENV TORCH_CUDA_ARCH_LIST="7.0;7.5;8.0;8.6"
ENV CUDA_HOME=/usr/local/cuda-12.1/
ENV PATH=/usr/local/cuda-12.1/bin:${PATH}
ENV LD_LIBRARY_PATH=/usr/local/cuda-12.1/lib64:${LD_LIBRARY_PATH}

RUN apt-get update && apt-get install -y --no-install-recommends \
        git wget ffmpeg \
        libsm6 libxext6 libgl1-mesa-glx libglib2.0-0 \
        ninja-build gcc-10 g++-10 \
    && rm -rf /var/lib/apt/lists/*

ENV CC=gcc-10
ENV CXX=g++-10

# ── Install Grounded-SAM-2 and its sub-packages ──────────────────────
WORKDIR /opt
RUN git clone https://github.com/IDEA-Research/Grounded-SAM-2.git

WORKDIR /opt/Grounded-SAM-2

RUN pip install --no-cache-dir --upgrade pip "setuptools>=62.3.0" wheel numpy \
    opencv-python "transformers<4.49" supervision pycocotools addict yapf timm matplotlib

RUN pip install --no-cache-dir -e .
RUN pip install --no-cache-dir --no-build-isolation -e grounding_dino

# ── Clone ColonyGroundedSam2 ─────────────────────────────────────────
RUN git clone https://github.com/WFSRDataScience/ColonyGroundedSam2.git /opt/ColonyGroundedSam2

# ── Patch hardcoded checkpoint paths to use /weights mount ───────────
RUN sed -i \
    's|"Grounded-SAM-2-main/checkpoints/sam2_hiera_large.pt"|"/weights/sam2_hiera_large.pt"|' \
    /opt/ColonyGroundedSam2/infer.py \
 && sed -i \
    's|"checkpoints/colony_gd.pth"|"/weights/colony_gd.pth"|' \
    /opt/ColonyGroundedSam2/infer.py \
 && sed -i \
    's|"Grounded-SAM-2-main/grounding_dino/groundingdino/config/GroundingDINO_SwinT_OGC.py"|"/opt/Grounded-SAM-2/grounding_dino/groundingdino/config/GroundingDINO_SwinT_OGC.py"|' \
    /opt/ColonyGroundedSam2/infer.py

# grounding_dino internals use "grounding_dino.groundingdino.*" imports
# that resolve only when the Grounded-SAM-2 root is on PYTHONPATH
ENV PYTHONPATH="/opt/Grounded-SAM-2"

WORKDIR /opt/ColonyGroundedSam2

ENTRYPOINT ["python", "infer.py"]
