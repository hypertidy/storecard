# portolan-fixtures: Zarr conformance fixtures for polar, ocean and virtual cases

Status: F01 built and published (see results-2026-11-06.md); the rest is plan. Expected outcomes are
predictions to be confirmed by the browser harness, not measurements.

Context: the Zarr profile drafted in portolan-sdi/portolan-spec PR 234, the
evidence report attached to portolan-spec issue 132, and the reference
implementation in portolan-sdi/portolan-browser PR 92. That report's 22-store
test set has no polar stereographic grid, no 0-360 longitude grid, no grid
that crosses the antimeridian, no store with ascending Y, no CF-packed integer
variable, and no physical/virtual twin of the same data. This set fills those
gaps.

## Method: twins

Most fixtures come as twins: the same data in two or more presentations that
should draw identically. A difference between twins is a client bug or a spec
gap, and the twin pair says which presentation choice caused it. A fixture
that only shows "draws" or "refuses" says much less.

## Where it lives

| Layer | Location | Notes |
| ----- | -------- | ----- |
| Recipes | this repo (`build/`) | One script per fixture family, rebuilds every store from its upstream source. The repo is the source of truth; the bucket is a cache of its outputs. |
| Stores, build and test | Pawsey Acacia, `aad-derived/portolan-fixtures/` (or a dedicated bucket) | Public read, GetObject only. No ListBucket needed for Zarr v3 or Icechunk. |
| Stores, durable | source.coop, `ausantarctic/portolan-fixtures/` | Mirror once stable. Pawsey allocations are tied to a project and expire; a fixture set the spec links to should not depend on one. |
| Catalog | same bucket, `catalog/` | The fixture set is itself a Portolan catalog: STAC, README.md, AGENTS.md. It can be validated with rashid and submitted to the registry. |

Bucket CORS (set in the setup script, not by hand):

- AllowedOrigins `*`, AllowedMethods `GET, HEAD`, AllowedHeaders `*` (covers
  `Range`)
- ExposeHeaders `Content-Range, Content-Length, ETag`
- Check it with a cross-origin fetch from a page on a different origin. A test
  that serves the catalog and the stores from one origin hides CORS failures.

Layout:

```
portolan-fixtures/
  README.md
  AGENTS.md
  catalog/
    catalog.json
    <family>/collection.json        # description ends with the expected outcome
  stores/
    <fixture-id>.zarr/              # physical Zarr v3 unless stated
    <fixture-id>.icechunk/          # Icechunk repositories
  expected.json                     # fixture id -> expected outcome, for the harness
```

The collection descriptions follow the existing harness convention in
portolan-browser (`tests/fixtures/catalogs/zarr-wild`): each description ends
with its expected browser outcome, so the same runner (`zarr-wild-check.mjs`)
can drive this catalog unchanged.

## Fixture families

### F01 OISST, presentation twins (geographic, 0-360, ascending Y, packed int16)

Source: NOAA OISST v2.1 AVHRR daily netCDF, one month. Native grid 0.25 deg,
1440 x 720, lon 0.125..359.875, lat -89.875..89.875 ascending, dims
`(time, zlev, lat, lon)`, `sst` int16 with CF `scale_factor` 0.01 and
`_FillValue` -999. (Check all of this against the current files before
building.)

| Id | Presentation | Tests |
| -- | ------------ | ----- |
| f01a-oisst-native | as published: lon 0-360, lat ascending, CF packing in attributes, length-1 `zlev` | x > 180 in EPSG:4326; Y axis direction; CF packing vs a `scale_offset` codec; length-1 extra dim |
| f01b-oisst-ydesc | f01a with lat flipped to descending | twin of f01a on Y direction only |
| f01c-oisst-180 | f01a rolled to lon -180..180 | twin of f01a on longitude convention only |
| f01d-oisst-transform | f01b plus `spatial:transform`, `spatial:shape`, `proj:code`, 2-level pyramid | twin of f01b with the grid declared in the zarr-conventions form |
| f01e-oisst-unpacked | f01b as float32, unpacked, `scale_offset` not used | twin of f01b on packing only; the display range must be identical |

Expected: all five draw identically, with the same colours for the same
statistics. Predicted spec-draft status: f01a to f01c fail the overviews MUST
(the coarsest level is 6 chunks at 512 px); f01d conforms.

### F02 Antimeridian sector

Source: f01a subset to lon 120..290 (crosses 180), lat -80..-30.

