# Assertions (v0)

An assertion is a separate, evidenced claim about a store someone else
publishes. It supplies what the store lacks or corrects what it gets wrong,
without copying or editing a byte of it: the "assertion" property of GDAL VRT
applied to stores found in the wild. The source store is never written;
fixes go upstream by asking the publisher, and an assertion the publisher
adopts is marked `settled`.

## Document

```json
{
 "assertion_version": "0",
 "kind": "grid",
 "subject": {
  "url": "https://projects.pawsey.org.au/aad-derived/portolan-fixtures/stores/f03d-asi-latlon2d.zarr",
  "variable": "z",
  "metadata_digest": "sha256:..."
 },
 "asserts": {
  "spatial:transform": [3125.0, 0.0, -3950000.0, 0.0, -3125.0, 4350000.0],
  "spatial:shape": [2656, 2528],
  "spatial:dimensions": ["y", "x"],
  "spatial:transform_type": "affine",
  "spatial:registration": "pixel",
  "proj:code": "EPSG:3412"
 },
 "crs_axes": ["x", "y"],
 "evidence": {"method": "..."},
 "by": {"name": "..."},
 "made_at": "2026-11-07T21:30:00Z",
 "status": "proposed"
}
```

| Field | |
| ----- | - |
| `kind` | `grid`: the variable is regular in the stated frame. `refusal`: it is regular in no frame tried (then `refuses: {reason, frames_tried}` in place of `asserts`) |
| `subject.url`, `subject.variable` | the store and the variable (array path) the claim is about |
| `subject.metadata_digest` | sha256 of the store's metadata as read when the assertion was made (every array's metadata document and the root attributes, canonical JSON). The card records the same digest as `source.metadata_digest`. If the store changes, the digest changes and the assertion goes stale |
| `asserts` | only zarr-conventions `spatial:` and `proj:` keys, so it can be written into a virtual store's metadata as it stands. The transform is in the zarr-conventions / STAC order, cell corners: x = a col + b row + c, y = d col + e row + f |
| `crs_axes` | the variable's spatial dimensions, by role, in the CRS's axis order: `["x", "y"]` for easting/northing, `["y", "x"]` for latitude/longitude. Needed for the VRT's axis mapping without consulting PROJ |
| `evidence` | free form for now: for a fit, residuals and the coordinate sample fitted (degredation, step 2 of the brief); for a known grid, where it is known from |
| `by` | who or what asserted it |
| `status` | `proposed`, `settled` (the publisher adopted it) or `withdrawn` |

## Applying

`card(url, assertions=[doc])` (CLI: `storecard URL --assertion FILE`) builds
the card as if the asserted attributes were on the variable, and records:

- `source.assertions`: each assertion, whether it was applied, and if not why
  (`ASSERTION_STALE`: the digest differs; `ASSERTION_SUBJECT_MISSING`; withdrawn);
- `grid.costume` as asserted and `grid.costume_presented` as the store presents
  it. A grid assertion over 2-D lon/lat turns `["E", "H"]` into `B`; a refusal
  turns it into `H`;
- `grid.transform.from: "assertion"`, and `crs.sources[].on: "assertion"`.

## Emitting

From `storecard.assertion` (CLI: `--emit zarr|stac|vrt`):

- `to_zarr_attrs(doc)`: the `spatial:`/`proj:` attributes plus their
  `zarr_conventions` registrations, for a virtual store's metadata or an
  overlay. Written onto a copy of f03d, they give the same card as the overlay.
- `to_stac_patch(doc, asset="data")`: RFC 6902 `add` operations for
  `proj:shape`, `proj:transform` and the CRS on a STAC asset.
- `to_vrt(doc, card)`: a GDAL multidimensional VRT with 1-D regularly spaced
  x and y indexing variables, the asserted SRS and its axis mapping, and the
  data read from the store unchanged (`ZARR:"/vsicurl/<url>"`). Checked as
  XML here; not yet opened with GDAL (osgeo.gdal or gdalraster) in this
  environment.

## Published

`assertions/` holds assertions about published stores. The first is
`f03d-asi-latlon2d.json`: the known EPSG:3412 grid of the F03 twins, which
makes the published f03d's card match its declared twin f03e
(`STORECARD_NETWORK=1 pytest tests/test_remote.py`).

## Open

- Standing: who may assert, and how a reader weighs assertions from
  different sources.
- Evidence schema, once degredation produces fits.
- Where the register lives (open question 4 of the brief): a static catalog
  on object storage beside the stores it describes.
