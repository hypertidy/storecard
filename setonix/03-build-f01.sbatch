#!/bin/bash
#SBATCH --job-name=pf-build-f01
#SBATCH --partition=copy
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x-%j.out
#
# F01: download one month of OISST, build the six twins and the catalog,
# upload to Pawsey.
#
#   cd setonix && sbatch --account=pawsey1362 03-build-f01.sbatch
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")}"
source ./config.sh
module load "$RCLONE_MODULE"
module load "$PYTHON_MODULE"   # the venv needs the Python it was built with

src="$WORK/src/oisst-$OISST_MONTH"
out="$WORK/out"
mkdir -p "$src" "$out"

# 1. download (skips files already present)
bash ../build/fetch_oisst.sh "$OISST_MONTH" "$src"

# 2. build (stores/ and catalog/ under $out)
rm -rf "$out/stores/f01"* "$out/catalog/f01"
"$VENV/bin/python" -I ../build/build_f01.py "$src" "$out" "$BASE_URL"
"$VENV/bin/python" -I ../build/catalog.py "$out"
cp ../bucket/README.md "$out/README.md"
cp ../bucket/AGENTS.md "$out/AGENTS.md"

# 3. upload
rclone copy "$out" "$PAWSEY_REMOTE:$BUCKET/$PREFIX" --transfers 16 --s3-no-check-bucket --stats-one-line
rclone size "$PAWSEY_REMOTE:$BUCKET/$PREFIX/stores"
echo "== catalog: $BASE_URL/catalog/catalog.json"
