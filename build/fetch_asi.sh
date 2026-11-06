#!/bin/bash
# Download consecutive days of Bremen ASI AMSR2 v5.4 3.125 km southern
# hemisphere netCDF files (a few MB each).
#   bash build/fetch_asi.sh 20250915 7 data/asi-20250915
set -euo pipefail
start=${1:?YYYYMMDD}; ndays=${2:?number of days}; dest=${3:?destination dir}
base="https://data.seaice.uni-bremen.de/amsr2/asi_daygrid_swath/s3125/netcdf"
mkdir -p "$dest"
for d in $(python3 -c "
import datetime as dt
s = dt.datetime.strptime('$start', '%Y%m%d')
print(' '.join((s + dt.timedelta(days=i)).strftime('%Y%m%d') for i in range($ndays)))"); do
  f="asi-AMSR2-s3125-${d}-v5.4.nc"
  [ -s "$dest/$f" ] && continue
  curl -sSf --retry 4 --retry-delay 5 -o "$dest/$f.part" "$base/${d:0:4}/$f" && mv "$dest/$f.part" "$dest/$f" \
    || echo "missing: $f"
done
echo "$(ls "$dest"/*.nc 2>/dev/null | wc -l) files in $dest"
