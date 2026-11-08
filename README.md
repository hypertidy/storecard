# storecard

New here? Read [BRIEF.md](BRIEF.md) first.

Demo: [one assertion, end to end](https://hypertidy.github.io/storecard/demo/), a store
refused for hiding its grid behind 2-D lon/lat draws identically to its declared
twin once a published assertion is applied (source in `site/demo/`).

A **store card** is a small, metadata-only description of an array store: what
its grid is, how it is chunked and compressed, where its bytes live, and
whether a given reader can use it. A card is built from a URL by reading a few
kilobytes of metadata, never a data chunk.

Cards are facts, not opinions. Rule sets (a catalog spec's conformance, a
viewer's capabilities, house rules) are thresholds applied to cards, so any
number of them can be checked against one card, and a viewer and a catalog
can be matched at read time.

Status: design. The `portolan/` directory holds a working set of Zarr
fixtures (published on Pawsey, built from OISST, sea ice and ocean-model
sources) that serves as the first test suite: each fixture has a known
presentation, so its card is known in advance.

## Why

Readers keep failing on the same small set of facts that the metadata
already holds, or that it fails to hold:

- the grid is given as coordinate arrays, so a reader must test regularity
  from data instead of reading it from a declaration;
- 2-D longitude and latitude arrays hide a grid that is regular in some
  projected CRS ("cryptic curvilinear"), which four numbers and a CRS string
  describe exactly;
- 1-D nominal axes look regular and are wrong (ocean model tripolar grids);
- CF packing, fill values and units decide the colour of every pixel and are
  read inconsistently;
- chunking set for the source files (one row, or 25 depth levels, per chunk)
  is carried into virtual stores, where it sets the read cost of every view;
- referenced bytes live on hosts with their own CORS behaviour.

Each of these is checkable from metadata. A card records them once, so a
person, an agent or a viewer can decide before fetching data.

## The card (v0 draft)

One JSON document per store (per array for multi-array stores):

| Section | Fields |
| ------- | ------ |
| `source` | url, form (zarr v2/v3, icechunk, kerchunk json/parquet, mdim VRT, COG), version or etag, scanned_at |
| `arrays` | name, dtype, shape, dimension names, chunk shape (inner and shard), codec chain |
| `values` | units, CF packing (`scale_factor`, `add_offset`), fill values from every source (Zarr `fill_value`, CF `_FillValue`, `missing_value`, STAC `nodata`) and whether they agree, `valid_range`, flag values |
| `grid` | declared form: `transform` (zarr-conventions spatial / GeoTransform), `coords_1d_regular`, `coords_1d_irregular`, `coords_2d`, `coords_named_missing`, `none`; axis order and direction; registration |
| `crs` | declared CRS (proj convention, CF grid mapping, WKT), how it was found |
| `coord_sample` | for 1-D and 2-D coordinates: edges plus a central cross, enough for grid inference without re-reading the arrays |
| `cost` | amplification for a single-index 2-D view per array, overview levels, coarsest-level chunk count |
| `hosts` | each host serving bytes (metadata and referenced chunks): CORS status, range support, protocol |
| `findings` | ordered list of problems with a code, e.g. `GRID_CRYPTIC_CURVILINEAR`, `FILL_DISAGREE`, `COORDS_NAMED_MISSING` |

## Using the extractor

```sh
pip install -e .                      # zarr and numpy; add [remote] for s3:// and https://
storecard path/to/store.zarr          # or: python -m storecard URL --stac collection.json
```

```python
from storecard import card
c = card("f03d-asi-latlon2d.zarr", stac="collection.json")
```

Zarr v2 and v3 only for now (Icechunk, kerchunk and VRT are later). The card
reads metadata and coordinate arrays, never a data chunk. The variables
section holds `values`, `grid` (with `coord_sample` and the presented
`costume`, A to H from regular-in-what), `crs` and `cost` (non-spatial read
factor for the inner chunk and the shard; tile amplification aligned and
worst case) for each data array. `findings_summary` groups the findings by
code. The codes and costumes are listed in [FINDINGS.md](FINDINGS.md).

Assertions: `storecard URL --assertion a.json` applies an assertion as an
overlay; `--emit zarr|stac|vrt` writes it as zarr-conventions attributes, a
STAC patch or a GDAL multidimensional VRT. See [ASSERTIONS.md](ASSERTIONS.md);
published assertions are in `assertions/`.

`tests/test_fit.py` is skipped without osgeo.gdal. Network tests are opt-in: `STORECARD_NETWORK=1 pytest` (needs `[remote]`).

Tests: `pip install -e .[test] && pytest`. The tests write small synthetic
sources, run the unchanged `portolan/build` builders on them (about 10 s), and
check each fixture's card against its stated presentation. Set
`STORECARD_FIXTURES=/some/dir` to keep the build between runs.

## Inferring the grid: degredation

Grid inference is the job of degredation (formerly gproj
 [hypertidy/degredation](https://github.com/hypertidy/degredation), design notes in
`design.md`, Phase 2 `detect_grid`): a rectilinear test, candidate CRSs from
the coordinates' geometry, a regularity test in projected space, resolution
snapping, half-cell extent recovery and a known-grid table, returning a CRS,
an extent, a resolution, residuals and a confidence. storecard does not
reimplement it: the card's `coord_sample` carries what `detect_grid` needs,
so inference runs from the card alone.

`storecard.fit` is the narrow part kept here: it projects the card's sample
into a short list of published frames (polar stereographic, EASE, web
mercator, lon/lat) with osgeo.gdal, fits one affine per frame, and passes a
frame only if every sampled cell centre is within 0.001 cell. The passing
transform is snapped to its shortest decimal form and checked again; the
roundest wins and the rest are recorded. No frame passing gives a refusal
listing every frame and its residual. Needs osgeo.gdal (`python3-gdal`, or
the `gdal` wheel built against the system GDAL).

```
python -m storecard URL --stac COLLECTION --fit
```

## Assertion

A proposed fix is an **assertion**: a statement that supplies what a source
lacks or corrects what it gets wrong, without copying a byte. It is the
"assertion" property of GDAL VRT (SRS, geotransform, nodata, scale and offset
in classic VRT; coordinates, dimension types and names in multidimensional
VRT), applied to stores found in the wild.

An assertion is kept separate from the source, keyed to the store's URL and
version, and records what it asserts (transform and CRS, fill value, units,
dimension roles), the evidence (residuals, the coordinate sample it was fitted
to) and who or what asserted it. It can be emitted in whichever form a reader
takes: a GDAL VRT, zarr-conventions attributes (`spatial:`, `proj:`) for a
virtual store's metadata, or a STAC asset patch. The source store is never
edited; fixes go upstream by asking the publisher.

## Reading

- [Regular in what?](https://hypertidy.github.io/regular-in-what/): grids,
  coordinates and the curvilinear confusion
  ([hypertidy/regular-in-what](https://github.com/hypertidy/regular-in-what))
- [Grids: regular, rectilinear, curvilinear](https://www.hypertidy.org/posts/2026-05-28_regular-rectilinear-curvilinear/):
  a grid taxonomy rooted in coordinate storage, not CRS
- [VRT is: Closure, Names, Placement, Assertion, Deferral, Emission](https://www.hypertidy.org/posts/2026-11-06_vrt-six-properties/):
  the design underneath VRT, where assertion is named
- [Broken netCDF](https://www.hypertidy.org/posts/2025-09-04_broken-netcdf/):
  the "cryptic curvilinear" case that degredation's detector is built on

## Plan

1. **Card extractor**: URL in, card out, metadata only. Python first (Zarr v3,
   Icechunk and kerchunk access are easiest there); the card format is
   language-neutral so R can produce and read cards too. Tested against the
   `portolan/` fixtures, whose cards are known.
2. **Grid inference** on the card's coordinate sample (named frames in
   `storecard.fit`, open-ended inference via degredation). Passes if it
   recovers EPSG:3412 and the exact transform from the fixture with only 2-D
   lon/lat (`f03d-asi-latlon2d`), and refuses the tripolar ocean grid
   (`f08c-esm-geo2d`). A passing fit is recorded as an assertion.
3. **Scanner**: run cards over the `ausantarctic` stores on source.coop (own
   data, fixable at source), then wider. Ranked triage for manual review:
   high-confidence assertions first.
4. **Rule packs and viewer capabilities**: thresholds over cards. Later.

## Layout

```
portolan/          Zarr fixtures, builders, Setonix runbook, and notes on the
                   Portolan Zarr profile (portolan-sdi/portolan-spec issue 132)
cases/rasterwise/  prototype cards for the rasterwise problem-file collection
                   (the files themselves live in rgdal-dev/rasterwise)
proto/             prototype card extractor (local netCDF files)
src/storecard/     card extractor for Zarr stores (step 1 of the plan), and
                   assertions: apply as overlay, emit (step 3)
assertions/        assertions about published stores
site/              GitHub Pages: Quarto website and the demo (site/demo/), deployed by
                   .github/workflows/pages.yml; some pages include FINDINGS.md,
                   ASSERTIONS.md and portolan/README.md
tests/             fixture tests: synthetic sources through the portolan builders
```
