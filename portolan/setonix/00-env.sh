#!/bin/bash
# Run once on a Setonix login node: create the Python venv the jobs use.
set -euo pipefail
source "$(dirname "$0")/config.sh"

module load "$PYTHON_MODULE"
python3 --version
case "$(python3 -c 'import sys; print(sys.version_info >= (3, 10))')" in
  True) ;; *) echo "need python >= 3.10, got $(python3 --version)"; exit 1 ;;
esac

want=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
have=$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo none)
if [ "$have" != "$want" ]; then
  echo "venv python is $have, module python is $want: rebuilding $VENV"
  rm -rf "$VENV"
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
# the builders' needs live in ../requirements.txt; awscli is only for 01-bucket-setup.sh
"$VENV/bin/pip" install -q -r "$(dirname "$0")/../requirements.txt" awscli
"$VENV/bin/python" -c "import zarr, xarray, pyproj, scipy; print('zarr', zarr.__version__, 'xarray', xarray.__version__, 'scipy', scipy.__version__)"
module load "$RCLONE_MODULE" && rclone version | head -1
echo "== can the keys see the bucket?"
rclone lsd "$PAWSEY_REMOTE:" | grep -w "$BUCKET" || echo "!! $BUCKET not visible with profile $AWS_PROFILE"
echo "venv ready: $VENV"
