# storecard: project brief

Read this first. It records how the project came about, what exists, what
has been learned, what is decided and what is open. Keep it current: when a
decision is made or a next step is done, edit this file in the same PR.

Last updated: 2026-11-09.

## In one paragraph

Readers of array data (browsers, catalogs, analysis tools, agents) keep
failing on a small set of facts that a store's metadata holds, or fails to
hold: what the grid is, which CRS it is in, how values are packed, which
fill value wins, how it is chunked, and where its bytes live. storecard makes
those facts explicit as a **store card**, read from metadata alone. Where a
store hides a simple grid behind coordinate arrays, a grid inference step
(**degredation**, formerly gproj) proposes the four numbers and a CRS string that
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
| Zarr browser fixtures, built as twins | `portolan/` | F01 OISST (6 twins), F03 polar sea ice (Bremen ASI AMSR2 3.125 km, 6 twins; NOAA/NSIDC G02202 25 km south and north, 4 twins), F08 ACCESS-ESM1.6 tripolar ocean (4 twins). Published at `https://projects.pawsey.org.au/aad-derived/portolan-fixtures/catalog/catalog.json` (20 collections; F08's true positions come from the run's fixed fields `ocean-2d-geolon_t-fx.nc` / `ocean-2d-geolat_t-fx.nc`, which the yearly files name but do not carry, so f08c exists and f08d is regridded on them) |
| Fixture builders, local CORS/range server, Setonix runbook | `portolan/build`, `portolan/serve`, `portolan/setonix` | working |
| Prototype card extractor (local netCDF) | `proto/protocard.py` | PR 4 |
| Card extractor | `src/storecard/` (`forms.py` for kerchunk and Icechunk), codes in `FINDINGS.md` | Zarr v2/v3, kerchunk JSON and Parquet, Icechunk; local, https and s3; checked against the published catalog and the five ausantarctic virtual stores in both forms |
| Assertions v0: schema, overlay, emitters (zarr-conventions attrs, STAC patch, multidim VRT) | `src/storecard/assertion.py`, `ASSERTIONS.md`, `assertions/` | the f03d assertion makes its card match its twin f03e, locally and on the published store; the VRT is checked as XML, not yet opened with GDAL |
| Fixture tests | `tests/`: synthetic sources run through the unchanged `portolan/build` builders, so shapes, chunking and attributes match the published fixtures | 18 fixtures (F01, F03 Bremen and G02202 south, F08), each also as a kerchunk JSON, kerchunk Parquet and Icechunk twin (`tests/virtual.py`) that must give the same variables; 175 tests; opt-in network tests (`STORECARD_NETWORK=1`) check the published Pawsey catalog against the same expectations (all match), a sharded source.coop store, and the five ausantarctic virtual stores |
| Prototype cards over the rasterwise problem files | `cases/rasterwise/cards.jsonl` | PR 4 |
| Problem-file archive | rgdal-dev/rasterwise | being consolidated into a checksummed superset; stays its own repo |
| Grid inference design | hypertidy/degredation, formerly mdsumner/gproj (`design.md`, Phase 2 `detect_grid`) | R, design written, detector partly prototyped |
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
- **Probing chunk hosts needs a browser's request, not a HEAD.** THREDDS
  (thredds.nci.org.au, the BRAN source) answers 403 to HEAD with an Origin
  header and serves the browser's ranged GET with `Access-Control-Allow-Origin: *`.
  The card probes by HEAD and falls back to a GET of the file's first byte
  when the sampled chunk starts past it, so no chunk byte is read. Listing
  every reference instead takes 25 s to over 3 minutes per store (37.5
  million for BRAN), so a card samples the first and last chunk of each
  data array; every store so far references one host.
- **The two forms of one virtual store can differ.** raad.virtualize writes
  CF `_FillValue` into its Icechunk stores but not into the kerchunk stores
  of the same data (OISST, G02202, BRAN, MUR; the value equals Zarr
  `fill_value`, so nothing disagrees, but a reader masking by `_FillValue`
  finds nothing in the kerchunk form). Fix in raad.virtualize.
- **A codec chain is a fact, not a capability.** The MUR store's chunks are
  TIFF tiles with an `imagecodecs_delta` filter; zarr refuses to parse
  metadata naming a codec it cannot load. The card registers placeholders
  that parse and refuse to decode, so it records the chain without needing
  imagecodecs.
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
- **Grid inference belongs to degredation; storecard checks named frames.**
  The card carries a coordinate sample (edges plus a central cross) so
  inference runs from the card alone. `storecard.fit` (decided 2026-11-08)
  tests that sample against a short list of published frames with
  osgeo.gdal and records the result as an assertion or a refusal; choosing
  a frame for coordinates that match no published grid stays with
  degredation, and `tests/test_fit.py` is the contract it is held to.
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
2. **degredation to Rust.** A Rust core, under the same name, with R (extendr) and Python
   (pyo3) bindings, and WebAssembly so browsers can apply assertions
   client-side. Projection maths: a few pure-Rust families versus libproj.
3. **The assertion schema**: v0 in `ASSERTIONS.md` settles fields,
   versioning (a metadata digest; stale when the store changes) and
   settlement (`status`). Still open: standing (who may assert, how
   assertions from different sources are weighed) and the evidence schema
   for fits.
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
   and `grid_mapping` names (`GROUP_NOT_LISTABLE` records it). kerchunk
   (JSON and Parquet) and Icechunk done (`src/storecard/forms.py`): each
   fixture's virtual twin gives the fixture's variables, and the hosts its
   chunk references point at are probed for CORS and range support
   (`CHUNK_HOST_NO_CORS`, `CHUNK_REFS_NOT_HTTP`) without reading a chunk.
   An Icechunk twin keeps the v3 metadata documents, so its metadata digest
   is the store's and assertions carry over. Still to do: mdim VRT and COG
   forms; tooling and containers to be settled from hypertidy/gdal-r-ci.
