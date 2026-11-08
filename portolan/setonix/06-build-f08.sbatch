#!/bin/bash
#SBATCH --job-name=pf-build-f08
#SBATCH --partition=copy
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x-%j.out
#
# F08: download one model year of ACCESS-ESM1.6 ocean temp (tripolar MOM5),
# build the F08 twins, relink the catalog,
# upload to Pawsey.
#
#   cd setonix && sbatch --account=pawsey1362 06-build-f08.sbatch
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")}"
source ./config.sh
module load "$RCLONE_MODULE"
module load "$PYTHON_MODULE"   # the venv needs the Python it was built with

out="$WORK/out"
mkdir -p "$out"

# 1. download one yearly file and the geolon_t/geolat_t fixed fields (skips if present)
mapfile -t srcfiles < <(bash ../build/fetch_esm.sh "$ESM_YEAR" "$WORK/src/esm")

# 2. build
rm -rf "$out/stores/f08"* "$out/catalog/f08"
"$VENV/bin/python" -I ../build/build_f08.py "${srcfiles[0]}" "$out" "$BASE_URL" "${srcfiles[@]:1}"
"$VENV/bin/python" -I ../build/catalog.py "$out"
cp ../bucket/README.md "$out/README.md"
cp ../bucket/AGENTS.md "$out/AGENTS.md"

# 3. upload
rclone copy "$out" "$PAWSEY_REMOTE:$BUCKET/$PREFIX" --transfers 16 --s3-no-check-bucket --stats-one-line
rclone size "$PAWSEY_REMOTE:$BUCKET/$PREFIX/stores" --include "f08*/**"
echo "== catalog: $BASE_URL/catalog/catalog.json"
