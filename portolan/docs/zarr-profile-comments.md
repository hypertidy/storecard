# Zarr in Portolan: the grid should be declared, not inferred

Comments on the draft Zarr profile in portolan-sdi/portolan-spec PR 234, and
on the revision 2 evidence report attached to portolan-spec issue 132. The
reference implementation is portolan-sdi/portolan-browser PR 92.

This is an opinionated read. The short version is in the PR comment; this is
the reasoning behind it.

## Summary

- The design rule in the report is right: a client must decide from metadata
  alone, before it fetches a chunk. The draft does not yet follow its own rule,
  because it defines the grid by coordinate arrays, and coordinate arrays are
  data.
- A regular grid is six numbers and a CRS. The zarr-conventions `spatial:` and
  `proj:` conventions already carry exactly that, beside the `multiscales`
  convention the draft cites. The profile should require those and treat 1-D
  coordinate arrays as a derived convenience.
- The CRS requirement should be "one of `proj:code`, `proj:wkt2`,
  `proj:projjson`", as the STAC projection extension and the zarr proj
  convention already say, not "an EPSG code".
- "Physical vs virtual" is not visible in the array metadata. It is a
  transport question. The checks should apply to the logical store, whatever
  resolves its chunk keys to bytes.
- The test set has no polar, 0-360, antimeridian, ascending-Y or CF-packed
  stores, so several assumptions are untested. A fixture plan is attached
  (`docs/fixtures-plan.md` in this repo).
- Most of the rest is right and should stay: the amplification bound, per-level
  declarations in pyramids, display range as authored, codecs as a SHOULD
  list, CORS as a MUST, curvilinear grids out of scope for v1.

## 1. What the draft gets right

The report's central move is sound and unusual: every requirement is a
property of a metadata document, and a client refuses a store with a stated
reason for the cost of a few kilobytes. The measurement backs it (no refusal
in the test set transferred more than 0.6 MB). That is the right shape for a
spec whose readers are browsers and validators.

Several choices are better than what came before:

- The amplification bound states the cost a client pays, instead of a chunk
  layout a publisher must follow.
- Per-level factor and shape in a pyramid, instead of a mandated level order,
  accepts real stores as they are and makes the declaration self-checking.
- Treating the display range as authored, not recomputed, separates two things
  that are often confused.
- The codec list is a SHOULD derived from a library registry, not a spec
  choice.

The comments below are mostly about applying the design rule more strictly,
not about changing direction.

## 2. Declare the grid; do not make the client infer it

The draft requires 1-D, regular X and Y coordinate arrays, and recommends
float64 because float32 coordinates near the poles fail a regularity test.
The checklist tests regularity from "three cell centres".

This gets the representation backwards. A regular grid is fully described by
an affine transform (six numbers), a shape (two integers) and a CRS. A 1-D
coordinate array expands two of those numbers (origin and step) into n
numbers, then asks the client to compress them back and check that the
compression was lossless. Everything the report found wrong with coordinate
arrays follows from that:

- **Precision.** The MUR float32 case is not a publisher error. It is what
  happens when a regular axis is stored as a list of floats. Recommending
  float64 makes the symptom smaller; it does not remove it.
- **The design rule.** Reading coordinate values is a data read, not a metadata
  read. The "three cell centres" check fetches coordinate chunks. For a large
  1-D axis that is small, but it is still the kind of check the report says a
  client cannot make cheaply or fail cleanly.
- **Orientation.** "Y before X" fixes axis order. It says nothing about
  whether Y increases or decreases with index. Plenty of stores are stored
  bottom-up (south-up). With coordinate arrays the client must read values to
  find out; with a transform the sign of one coefficient says so.
- **Registration.** Coordinate arrays conventionally hold cell centres, but
  nothing in a bare array says so. A transform with `spatial:registration`
  says whether the origin is a corner or a centre.

zarr-conventions/spatial already defines `spatial:transform`, `spatial:shape`,
`spatial:bbox` and `spatial:registration`, and it composes with the proj and
multiscales conventions. The best-described store in the report's own test
set uses this form (the report notes `proj:code`, `spatial:transform` and
`spatial:shape` in its root attributes, and suggests no one has written that
convention down; it has been written down).

