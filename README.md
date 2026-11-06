# portolan-kit

Zarr conformance fixtures for browser rendering, built as **twins**: the same
data in presentations that should draw identically. When twins draw
differently, the difference is a client bug or a spec gap, and the twin pair
says which presentation choice caused it.

Context: the Zarr profile discussion in portolan-sdi/portolan-spec issue 132
and PR 234, and the reference renderer in portolan-sdi/portolan-browser PR 92
(branch `feat/zarr-rendering`). The fixtures target cases that work's 22-store
test set does not cover: ascending Y, 0..360 longitude, CF-packed integers,
fill-value precedence, polar grids, and physical vs virtual delivery of the
same array.

Status: early. Three families: F01 (OISST, global 0.25 degree), F03 (polar
sea ice: Bremen ASI AMSR2 3.125 km south, plus NOAA/NSIDC G02202 25 km south
and north, same week, same sensor) and F08 (an ocean model's native tripolar
grid, ACCESS-ESM1.6).
f01a to f01d are published; f01e, f01f and F03 build locally and go up on the
next published run. The rest of the plan is in `docs/fixtures-plan.md`.

## 1. Look at the published fixtures (no setup)

The catalog is public, CORS-enabled and range-readable:

```
https://projects.pawsey.org.au/aad-derived/portolan-fixtures/catalog/catalog.json
```

Open it in portolan-browser (PR 92 branch):

```
git clone https://github.com/portolan-sdi/portolan-browser && cd portolan-browser
git checkout feat/zarr-rendering
corepack pnpm install
corepack pnpm exec vite --host 127.0.0.1 --port 8095 --strictPort
```

then browse to

```
http://localhost:8095/external/projects.pawsey.org.au/aad-derived/portolan-fixtures/catalog/catalog.json
```

Open a collection and switch on the `sst` layer. The map needs WebGL2.

## 2. Build the fixtures yourself (local, about 100 MB download, 1 GB built)

Python 3.10 or newer:

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
bash build/fetch_oisst.sh 202501 data/oisst-202501
bash build/fetch_asi.sh 20250915 7 data/asi-20250915
bash build/fetch_g02202.sh south 20250915 7 data/g02202-south
bash build/fetch_g02202.sh north 20250915 7 data/g02202-north
bash build/fetch_esm.sh 2014 data/esm
.venv/bin/python -I build/build_f01.py data/oisst-202501 out http://localhost:8096
.venv/bin/python -I build/build_f03.py data/asi-20250915 out http://localhost:8096
.venv/bin/python -I build/build_f03g.py data/g02202-south out http://localhost:8096 south
.venv/bin/python -I build/build_f03g.py data/g02202-north out http://localhost:8096 north
.venv/bin/python -I build/build_f08.py data/esm/ocean-3d-temp-1mon-mean-y_2014.nc out http://localhost:8096
.venv/bin/python -I build/catalog.py out
python3 -I serve/serve_cors.py out 8096
```

Then open `http://localhost:8095/external/localhost:8096/catalog/catalog.json`
in the browser from step 1. `serve/serve_cors.py` adds the CORS headers and
byte-range responses a browser Zarr reader needs; Python's built-in
`http.server` does neither.

To change a fixture, edit `build/build_f01.py` or `build/build_f03.py`: each
twin is a few lines in `main()`, and the collection description carries its
expected outcome. `build/catalog.py` relinks whatever families are present.

## 3. Host on object storage

`setonix/` is the runbook used for the published copy (Slurm jobs on Pawsey
Setonix writing to an Acacia bucket), including copying index-only virtual
stores from source.coop. Any S3-compatible store with CORS works the same way;
`setonix/01-bucket-setup.sh` shows the CORS and policy it needs.

## The F01 twins

All six are one month (January 2025) of NOAA OISST v2.1 daily SST, 0.25
degree, as Zarr v3 with 360 x 360 inner chunks and a CF grid mapping (`crs`,
EPSG:4326).

| Id | Differs from its twin by | Tests |
| -- | ------------------------ | ----- |
| f01a-oisst-native | as published: lat ascending (south-up), lon 0..360, int16 with CF `scale_factor` | Y direction, x > 180, CF packing |
| f01b-oisst-ydesc | f01a with lat descending (north-up) | Y direction only |
| f01c-oisst-180 | f01a with lon rolled to -180..180 | longitude convention only |
| f01d-oisst-transform | f01b plus `spatial:`/`proj:` conventions and a 3-level `multiscales` pyramid; levels 1 and 2 are unpacked float32 | grid declared from metadata; pyramid order; packed level 0 vs unpacked overviews in one store |
| f01e-oisst-unpacked | f01b stored as float32 physical values, NaN fill | separates "packing not applied" from other colour causes |
| f01f-oisst-nodata | f01b with `bands[].nodata = -999` on the STAC asset | whether nodata comes from STAC, CF `_FillValue` or Zarr `fill_value` |