| Id | Presentation | Tests |
| -- | ------------ | ----- |
| f02a-sector-0360 | lon 120..290, monotonic | contiguous in 0-360, so no split in the store |
| f02b-sector-180 | lon 120..180 then -180..-70, as stored after a naive roll | non-monotonic 1-D axis; should be refused by the regularity check |
| f02c-sector-bbox | f02a with STAC `bbox` written west > east | STAC antimeridian bbox convention; the catalog search and the map extent |

Expected: f02a draws across the antimeridian; f02b refused with a reason;
f02c draws, and the map zooms to the right extent rather than the whole world.

### F03 Southern polar stereographic, grid-declaration twins (built)

Source: University of Bremen ASI AMSR2 v5.4 sea ice concentration, 3.125 km,
southern hemisphere, seven days from 2025-09-15: 2656 x 2528 on the NSIDC
polar stereographic south grid (EPSG:3412, Hughes 1980 ellipsoid), the same
extent as the 25 km G02202 grid. The source files are south-up, name the
variable `z`, carry no grid mapping, and are chunked one row per chunk.
Built by `build/build_f03.py`; see the F03 table in the README for the six
twins (native, row-chunked, transform + pyramid, 2-D lon/lat only,
PROJJSON-only, renamed grid mapping).

G02202 v6 (25 km) is built alongside as physical twins, south (same extent,
8 x 8 Bremen cells per cell, same AMSR2 sensor and week) and north
(EPSG:3411). Its virtual references cannot be read from a browser (no CORS at
the source host), which is why these are physical copies.

### F04 Antarctic pole-centred pyramid (EPSG:3031)

Source: a coarse REMA v2 mosaic (the 1 km or 500 m product, if still
published), with a pyramid down to a few chunks.

| Id | Presentation | Tests |
| -- | ------------ | ----- |
| f04a-rema-pyramid | EPSG:3031, multiscales, factor 2, per-level `spatial:transform` | a pole inside the data; level order from per-level transforms |
| f04b-rema-pyramid-finestlast | as f04a with levels listed coarsest first | twin on level order only |

Expected: both draw identically. In a Web Mercator view the pole region is
clipped; that is a limit of the map view, not of the store. The spec should
not count it against the store.

### F05 REMA, virtual Icechunk over COG tiles (existing store)

Source: the existing rema-icechunk repository (virtual chunk references into
the published REMA v2 2 m COGs).

Tests: virtual references into TIFF tiles on a third-party host; CORS on that
host; whether the COG compression (and any TIFF predictor) maps onto a codec
the browser has; the chunk grid the store uses (if it is rectilinear, this
tests the chunk-grid extension too).

Expected: unknown, and a refusal is fine. Whichever check refuses it is the
finding.

### F06 BRAN daily, virtual references into netCDF4 (existing store)

Source: the existing raad.virtualize index-only store `bluelink-daily-salt` on
the source.coop scratch prefix.

Tests: references into HDF5 chunks on a remote host; a depth dimension the
client must pin; zlib and shuffle codecs; amplification as set by the source
netCDF chunking (measure it, do not assume it); CORS on the source host.

Expected: unknown. If the source host sends no CORS header, this is the
second real case for the draft's "CORS on every referenced file" rule.

### F07 MUR SST, physical/virtual twin

Source: GHRSST MUR, one day.

| Id | Transport | Tests |
| -- | --------- | ----- |
| f07a-mur-physical | physical Zarr v3 copy of the virtual store's logical array | baseline |
| f07b-mur-virtual | the raad.virtualize virtual store over the daily MUR COGs | same logical array through byte references |

Expected: identical draws. This pair is the evidence for treating "virtual"
as a transport property: the same array metadata, the same codecs, and only
how bytes are found differs. If f07b fails, the reason will be a transport
cause (CORS, a missing codec carried over from the source), not a metadata
cause.

### F08 Gaps for others to fill

- Rotated-pole regional climate grid (a common case in regional climate
  downscaling): CRS outside EPSG, regular in its own CRS.
- An ocean model native grid (tripolar or ROMS-type): genuinely curvilinear,
  correctly out of scope for v1, to pin the refusal reason.

## Build order

1. Bucket and CORS setup script, plus cross-origin check page.
2. F01 (exercises every presentation question and is cheap to build).
3. F03 (the grid-declaration argument).
4. F07 (the physical/virtual argument).
5. F02, F04, then F05 and F06 (these already exist; they only need catalog
   entries).
6. Run the portolan-browser harness, record outcomes in expected.json, and
   report the results on issue 132 as a table matching the report's format.
