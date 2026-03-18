FROM pytorch/pytorch:2.4.0-cuda12.1-cudnn9-devel

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        git wget \
        libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ── Install Grounded-SAM-2 and its sub-packages ──────────────────────
WORKDIR /opt
RUN git clone https://github.com/IDEA-Research/Grounded-SAM-2.git

WORKDIR /opt/Grounded-SAM-2
RUN pip install --no-cache-dir -e .
RUN pip install --no-cache-dir --no-build-isolation -e grounding_dino

# ── Install remaining Python deps ────────────────────────────────────
RUN pip install --no-cache-dir opencv-python supervision matplotlib

# ── Clone ColonyGroundedSam2 ─────────────────────────────────────────
RUN git clone https://github.com/WFSRDataScience/ColonyGroundedSam2.git /opt/ColonyGroundedSam2

# ── Patch hardcoded checkpoint paths to use /weights mount ───────────
#    Original paths:
#      Grounded-SAM-2-main/checkpoints/sam2_hiera_large.pt
#      checkpoints/colony_gd.pth
#      Grounded-SAM-2-main/grounding_dino/groundingdino/config/GroundingDINO_SwinT_OGC.py
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
