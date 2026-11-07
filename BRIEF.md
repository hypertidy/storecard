# storecard: project brief

Read this first. It records how the project came about, what exists, what
has been learned, what is decided and what is open. Keep it current: when a
decision is made or a next step is done, edit this file in the same PR.

Last updated: 2026-11-07.

## In one paragraph

Readers of array data (browsers, catalogs, analysis tools, agents) keep
failing on a small set of facts that a store's metadata holds, or fails to
hold: what the grid is, which CRS it is in, how values are packed, which
fill value wins, how it is chunked, and where its bytes live. storecard makes
those facts explicit as a **store card**, read from metadata alone. Where a
store hides a simple grid behind coordinate arrays, a grid inference step
(gproj, to become **regula**) proposes the four numbers and a CRS string that
describe it exactly, recorded as an **assertion**: a separate, evidenced,
versioned claim about someone else's store. Cards and assertions are files
on storage, so the whole resource is a static catalog anyone can publish,
mirror and read.

## How it started

The project grew out of work on the Zarr profile for Portolan
(portolan-sdi/portolan-spec issue 132, draft text in PR 234, reference
renderer in portolan-sdi/portolan-browser PR 92). Building browser fixtures
to test that profile showed that the hard cases are not rendering problems
but interpretation problems: grids declared by coordinate arrays, packing
ignored, fill values in disagreement, nominal axes that are wrong. A viewer
cannot fix those; a declaration can. Comparing with a reader that adapts to
stores instead (allboa/sondage issue 18, ACCESS-ESM1.6 ocean temperature)
made the same point from the other side.

## What exists

| Thing | Where | State |
| ----- | ----- | ----- |
| Zarr browser fixtures, built as twins | `portolan/` | F01 OISST (6 twins), F03 polar sea ice (Bremen ASI AMSR2 3.125 km, 6 twins; NOAA/NSIDC G02202 25 km south and north, 4 twins), F08 ACCESS-ESM1.6 tripolar ocean (4 twins). Published at `https://projects.pawsey.org.au/aad-derived/portolan-fixtures/catalog/catalog.json` (F08 pending a rerun) |
| Fixture builders, local CORS/range server, Setonix runbook | `portolan/build`, `portolan/serve`, `portolan/setonix` | working |
| Prototype card extractor (local netCDF) | `proto/protocard.py` | PR 4 |
| Card extractor for Zarr v2/v3 stores | `src/storecard/`, codes in `FINDINGS.md` | working on local stores; remote (s3, https) written, not yet run against the published catalog |
| Fixture tests | `tests/`: synthetic sources run through the unchanged `portolan/build` builders, so shapes, chunking and attributes match the published fixtures | 18 fixtures (F01, F03 Bremen and G02202 south, F08), 96 tests; opt-in network tests (`STORECARD_NETWORK=1`) check the published Pawsey catalog against the same expectations (all match) and a sharded source.coop store |
| Prototype cards over the rasterwise problem files | `cases/rasterwise/cards.jsonl` | PR 4 |
| Problem-file archive | rgdal-dev/rasterwise | being consolidated into a checksummed superset; stays its own repo |
| Grid inference design | mdsumner/gproj (`design.md`, Phase 2 `detect_grid`) | R, design written, detector partly prototyped |
| Virtual stores used as test sources | source.coop `ausantarctic/ausantarctic-scratch/` (OISST, G02202, Bremen ASI, BRAN, MUR, ACCESS-ESM1.6) | published by raad.virtualize |

## What the fixtures have shown so far

- **Transport works.** Pawsey Acacia and source.coop both serve
  cross-origin range reads. A browser drew f01b straight from the bucket.
- **Packing is ignored.** The reference renderer drew CF-packed int16 OISST
  as raw integers against a ramp in physical units: the whole ocean saturated.
- **Fill values are not treated as missing** unless STAC `nodata` says so;
  land drew as the bottom colour. Writers disagree too: xarray's default for
  Zarr v3 writes `fill_value` 0 beside a CF `_FillValue` of -999, and a plain
  float `_FillValue` attribute (as raad.virtualize writes it) fails xarray's
  v3 decoder, while -1e20 stored as float32 never equals the float64
  attribute, so masking silently fails.
- **Source hosts decide whether virtual stores can draw.** NCEI sends
  `Access-Control-Allow-Origin: *`; noaadata.apps.nsidc.org sends none, so the
  G02202 virtual store cannot be read from any browser, wherever its index is
  hosted.
