# Finding codes

The codes `storecard.card()` emits, in the card's `findings` list. Each is a
fact read from metadata (or from coordinate values), not a judgement: rule
sets decide which ones matter to a given reader. Codes shared with the
rasterwise cases (`cases/*/case.yaml`, `findings:`) keep the same name and
meaning.

| Code | Meaning | Fixture that shows it |
| ---- | ------- | --------------------- |
| `Y_ASCENDING` | the y (or latitude) axis increases with index: south-up | f01a, f03a |
| `LON_0_360` | a longitude axis has values above 180 | f01a |
| `LON_BELOW_MINUS_180` | a longitude axis has values below -180 | f08a (xt_ocean from -279.5) |
| `AXES_X_BEFORE_Y` | the x dimension comes before the y dimension | rasterwise `gpm-dpr-swapped-axes` |
| `COORD_IRREGULAR` | a spatial 1-D axis is monotonic but not evenly spaced (and, for latitude, not evenly spaced in Mercator either) | f08a (yt_ocean) |
| `COORD_NONMONOTONIC` | a spatial 1-D axis changes direction | fixtures-plan f02b |
| `COORD_NONFINITE` | a spatial 1-D axis holds NaN or Inf | rasterwise `laea-globe-transposed-inf-lonlat` |
| `LAT_MERCATOR_SPACED` | latitude is irregular in degrees but evenly spaced in Mercator y: costume D of regular-in-what | rasterwise `aviso-mercator-as-lonlat` |
| `GRID_2D_LONLAT_ONLY` | the only positions are 2-D longitude and latitude: a candidate for a grid fit (costume E or H) | f03d |
| `GRID_2D_WITH_PROJECTED_1D` | 2-D longitude and latitude beside 1-D projected or rotated axes | rasterwise `regcm-lcc-cross-dot-points` |
| `NOMINAL_AXES_DISAGREE` | 2-D positions beside 1-D longitude and latitude axes, and the 2-D positions are more than half a cell from the axes' outer product somewhere on the sample lines: the 1-D axes are nominal | f08c (tripolar fold) |
| `COORDS_NAMED_MISSING` | a `coordinates` attribute names arrays the store does not have | f08a |
| `GRID_MAPPING_NAMED_MISSING` | a `grid_mapping` attribute names an array the store does not have | |
| `CRS_NOT_DECLARED` | no CRS in the store: no CF grid mapping, no `proj:` attribute (a STAC `proj:code` is recorded but does not count) | f03d, f08a |
| `PROJECTED_NO_GRID_MAPPING` | projected x/y axes and no CRS | |
| `TRANSFORM_SHAPE_MISMATCH` | `spatial:shape` differs from the array's spatial shape | |
| `FILL_DISAGREE` | the fill sources (Zarr `fill_value`, CF `_FillValue`, `missing_value`, STAC `nodata`) give different values once cast to the stored dtype | xarray's Zarr v3 default: `fill_value` 0 beside `_FillValue` -999 |
| `FILL_NOT_REPRESENTABLE` | a declared fill value cannot be held exactly by the stored dtype, so a comparison at the declared precision never matches | f08a (STAC nodata -1e20 against float32) |
| `GROUP_NOT_LISTABLE` | the store's arrays could not be listed (no consolidated metadata, a host that does not list) and were found from hints | |
| `OPEN_FAILED` | the store could not be opened (from `proto/protocard.py`) | |

Not yet emitted, but used by the rasterwise cases: `ARRAY_TRANSPOSED`,
`CHAR_DIM_DROPPED`, `CHUNKS_SPAN_BAND_DIM`, `DSG_NOT_GRID`,
`FILL_ATTR_NONSTANDARD`, `GRID_MAPPING_MISLABELLED`, `GRID_NO_COORDS`,
`ID_AS_COORDINATE`, `TRUNCATED`. A confirmed grid fit will turn
`GRID_2D_LONLAT_ONLY` into an assertion, with a code such as
`GRID_CRYPTIC_CURVILINEAR` (step 2 of the brief).
