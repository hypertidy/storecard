# rasterwise cases

[rgdal-dev/rasterwise](https://github.com/rgdal-dev/rasterwise) is the home of
the problem-file collection: netCDF and HDF files that broke readers, with
their notes and issues. It holds the superset and its manifest. storecard
consumes it: each file becomes a case with a card, findings, and an expected
assertion or refusal.

`cards.jsonl` holds prototype cards for the 34 netCDF files recoverable from
the intact rasterwise release bundles (v0.0.6 to v0.0.12, plus what could be
salvaged from the truncated v0.5.0), produced by `proto/protocard.py`. They
are keyed by path for now; once the rasterwise manifest exists they should be
keyed by its sha256 so cards follow content, not paths.

The findings are first-pass heuristics. Notable already:

- `LAT_MERCATOR_SPACED`: the Aviso MADT file and ACCfronts, the regular
  Mercator grid published as rectilinear lon/lat (gproj's `mercator_devolved`)
- `AXES_X_BEFORE_Y`: `swapped/3A-DAY.nc`
- `GRID_2D_LONLAT_ONLY`: candidates for a regula fit (cryptic curvilinear):
  `nhsce_v01r01_19661004_20140203.nc`, `hmr_ita.nc`, `test.nc_60/test.nc`,
  `get1index_64/test.nc`, `bad_examples_62/example1.nc`
- `GRID_2D_WITH_PROJECTED_1D`: the rotated-pole (`ob_tran`) and
  EURO-CORDEX files, whose lon/lat are derived from projected axes
