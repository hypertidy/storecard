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

Status: early. Family F01 (OISST) has six twins: f01a to f01d are published,
f01e and f01f build locally and go up on the next published run. The rest
of the plan is in `docs/fixtures-plan.md`.

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

## 2. Build the fixtures yourself (local, about 50 MB download)

Python 3.10 or newer:

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
bash build/fetch_oisst.sh 202501 data/oisst-202501
.venv/bin/python -I build/build_f01.py data/oisst-202501 out http://localhost:8096
python3 -I serve/serve_cors.py out 8096
```

Then open `http://localhost:8095/external/localhost:8096/catalog/catalog.json`
in the browser from step 1. `serve/serve_cors.py` adds the CORS headers and
byte-range responses a browser Zarr reader needs; Python's built-in
`http.server` does neither.

To change a fixture, edit `build/build_f01.py`: each twin is a few lines in
`main()`, and the collection description carries its expected outcome.

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
