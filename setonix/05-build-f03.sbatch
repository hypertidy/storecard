#!/bin/bash
#SBATCH --job-name=pf-build-f03
#SBATCH --partition=copy
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x-%j.out
#
# F03: download a week of Bremen ASI AMSR2 (3.125 km, south) and the same week
# of NOAA/NSIDC G02202 v6 (25 km, south and north), build the F03 twins,
# rebuild the root catalog (keeps F01),
# upload to Pawsey.
#
#   cd setonix && sbatch --account=pawsey1362 05-build-f03.sbatch
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")}"
source ./config.sh
module load "$RCLONE_MODULE"
module load "$PYTHON_MODULE"   # the venv needs the Python it was built with

src="$WORK/src/asi-$ASI_START-$ASI_DAYS"
out="$WORK/out"
mkdir -p "$src" "$out"

gs="$WORK/src/g02202-south-$ASI_START-$ASI_DAYS"
gn="$WORK/src/g02202-north-$ASI_START-$ASI_DAYS"

# 1. download (skips files already present)
bash ../build/fetch_asi.sh "$ASI_START" "$ASI_DAYS" "$src"
bash ../build/fetch_g02202.sh south "$ASI_START" "$ASI_DAYS" "$gs"
bash ../build/fetch_g02202.sh north "$ASI_START" "$ASI_DAYS" "$gn"

# 2. build (stores/ and catalog/ under $out)
rm -rf "$out/stores/f03"* "$out/catalog/f03"
"$VENV/bin/python" -I ../build/build_f03.py "$src" "$out" "$BASE_URL"
"$VENV/bin/python" -I ../build/build_f03g.py "$gs" "$out" "$BASE_URL" south
"$VENV/bin/python" -I ../build/build_f03g.py "$gn" "$out" "$BASE_URL" north
"$VENV/bin/python" -I ../build/catalog.py "$out"
cp ../bucket/README.md "$out/README.md"
cp ../bucket/AGENTS.md "$out/AGENTS.md"

# 3. upload
rclone copy "$out" "$PAWSEY_REMOTE:$BUCKET/$PREFIX" --transfers 16 --s3-no-check-bucket --stats-one-line
rclone size "$PAWSEY_REMOTE:$BUCKET/$PREFIX/stores" --include "f03*/**"
echo "== catalog: $BASE_URL/catalog/catalog.json"
