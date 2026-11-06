#!/bin/bash
# Cross-origin checks from the command line: for each URL, a GET with an
# Origin header and a byte Range, then report status and CORS headers.
# 206 + access-control-allow-origin = a browser can range-read it.
#
#   bash 04-verify.sh
set -uo pipefail
cd "$(dirname "$0")"
source ./config.sh
ORIGIN="https://example.org"

check() {
  local url=$1
  local hdr
  hdr=$(curl -s -o /dev/null -D - -m 30 -H "Origin: $ORIGIN" -H "Range: bytes=0-99" "$url")
  local code; code=$(printf '%s' "$hdr" | awk 'toupper($1) ~ /^HTTP/ {c=$2} END {print c}')
  local acao; acao=$(printf '%s' "$hdr" | grep -i '^access-control-allow-origin' | tr -d '\r' | cut -d' ' -f2-)
  local aceh; aceh=$(printf '%s' "$hdr" | grep -i '^access-control-expose-headers' | tr -d '\r' | cut -d' ' -f2-)
  printf '%-4s acao=%-4s expose=%-30s %s\n' "${code:-ERR}" "${acao:--}" "${aceh:--}" "$url"
}

echo "== Pawsey: built fixtures"
check "$BASE_URL/catalog/catalog.json"
check "$BASE_URL/stores/f01b-oisst-ydesc.zarr/zarr.json"
check "$BASE_URL/stores/f01b-oisst-ydesc.zarr/sst/zarr.json"
check "$BASE_URL/stores/f01b-oisst-ydesc.zarr/sst/c/0/0/0/0"
check "$BASE_URL/stores/f01d-oisst-transform.zarr/2/sst/c/0/0/0/0"

check "$BASE_URL/stores/f01e-oisst-unpacked.zarr/sst/zarr.json"
check "$BASE_URL/stores/f03c-asi-transform.zarr/zarr.json"
check "$BASE_URL/stores/f03c-asi-transform.zarr/2/z/c/0/0/0"
check "$BASE_URL/stores/f03b-asi-rowchunk.zarr/z/c/0/1000/0"

echo "== Pawsey: copied virtual indexes"
check "$BASE_URL/virtual/oisst-v2.1-daily/mdim.vrt"
check "$BASE_URL/virtual/oisst-v2.1-daily/icechunk/repo"
check "$BASE_URL/virtual/oisst-v2.1-daily/kerchunk/.zmetadata"

echo "== source.coop (for comparison)"
check "https://data.source.coop/$SRC_ACCOUNT/ausantarctic-scratch/oisst/oisst-v2.1-daily/mdim.vrt"

echo "== upstream hosts the virtual references point at (decides whether a browser can follow them)"
check "$OISST_URL/$OISST_MONTH/oisst-avhrr-v02r01.${OISST_MONTH}01.nc"
check "https://noaadata.apps.nsidc.org/NOAA/G02202_V6/south/daily/1978/sic_pss25_19781025_n07_v06r00.nc"
check "https://data.seaice.uni-bremen.de/amsr2/asi_daygrid_swath/s3125/netcdf/2012/asi-AMSR2-s3125-20120801-v5.4.nc"

echo "== negative control: listing should be denied (GetObject-only policy)"
curl -s -o /dev/null -w '%{http_code} list %{url_effective}\n' -m 30 "$PAWSEY_ENDPOINT/$BUCKET?list-type=2&prefix=$PREFIX/"