Proposed rule:

- A regular grid MUST be declared with `spatial:transform` and
  `spatial:shape`, per zarr-conventions/spatial, on the group or array.
- 1-D X and Y coordinate arrays MAY be present. Where both are present they
  MUST agree with the transform; a validator may check this, but a client
  MUST NOT need to.
- A store with only 1-D coordinate arrays and no transform SHOULD be accepted
  during a transition, with the regularity test as the fallback, and float64
  coordinates SHOULD be used in that case.

This also removes most of the regularity discussion from the spec. The
transform is regular by construction.

## 3. Use the conventions that exist

The draft names zarr-conventions/multiscales for pyramids, but for the CRS it
requires a CF grid mapping "as `spatial_ref` or `crs`". Two problems:

- **CF does not fix that name.** CF links a data variable to its grid mapping
  through the variable's `grid_mapping` attribute; the grid mapping variable
  can be called anything. `spatial_ref` is a naming habit of one Python
  toolchain, and `crs` is another common choice, but a CF-conformant store
  with a grid mapping named `polar_stereographic` fails the draft as written.
- **It ignores the sibling convention.** The proj convention puts
  `proj:code`, `proj:wkt2` or `proj:projjson` in store attributes and requires
  at least one. It is designed to compose with `spatial:` and `multiscales`.

Proposed rule:

- The store MUST declare its CRS with the zarr-conventions proj convention
  (`proj:code`, `proj:wkt2` or `proj:projjson`; at least one) on the group or
  array that carries `spatial:transform`, and MUST list the conventions it uses
  in `zarr_conventions`.
- A CF grid mapping, referenced from each data variable's `grid_mapping`
  attribute, SHOULD also be present for readers that do not know the zarr
  conventions. It MUST NOT be required to have a particular variable name.

The CF route stays as the compatibility path for existing readers. The
convention route is the one a validator can check from root attributes alone,
which is what the design rule asks for.

## 4. A CRS is not an EPSG code

The draft makes `proj:code` with an EPSG code a MUST on the asset. Under that
rule:

- The geostationary store in the test set, which the browser draws, does not
  conform.
- Rotated-pole grids, common in regional climate downscaling, do not conform.
- Any grid with project-specific parameters (many polar products, satellite
  swath-derived L3 grids) does not conform.

The STAC projection extension already allows `proj:code` from any authority
(not only EPSG), or `proj:wkt2`, or `proj:projjson`, with `proj:code` set to
null when no code exists. The zarr proj convention says the same. The draft's
own text recommends PROJJSON for grids outside EPSG, then makes them
non-conformant one sentence earlier.

Proposed rule: the asset MUST carry one of `proj:code`, `proj:wkt2` or
`proj:projjson`, and SHOULD carry `proj:code` when an authority code exists.
A grid without a code SHOULD carry `proj:projjson`, which states method
parameters directly, and MAY also carry `proj:wkt2`.

On the projection-method evidence: the draft and checklist cite a repository
that measures which projection methods each library supports. Use it as
evidence, and cite a pinned snapshot rather than the moving head, so the
spec's meaning does not change when that repository does. A spec should not
depend on one repository staying maintained.

## 5. Longitude, the antimeridian and direction

None of the 22 tested stores has longitudes in 0-360, and none crosses the
antimeridian. For ocean and climate data, 0-360 is not an edge case; it is
how a large share of global products are published, including widely used
daily SST analyses.

The profile should say, explicitly:

- In a geographic CRS, X values MAY lie in 0..360. Clients MUST NOT assume
  -180..180.
- A store whose extent crosses the antimeridian SHOULD be stored contiguously
  (for example, 120..290) rather than split and rolled. A 1-D axis that jumps
  from 180 to -180 is not regular, and the regularity check should refuse it
  with a reason.
- The STAC `bbox` for such a store follows the STAC and GeoJSON convention:
  west greater than east.

And, as in section 2: the direction of each spatial axis comes from the sign
of the transform. A store stored south-up is not defective.

## 6. Curvilinear is often a presentation, not a property

