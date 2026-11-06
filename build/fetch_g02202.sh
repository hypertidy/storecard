#!/bin/bash
# Download consecutive days of NOAA/NSIDC G02202 v6 daily sea ice files
# (about 0.4 MB each). The sensor code is part of the file name; AMSR2
# ("am2") covers recent years.
#   bash build/fetch_g02202.sh south 20250915 7 data/g02202-south [am2]
set -euo pipefail
hem=${1:?south|north}; start=${2:?YYYYMMDD}; ndays=${3:?days}; dest=${4:?dir}; sensor=${5:-am2}
case "$hem" in south) p=sic_pss25 ;; north) p=sic_psn25 ;; *) echo "hem must be south or north"; exit 1 ;; esac
base="https://noaadata.apps.nsidc.org/NOAA/G02202_V6/$hem/daily"
mkdir -p "$dest"
for d in $(python3 -c "
import datetime as dt
s = dt.datetime.strptime('$start', '%Y%m%d')
print(' '.join((s + dt.timedelta(days=i)).strftime('%Y%m%d') for i in range($ndays)))"); do
  f="${p}_${d}_${sensor}_v06r00.nc"
  [ -s "$dest/$f" ] && continue
  curl -sSf --retry 4 --retry-delay 5 -o "$dest/$f.part" "$base/${d:0:4}/$f" && mv "$dest/$f.part" "$dest/$f" \
    || echo "missing: $f"
done
echo "$(ls "$dest"/*.nc 2>/dev/null | wc -l) files in $dest"
