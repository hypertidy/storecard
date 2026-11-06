# storecard

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

## Inferring the grid: gproj

Grid inference is gproj's job
([mdsumner/gproj](https://github.com/mdsumner/gproj), design notes in
`design.md`, Phase 2 `detect_grid`): a rectilinear test, candidate CRSs from
the coordinates' geometry, a regularity test in projected space, resolution
snapping, half-cell extent recovery and a known-grid table, returning a CRS,
an extent, a resolution, residuals and a confidence. Background:
[hypertidy.org, 2025-09-04, broken netCDF](https://www.hypertidy.org/posts/2025-09-04_broken-netcdf/).

storecard does not reimplement it. The card's `coord_sample` carries what
`detect_grid` needs, so inference runs from the card alone. A proposed fix is
recorded as an **overlay**: a separate document keyed to the store's URL and
version, holding the transform, CRS, residuals and who asserted it. The
source store is never edited; fixes go upstream by asking the publisher.

## Plan

1. **Card extractor**: URL in, card out, metadata only. Python first (Zarr v3,
   Icechunk and kerchunk access are easiest there); the card format is
   language-neutral so R can produce and read cards too. Tested against the
   `portolan/` fixtures, whose cards are known.
2. **Grid inference** via gproj on the card's coordinate sample. Passes if it
   recovers EPSG:3412 and the exact transform from the fixture with only 2-D
   lon/lat (`f03d-asi-latlon2d`), and refuses the tripolar ocean grid
   (`f08c-esm-geo2d`).
3. **Scanner**: run cards over the `ausantarctic` stores on source.coop (own
   data, fixable at source), then wider. Ranked triage for manual review:
   high-confidence fixes first.
4. **Rule packs and viewer capabilities**: thresholds over cards. Later.

## Layout

```
portolan/   Zarr fixtures, builders, Setonix runbook, and notes on the
            Portolan Zarr profile (portolan-sdi/portolan-spec issue 132)
```
