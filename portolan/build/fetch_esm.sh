#!/bin/bash
# Download one model year of ACCESS-ESM1.6 historical monthly ocean temp
# (about 70 MB), looking its URL up in the virtual store's source table.
#   bash build/fetch_esm.sh 2014 data/esm
set -euo pipefail
year=${1:?YYYY}; dest=${2:?destination dir}
meta="https://data.source.coop/ausantarctic/ausantarctic-scratch/access-esm/access-esm1-6.historical.ocean-3d-temp-1mon-mean/sources.meta.tsv"
url=$(curl -sSf "$meta" | awk -F'\t' -v y="$year" 'NR > 1 && $4 == y {print $3; exit}')
[ -n "$url" ] || { echo "no source for year $year in $meta"; exit 1; }
mkdir -p "$dest"
f="$dest/$(basename "$url")"
[ -s "$f" ] || { curl -sSf --retry 4 --retry-delay 5 -o "$f.part" "$url" && mv "$f.part" "$f"; }
echo "$f"
