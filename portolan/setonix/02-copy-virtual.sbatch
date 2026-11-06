#!/bin/bash
#SBATCH --job-name=pf-copy-virtual
#SBATCH --partition=copy
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
#
# Copy the index-only virtual stores from source.coop to Pawsey, as is.
# Only the indexes move: their references still point at the upstream hosts.
#
#   cd setonix && sbatch --account=pawsey1362 02-copy-virtual.sbatch
#   DRY=1 sbatch ...   (rclone --dry-run)
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")}"
source ./config.sh
module load "$RCLONE_MODULE"
module load "$PYTHON_MODULE"   # the venv needs the Python it was built with
command -v rclone >/dev/null || { echo "rclone not found"; exit 1; }

opts=(--transfers 16 --checkers 32 --s3-no-check-bucket --fast-list --stats 60s --stats-one-line)
[ "${DRY:-0}" = 1 ] && opts+=(--dry-run)

for src in "${VIRTUAL_STORES[@]}"; do
  name=$(basename "$src")
  dst="$PAWSEY_REMOTE:$BUCKET/$PREFIX/virtual/$name"
  echo "== $SRC_ACCOUNT/$src -> $dst"
  rclone copy "srccoop:$SRC_ACCOUNT/$src" "$dst" "${opts[@]}" \
    --include "kerchunk/**" --include "icechunk/**" --include "flat/**" \
    --include "mdim.vrt" --include "thumbnail.png" --include "stac/collection.json"
  rclone size "$dst" 2>/dev/null || true
done
echo "== done $(date -u +%FT%TZ)"