2. Grid fit from a card: must recover EPSG:3412 and the exact transform from
   `f03d-asi-latlon2d`, and refuse the tripolar `f08c-esm-geo2d`. Done for
   named frames (`src/storecard/fit.py`, `python -m storecard URL --fit`):
   the published f03d fits EPSG:3412 at 5e-10 cells with the transform
   snapped exactly; the published f08c is refused (best frame EPSG:4326,
   448.5 cells off). The WGS84
   variants EPSG:3976 and EPSG:3031 also fit within tolerance, at pixel
   sizes that are not round, so the roundest transform is chosen and the
   others recorded. The refusal is published as
   `assertions/f08c-esm-geo2d.json`.
   Still to do: frames outside the list, through degredation.
3. One assertion end to end: a refused store is fitted, the assertion is
   published, a viewer applies it, and the store draws identically to its
   twin. This is the demo. Done: the f03d assertion (made by the step 2
   fit) is published in `assertions/` and makes f03d's card match f03e's,
   and `site/demo/` is a static page (GitHub Pages) that reads both
   published stores from the bucket, refuses f03d as published, applies
   the assertion as a zarr-conventions overlay, and checks that f03d then
   draws identically to f03e (values, transform, CRS and every pixel). It
   can also recheck the fit over every cell from f03d's lon/lat (68 MB).
   Still open: the same overlay in portolan-browser.
   A second page, `site/demo/costumes.html`, leads into it: f03a, f03c,
   f03e, f03f and f03d (the published F03 twins) read in the browser under
   four reader rules (zarr-conventions only; CF with fixed `crs` or
   `spatial_ref` names; CF by `grid_mapping`; the card, every declaration
   checked for agreement). Each rule places a different subset; the card
   places the four declared stores, which draw identically to f03e cell for
   cell, and refuses f03d, which the assertion page then places.
   A third page, `site/demo/tripolar.html`, reads the published f08c: the
   1-D axes against the true positions in a north polar view, the per-row
   deviation (under 0.5 cells to row 245, 74.8 at the top row), and the
   published refusal with every frame tried. A fourth page,
   `site/demo/packing.html`, reads f01b and f01e (f01e is f01b unpacked;
   f01a differs from both in latitude order): skipping packing puts 78% of
   ocean cells past the top of the ramp, and f01b unpacked in float32 (the
   type of `scale_factor`) equals f01e bit for bit, every ocean and fill
   cell; float64 unpacking differs in the last bits. f01e kept the packed
   `valid_min`/`valid_max` (-300, 4500) after unpacking; a finding for a
   valid range left in packed units is not written yet. A fifth page,
   `site/demo/fill.html`, reads f01b, f01f and f08b under four reader
   rules (STAC nodata; CF `_FillValue` parsed as a number; Zarr
   `fill_value`; the card). STAC nodata misses f01b (none declared) and
   f08b (-1e20 never equals a float32 cell in float64); the number parse
   misses f08b, whose `_FillValue` xarray wrote as base64; the card masks
   every fill cell in all three, checked against f01e's NaN and f08b's
   values beyond 1e19. f08b stands in for f08a: same fill metadata, one
   level per chunk (0.2 MB for the surface against 6.7 MB).
4. Cards over the `ausantarctic` stores on source.coop; fix findings at
   source. First pass done for the five virtual stores (OISST, G02202
   south, Bremen ASI south, BRAN salt, MUR), kerchunk and Icechunk forms
   (`tests/test_remote.py`). To fix in raad.virtualize: no CRS declared on
   any of them (`CRS_NOT_DECLARED`; G02202 and ASI also
   `PROJECTED_NO_GRID_MAPPING`), BRAN's `coordinates` names arrays it does
   not carry, and the kerchunk form drops CF `_FillValue`. Not fixable
   there: G02202 (NSIDC) and ASI (Bremen) chunk hosts send no CORS
   (`CHUNK_HOST_NO_CORS`); NOAA's S3, NCI THREDDS and source.coop do.
   CRS assertions published 2026-11-09 for the five raadtools tier 1 stores
   (`assertions/ausantarctic/`, built by its `build.py`, checked by
   `tests/test_remote.py`): OISST and MUR EPSG:4326, G02202 south
   EPSG:3412 and north EPSG:3411, ASI south EPSG:3976. The G02202 and ASI
   source files declare these CRSs themselves (GDAL reads them into each
   dataset's `plan.vrt` `<SRS>`); the virtual stores drop them, so the fix
   at source is for raad.virtualize to write the plan's SRS. When it does,
   the store's digest changes and these assertions go stale, as they
   should. These rows feed the raadtools contract (rgdal-dev/rasterwise
   `ledger/raadtools.csv`): one contract row per (dataset, era).
5. Rule packs and viewer capability matching.

## Reading

- [Regular in what?](https://hypertidy.github.io/regular-in-what/)
- [Grids: regular, rectilinear, curvilinear](https://www.hypertidy.org/posts/2026-05-28_regular-rectilinear-curvilinear/)
- [VRT is: Closure, Names, Placement, Assertion, Deferral, Emission](https://www.hypertidy.org/posts/2026-11-06_vrt-six-properties/)
- [Broken netCDF](https://www.hypertidy.org/posts/2025-09-04_broken-netcdf/)
- portolan-sdi/portolan-spec issue 132 and PR 234; portolan-sdi/portolan-browser PR 92
- allboa/sondage issue 18
- `portolan/docs/results-2026-11-06.md`, `portolan/docs/fixtures-plan.md`