- **Virtual stores inherit source chunking.** Bremen ASI is one row per
  chunk; ACCESS-ESM1.6 packs 25 depth levels per chunk. Both exceed the draft
  profile's amplification bound of 8.
- **Indexes drop interpretation.** The G02202 virtual store has no grid
  mapping; the ACCESS-ESM1.6 store names `geolon_t geolat_t` in `coordinates`
  but does not carry them, leaving 1-D nominal axes that are wrong north of
  the tripolar fold.
- **The rasterwise heuristics find the known cases unprompted:**
  Mercator-spaced latitude (Aviso MADT, ACCfronts), swapped axes (3A-DAY),
  and five files with only 2-D lon/lat that are candidates for a grid fit.

## Decisions

- **Cards are facts, not opinions.** Rule sets (a spec's conformance, a
  viewer's capabilities, house rules) are thresholds over cards, added later.
- **Assertions, not edits.** A fix is a separate document keyed to the
  store's URL and version, recording what is asserted, the evidence
  (residuals, the coordinate sample fitted) and who asserted it. It can be
  emitted as a GDAL VRT, zarr-conventions attributes, or a STAC asset patch.
  Upstream adoption closes it as settled.
- **Grid inference is not reimplemented here.** It belongs to gproj/regula;
  the card carries a coordinate sample (edges plus a central cross) so
  inference runs from the card alone.
- **rasterwise stays its own repo** as the archive of problem files and their
  lessons. storecard reads it and keys cards to its manifest checksums.
- **Dependencies stay small.** The extractor needs zarr and numpy only. No
  rasterio, no shapely; where GDAL is used, it is osgeo.gdal in Python or
  gdalraster in R.
- **Lead with a demo, not the vision.** The resource earns "community" by
  working on real stores first.

## Open questions

1. **Language of the extractor.** Started in Python (`src/storecard/`). Python first (Zarr v3, Icechunk and
   kerchunk access), or R through GDAL multidim. The card format stays
   language-neutral either way.
2. **gproj to Rust as "regula".** A Rust core with R (extendr) and Python
   (pyo3) bindings, and WebAssembly so browsers can apply assertions
   client-side. Projection maths: a few pure-Rust families versus libproj.
3. **The assertion schema**: fields, versioning, standing (who may assert),
   expiry when the source changes, settlement when a publisher adopts it.
4. **Where the register lives**: a static catalog on object storage
   (source.coop alongside the stores it describes is the obvious first home).
5. **The Portolan conversation**: propose two conformance tiers (catalog,
   and browser-drawable as an optional pack), conventions-based grid and CRS
   declaration, and rule packs as data. Comments drafted in
   `portolan/docs/zarr-profile-comments.md`; not yet posted.

## Next steps, in order

1. Card extractor for stores (URL in, card out, metadata only), tested
   against the `portolan/` fixtures, whose cards are known in advance.
   Zarr part done (`src/storecard/`) and checked against the published
   catalog: every published fixture gives its expected card. Over plain
   HTTP the unconsolidated fixture stores cannot be listed, so arrays are
   found from STAC `cube:variables` by following dimension, `coordinates`
   and `grid_mapping` names (`GROUP_NOT_LISTABLE` records it). Still to do:
   CORS probing of the hosts of referenced chunks for virtual stores, and
   Icechunk and kerchunk forms; tooling and containers to be settled from
   hypertidy/gdal-r-ci.
2. Grid fit from a card: must recover EPSG:3412 and the exact transform from
   `f03d-asi-latlon2d`, and refuse the tripolar `f08c-esm-geo2d`.
3. One assertion end to end: a refused store is fitted, the assertion is
   published, a viewer applies it, and the store draws identically to its
   twin. This is the demo.
4. Cards over the `ausantarctic` stores on source.coop; fix findings at
   source.
5. Rule packs and viewer capability matching.

## Reading

- [Regular in what?](https://hypertidy.github.io/regular-in-what/)
- [Grids: regular, rectilinear, curvilinear](https://www.hypertidy.org/posts/2026-05-28_regular-rectilinear-curvilinear/)
- [VRT is: Closure, Names, Placement, Assertion, Deferral, Emission](https://www.hypertidy.org/posts/2026-11-06_vrt-six-properties/)
- [Broken netCDF](https://www.hypertidy.org/posts/2025-09-04_broken-netcdf/)
- portolan-sdi/portolan-spec issue 132 and PR 234; portolan-sdi/portolan-browser PR 92
- allboa/sondage issue 18
- `portolan/docs/results-2026-11-06.md`, `portolan/docs/fixtures-plan.md`
