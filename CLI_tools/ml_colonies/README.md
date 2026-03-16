# Colony Counting — Docker Image

Docker image for running [automatical-colony-counting](https://github.com/daimaku1/automatical-colony-counting/tree/master) inference on any CUDA-capable machine.

## Build

```bash
docker build -t colony-counting .
```

## Download model weights

Weights are available on Kaggle:
https://www.kaggle.com/datasets/clb2256095392/automatic-colony-counting

Download and place the three `.pth` files into this directory structure:

```
weights/
├── u2net/
│   ├── model_Circle_preformance.pth   # U2-Net for petri dish edge detection
│   └── model_best_direct_1_10.pth     # U2-Net for colony segmentation
└── ResNet/
    └── resnet_50_new.pth              # ResNet-50 colony classifier
```

You can use the Kaggle CLI:
```bash
pip install kaggle
kaggle datasets download -d clb2256095392/automatic-colony-counting
unzip automatic-colony-counting.zip -d weights_download

# Then arrange files into the structure above.
# Check the downloaded archive for the exact file layout and copy accordingly:
mkdir -p weights/u2net weights/ResNet
# cp weights_download/<path>/model_Circle_preformance.pth weights/u2net/
# cp weights_download/<path>/model_best_direct_1_10.pth   weights/u2net/
# cp weights_download/<path>/resnet_50_new.pth            weights/ResNet/
```

## Run inference

Put your colony plate images (`.jpg` or `.png`) in the current directory, then
point `-v` at your weights drive and use `$(pwd)` for images and output:

```bash
docker run --rm --gpus all \
    -v /path/to/your/weights:/app/repo/ColonyCounting/weights:ro \
    -v $(pwd):/app/repo/ColonyCounting/Inferences/image:ro \
    -v $(pwd)/output:/app/repo/ColonyCounting/Inferences/predict_res \
    colony-counting
```

For example, if your weights live on an external drive at
`/mnt/external_ssd/colony_weights` and you have plate photos in `~/plates`:

```bash
cd ~/plates
mkdir -p output

docker run --rm --gpus all \
    -v /mnt/external_ssd/colony_weights:/app/repo/ColonyCounting/weights:ro \
    -v $(pwd):/app/repo/ColonyCounting/Inferences/image:ro \
    -v $(pwd)/output:/app/repo/ColonyCounting/Inferences/predict_res \
    colony-counting
```

Results appear in `./output/exp_0/`, `./output/exp_1/`, etc. (auto-incrementing).

### Volume mapping reference

| Host path | Container path | Purpose |
|---|---|---|
| `/path/to/weights/` | `/app/repo/ColonyCounting/weights/` | Model weight files (read-only) |
| `$(pwd)` (your images) | `/app/repo/ColonyCounting/Inferences/image/` | Input plate images (read-only) |
| `$(pwd)/output` | `/app/repo/ColonyCounting/Inferences/predict_res/` | Inference results (read-write) |

### GPU / CPU behavior

The Dockerfile patches `final_predict.py` to auto-detect CUDA:
- With `--gpus all` and a CUDA-capable GPU: runs on GPU
- Without `--gpus`: falls back to CPU automatically

To run CPU-only intentionally, just drop the `--gpus all` flag.

## Pipeline overview

1. **Edge removal** — U2-Net model 1 detects the petri dish circle and masks it out
2. **Colony segmentation** — U2-Net model 2 segments individual colonies
3. **Classification** — ResNet-50 classifies each colony segment (10 classes: 0-9)
4. **Output** — Segmented colony images saved with predicted class in filename

## Notes

- No GUI required — the image uses `opencv-python-headless` and all display calls are disabled
- Python 3.9, PyTorch 1.10, CUDA 11.3 (matching the original repo's environment)
- The Dockerfile also fixes a hardcoded Windows path in `resnet__50/pred_api.py`
