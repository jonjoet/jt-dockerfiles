# ColonyGroundedSAM2 Docker

Docker image for running [ColonyGroundedSAM2](https://github.com/WFSRDataScience/ColonyGroundedSam2) — zero-shot detection and segmentation of bacterial colonies using Grounded SAM2.

Requires an NVIDIA GPU with CUDA support.

## Quick start

### 1. Download model weights

Two checkpoint files are needed (~2.5 GB total). Run the helper script to download them to a local directory:

```bash
./download_weights.sh ./weights
```

This downloads:
- `sam2_hiera_large.pt` — SAM2 backbone checkpoint
- `colony_gd.pth` — fine-tuned Grounding DINO checkpoint for colony detection

### 2. Build the image

```bash
docker build -t colony-gsam2 .
```

### 3. Run inference

```bash
docker run --gpus all \
    -v /path/to/weights:/weights:ro \
    -v /path/to/input/images:/data:ro \
    -v /path/to/output:/output \
    colony-gsam2 \
    --data_path /data --out_path /output
```

Replace `/path/to/weights`, `/path/to/input/images`, and `/path/to/output` with actual paths on your host.

### Optional arguments

| Argument | Default | Description |
|---|---|---|
| `--crop_coords` | `None` | Crop coordinates (`x1 y1 x2 y2`) applied to input images |
| `--box_threshold` | `0.25` | Confidence threshold for bounding box detection |
| `--text_threshold` | `0.25` | Confidence threshold for text grounding |

Example with thresholds:

```bash
docker run --gpus all \
    -v ./weights:/weights:ro \
    -v ./images:/data:ro \
    -v ./results:/output \
    colony-gsam2 \
    --data_path /data --out_path /output \
    --box_threshold 0.3 --text_threshold 0.3
```

## Output

The tool saves annotated images (with mask overlays) to the output directory, prefixed with `annotated_`.
