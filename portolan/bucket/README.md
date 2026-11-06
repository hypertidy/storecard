# portolan-fixtures

Zarr conformance fixtures for polar, ocean and virtual cases, built as twins:
the same data in presentations that should draw identically. Context:
portolan-sdi/portolan-spec issue 132 and PR 234.

- `catalog/catalog.json`: STAC catalog, one collection per fixture. Each
  collection description ends with its expected browser outcome.
- `stores/`: physical Zarr v3 fixtures.
- `virtual/`: copies of index-only virtual stores (kerchunk, Icechunk, flat
  byte-reference tables, GDAL multidim VRT). Their references point at the
  upstream hosts, not at this bucket.

Built by scripts in the portolan-fixtures repository; this bucket is a cache
of their output and can be rebuilt from them.