The draft excludes 2-D curvilinear coordinates, which is right for v1 where
the grid is genuinely curvilinear: ocean model native grids (tripolar,
ROMS-type) need a per-pixel warp, and that is a tile server's job.

But a large class of stores that look curvilinear are not. Many sea ice and
polar products, and many satellite L3 products on polar stereographic grids,
are regular in a projected CRS and ship 2-D longitude and latitude arrays as
a convenience. Their grid is six numbers in EPSG:3412 or EPSG:3031; the 2-D
arrays are the same grid expanded into geographic coordinates. Refusing them
as "curvilinear" refuses a presentation, not a grid.

Proposed text: a grid that is regular in some CRS MUST be declared in that CRS
(per sections 2 and 3). 2-D geographic coordinate arrays MAY accompany it and
MUST NOT be the only grid declaration. A store whose grid is not regular in
any CRS is out of scope for this profile.

That turns a large group of refusals into conforming stores, at the cost of
one metadata block the publisher writes once.

## 7. Physical and virtual are transports, not kinds of store

The draft scopes the profile to physical stores and defers virtual and
transactional stores, while noting that clients are expected to read them.
The report's own evidence shows that this deferral is a scoping choice, not a
technical one: two of the 11 drawing stores are Icechunk repositories, and one
reads virtual references into netCDF files on another host.

The cleaner framing is that "virtual" is not visible in the array metadata at
all. A virtual store presents the same `zarr.json`, the same dimensions, the
same codecs and the same attributes as a physical one. What differs is how a
chunk key resolves to bytes: a direct object key, an Icechunk manifest entry,
or a row in a byte-reference table (path, offset, length, keyed by chunk
index). The draft already recognises this without saying so:

- its CORS rule reaches every referenced file of a virtual store (a transport
  property);
- its codec rule notes that a virtual store inherits the compression of the
  files it references (a logical property, declared in the codec chain like
  any other).

Proposed text: the requirements of this profile apply to the logical store:
its metadata, codecs and attributes. How chunk keys are resolved to bytes
(directly, through a manifest, or through a reference table) is a transport
concern outside this profile, except that every host serving bytes MUST
satisfy the CORS rule.

This keeps the deferral exactly as scoped: no new conformance surface, no
commitment to any particular virtual format. It just avoids defining a
virtual store that passes every check as non-conformant by category. It also
means a flat byte-reference model, or any other reference format, can come in
later as a transport profile without reopening this one.

## 8. Packing, fill values and units

Two things the draft does not say, both of which a client has to get right
before it can apply a display range:

- **CF packing vs codecs.** Many existing stores pack values as integers with
  CF `scale_factor` and `add_offset` in attributes, not with a
  `scale_offset` codec. The codec list includes `scale_offset`, but attribute
  packing is a different mechanism. The profile should say which it expects,
  and that `statistics` in `bands` are in unpacked (physical) units either
  way. Otherwise the same store, packed or unpacked, gets two different colour
  ramps.
- **Which fill value wins.** A Zarr array has a `fill_value` in its metadata
  (the value of a missing chunk). CF has `_FillValue` and `missing_value`.
  STAC `bands` has `nodata`. These can differ, and often do. The profile
  should give a precedence order, for example `bands.nodata`, then CF
  `_FillValue`, then Zarr `fill_value`.

## 9. Pyramids: declare per-level transforms

Requiring each level to declare its own factor and shape is the right call.
A per-level `spatial:transform` is better still, and the multiscales and
spatial conventions are designed to compose that way: each level's
georeferencing comes from its own transform, not from the scale factor. A
factor alone leaves open how levels align (corner or centre) when a dimension
has odd length. A transform per level settles order, alignment and extent in
one field.

Proposed: each level MUST declare its shape and SHOULD declare its own
`spatial:transform`; where it does, the transform is authoritative and the
factor is informative.

The append rule (append to the level-0 group, never the store root) is a
good catch and should stay.

## 10. Amplification: a MUST at the top, a SHOULD at the bottom

The amplification bound is the best idea in the draft. The open question is
the limit (8 refuses a store chunked for animation by month at 12; 16 admits
it at twice the cost per tile) and how to treat stores chunked for
time-series analysis.