Expected: all six draw identically. First results are in
`docs/results-2026-11-06.md`.

## The F03 twins

G02202 is a physical copy for a reason: its source host sends no CORS header,
so a virtual store over it cannot be read from a browser.

Seven days (from 2025-09-15, near maximum extent) of University of Bremen ASI
sea ice concentration from AMSR2, v5.4: 2656 x 2528 cells at 3125 m on the
NSIDC polar stereographic south grid (EPSG:3412, Hughes 1980 ellipsoid),
float32 percent with NaN fill. The source files are south-up, call the
variable `z`, carry no grid mapping, and are chunked one row per chunk. The
grid has the same extent as the 25 km NOAA/NSIDC G02202 grid, at 8x the
resolution.

| Id | Differs by | Tests |
| -- | ---------- | ----- |
| f03a-asi-native | as published (south-up, `z`) plus a CF grid mapping `crs` (WKT2 `crs_wkt`, WKT1 `spatial_ref`); 512 x 512 chunks | polar stereographic on a non-WGS84 ellipsoid; Y direction |
| f03b-asi-rowchunk | f03a chunked one row per chunk, as the source files and any virtual store over them are | amplification check (about 10x for a 256 px tile) |
| f03c-asi-transform | north-up, `spatial:transform` + `proj:code`, CF grid mapping, 3-level pyramid | the conforming form; pole inside the data |
| f03d-asi-latlon2d | 2-D lon/lat arrays only, no x/y or grid mapping | a regular grid presented as curvilinear |
| f03e-asi-projjson | CRS only as zarr-conventions `proj:projjson` + `spatial:transform`; no CF, no `proj:code` | whether the zarr conventions alone place a grid |
| f03f-asi-gridmap-named | f03a with the grid mapping variable named `polar_stereographic` | the draft's fixed `spatial_ref`/`crs` naming vs CF |

| f03g-g02202-native | G02202 v6 25 km south as published: north-up, uint8 with `scale_factor` 0.01, flags 251-254 above `valid_range`, the file's own grid mapping | packed integers with flag values; cross-product placement against Bremen (8 x 8 Bremen cells per cell, shared edges) |
| f03h-g02202-percent | f03g as float32 percent, flags as NaN, variable `z` | same units and ramp as the Bremen twins |
| f03i-g02202-north-native | as f03g, north: EPSG:3411, central meridian -45 | a second polar CRS; Arctic near its September minimum |
| f03j-g02202-north-percent | f03i as float32 percent | as f03h, north |

Expected: a, c, e and f draw identically; b may be refused by an
amplification check; d is refused as curvilinear although its grid is regular.
g and h sit exactly on the Bremen grid at 8x coarser cells; g's colours are
right only if the client applies `scale_factor` and treats out-of-range flags
as not-data.
In a Web Mercator map the pole region is clipped; that is the map, not the
store.

## The F08 twins

One model year (2014) of ACCESS-ESM1.6 historical monthly ocean temperature,
50 depth levels, on MOM5's tripolar 300 x 360 grid: regular in longitude and
non-uniform in latitude south of about 65N, curvilinear north of it. The model
files carry 1-D nominal axes (`xt_ocean` -279.5 to 79.5, `yt_ocean` in steps
of about 0.25 to 1 degree) and the true 2-D positions `geolon_t`/`geolat_t`.
The source files are on Pawsey and are indexed as a virtual store on
source.coop; that store keeps only the nominal axes while `temp` still names
`geolon_t geolat_t` in its `coordinates` attribute.

| Id | Differs by | Tests |
| -- | ---------- | ----- |
| f08a-esm-native | as the virtual store presents it: nominal axes, dangling `coordinates`, chunks [1, 25, 150, 180] | two refusals at once: non-uniform y, and one level reads 25x what it draws |
| f08b-esm-levelchunk | one level per chunk | only the non-uniform axis remains |
| f08c-esm-geo2d | plus the true 2-D positions | a genuinely curvilinear grid: the correct refusal for v1 |
| f08d-esm-regular | nearest-neighbour regrid to regular 1 degree EPSG:4326 | draws; which depth level shows is up to the client |

The point of a and b: nominal 1-D axes look like a grid and are wrong north
of the fold. A rule that accepts 1-D coordinates as the grid cannot tell; a
declared transform or CRS cannot be made from them honestly.

## Layout

```
build/      fixture builders and the OISST fetch script
serve/      local static server with CORS and byte ranges
setonix/    Slurm/Acacia runbook for the published copy
bucket/     README.md and AGENTS.md uploaded at the catalog root
docs/       fixture plan, comments on the draft profile, results
```

## Licence

Code: MIT (see LICENSE). The fixtures are derived from NOAA OISST v2.1; cite
the upstream product, not these stores.
