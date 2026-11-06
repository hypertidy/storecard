#!/bin/bash
# Download one month of final OISST v2.1 daily files from NCEI (about 1.5 MB each).
#   bash build/fetch_oisst.sh 202501 data/oisst-202501
set -euo pipefail
month=${1:?YYYYMM}; dest=${2:?destination dir}
url="https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr/$month"
mkdir -p "$dest"
y=${month:0:4}; m=${month:4:2}
ndays=$(python3 -c "import calendar; print(calendar.monthrange($y, int('$m'))[1])")
for d in $(seq -w 1 "$ndays"); do
  f="oisst-avhrr-v02r01.${month}${d}.nc"
  [ -s "$dest/$f" ] && continue
  curl -sSf --retry 4 --retry-delay 5 -o "$dest/$f.part" "$url/$f" && mv "$dest/$f.part" "$dest/$f"
done
echo "$(ls "$dest" | wc -l) files in $dest"