A suggestion that resolves both: apply the bound as a MUST to the pyramid
levels, and as a SHOULD to level 0.

- Overview levels are new arrays anyway, written once by the publisher. They
  can be chunked for display at no cost to analysis users.
- Level 0 can stay chunked for time-series access. The world view and the
  zoom-out views, which are what a catalog browser draws first, stay cheap.
- The draft's "SHOULD be published beside a display-chunked copy" becomes
  "the pyramid is the display-chunked copy", which needs no second store.

A client that zooms to full resolution on an analysis-chunked level 0 pays
for it, and can warn. That is a fair trade, and it is the publisher's to make.

## 11. Zarr v2

The draft requires Zarr v3. Several drawing stores in the test set are v2, and
a lot of existing reference-based data materialises v2 metadata. Allowing v2
costs a second metadata path and the C-order check the draft already has.

Proposed: stores SHOULD be Zarr v3 and MAY be Zarr v2 with `order: "C"`. The
zarr conventions above are v3 attributes; a v2 store meets the grid and CRS
rules through the CF route during a transition.

## 12. The test set

The report's evidence is strong where it reaches, and the reach is
mid-latitude and mostly geographic or Web Mercator. Untested cases that the
rules above touch:

- polar stereographic, with the pole inside the data (and a non-WGS84
  ellipsoid);
- 0-360 longitude, and a store crossing the antimeridian;
- ascending Y;
- CF-packed integer variables;
- a regular projected grid published with 2-D geographic coordinates;
- the same logical array delivered physically and virtually.

Each of these comes up all the time in ocean and polar data. A fixture plan
built as twins (the same data in two presentations that should draw
identically) is in `docs/fixtures-plan.md`. It is meant to run
through the existing browser harness unchanged.

## 13. Proposed replacement text (Grid and CRS sections)

**Grid.** A client must index the samples from metadata alone, so:

- A regular grid MUST be declared with `spatial:transform` and `spatial:shape`
  per zarr-conventions/spatial, on the group or array, and SHOULD declare
  `spatial:registration`. The transform is authoritative.
- The spatial axes MUST be the last two dimensions of every renderable array,
  Y before X. Axis direction is given by the transform; either direction is
  valid.
- 1-D X and Y coordinate arrays MAY be present and MUST agree with the
  transform. A store with coordinate arrays and no transform SHOULD be
  accepted during a transition; such coordinates SHOULD be float64.
- In a geographic CRS, X MAY lie in 0..360. A grid crossing the antimeridian
  SHOULD be stored contiguously.
- A grid regular in some CRS MUST be declared in that CRS. 2-D geographic
  coordinate arrays MAY accompany it. A grid not regular in any CRS is outside
  this profile.
- Arrays MUST be stored row-major (C order).

**Coordinate reference system.** The store MUST carry one of `proj:code`,
`proj:wkt2` or `proj:projjson` per the zarr-conventions proj convention, beside
`spatial:transform`, and MUST list the conventions used in `zarr_conventions`.
Each data variable SHOULD also reference a CF grid mapping through its
`grid_mapping` attribute; the grid mapping variable's name is not constrained.
The asset MUST carry one of `proj:code`, `proj:wkt2` or `proj:projjson`, and
SHOULD carry `proj:code` where an authority code exists. A CRS without a code
SHOULD be given as `proj:projjson`.

**Scope.** These requirements apply to the logical store. How chunk keys
resolve to bytes is a transport concern outside this profile, except that
every host serving bytes MUST satisfy the CORS requirement.

## References

- portolan-sdi/portolan-spec issue 132 and PR 234
- portolan-sdi/portolan-browser PR 92 (`docs/zarr.md` on that branch)
- zarr-conventions/spatial: https://github.com/zarr-conventions/spatial
- zarr-conventions proj convention (geo-proj), as composed in the GeoZarr
  minispec: https://eopf-explorer.github.io/data-model/geozarr-minispec/
- zarr-conventions/multiscales: https://github.com/zarr-conventions/multiscales
- STAC projection extension: https://github.com/stac-extensions/projection
- CF Conventions, grid mappings:
  https://cfconventions.org/cf-conventions/cf-conventions.html#grid-mappings-and-projections
