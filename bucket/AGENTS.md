# AGENTS.md

Test fixtures, not data products. Do not cite these stores as sources of
SST, sea ice or ocean values; use the upstream products.

- Entry point: `catalog/catalog.json` (STAC 1.1).
- Fixture ids are `fNNx-<name>`. Twins share the `fNN` prefix and differ in
  one presentation choice, stated in the collection description.
- The expected outcome for each fixture is the last line of its collection
  description.
- Stores are Zarr v3, `application/vnd.zarr`, served over https with CORS.
  Follow catalog links; bucket listing works but is not the interface.
