# ============================================================
# automatical-colony-counting — CUDA inference image
# ============================================================
# Base: NVIDIA CUDA 11.3 + cuDNN 8, Ubuntu 20.04
# PyTorch 1.10 (matches the repo's requirements.txt)
# Python 3.9  (matches the repo's .idea/misc.xml)
# ============================================================

FROM nvidia/cuda:11.3.1-cudnn8-runtime-ubuntu20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# ---- system deps ----
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.9 python3.9-dev python3.9-venv python3-pip \
        libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender1 \
        git wget \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.9 1 \
    && update-alternatives --install /usr/bin/python  python  /usr/bin/python3.9 1 \
    && python -m pip install --upgrade pip setuptools wheel \
    && rm -rf /var/lib/apt/lists/*

# ---- python deps ----
# Pin versions to match the repo; allow compatible CUDA wheels
RUN pip install --no-cache-dir \
        torch==1.10.0+cu113 \
        torchvision==0.11.1+cu113 \
        -f https://download.pytorch.org/whl/cu113/torch_stable.html \
    && pip install --no-cache-dir \
        numpy==1.22.0 \
        opencv-python-headless==4.5.4.60 \
        scikit-image \
        scikit-learn \
        scipy \
        Pillow \
        matplotlib \
        tqdm \
        imgviz \
        pycocotools \
        tensorboard \
        lxml \
        Shapely

# ---- application code ----
WORKDIR /app

# Clone the repo (master branch)
RUN git clone --branch master --depth 1 \
        https://github.com/daimaku1/automatical-colony-counting.git /app/repo

# Fix the hardcoded Windows path for class_indices.json in resnet pred_api.py
# so it resolves relative to the resnet__50 directory at runtime.
RUN sed -i "s|json_path = r'F:\\\\final_version.*class_indices.json'|json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'class_indices.json')|" \
        /app/repo/ColonyCounting/model_src/resnet__50/pred_api.py

# Patch final_predict.py to use CUDA when available instead of hardcoded CPU
RUN sed -i "s|device = torch.device('cpu')|device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')|" \
        /app/repo/ColonyCounting/final_predict.py

# Fix hardcoded Windows path for input image directory
RUN sed -i "s|infer_dir = r'E:\\\\Desktop\\\\testout'|infer_dir = './Inferences'|" \
        /app/repo/ColonyCounting/final_predict.py

# Ensure the weights directory structure exists (user mounts weights here)
RUN mkdir -p /app/repo/ColonyCounting/weights/u2net \
             /app/repo/ColonyCounting/weights/ResNet \
             /app/repo/ColonyCounting/Inferences/predict_res

WORKDIR /app/repo/ColonyCounting

# ---- default entrypoint ----
# Run inference via final_predict.py.
# Users override infer_dir / exps_dir / device via env vars or by
# bind-mounting their own images into the container.
ENTRYPOINT ["python", "final_predict.py"]
