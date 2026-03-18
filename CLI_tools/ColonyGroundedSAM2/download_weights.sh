#!/usr/bin/env bash
# Downloads the two model checkpoints needed by ColonyGroundedSAM2.
# Usage: ./download_weights.sh [TARGET_DIR]
#   TARGET_DIR defaults to ./weights

set -euo pipefail

DIR="${1:-./weights}"
mkdir -p "$DIR"

echo "Downloading SAM2 checkpoint..."
wget -q --show-progress -O "$DIR/sam2_hiera_large.pt" \
    "https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_large.pt"

echo "Downloading Colony Grounding DINO checkpoint..."
wget -q --show-progress -O "$DIR/colony_gd.pth" \
    "https://huggingface.co/DataScienceWFSR/ColonyGroundedSAM2/resolve/main/checkpoints/colony_gd.pth"

echo "Done. Weights saved to: $DIR"
