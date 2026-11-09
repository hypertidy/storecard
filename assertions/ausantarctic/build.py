"""Build the CRS assertions for the ausantarctic scratch virtual stores.

These are the tier 1 datasets of the raadtools contract (the raadtools
ledger in rgdal-dev/rasterwise, ledger/raadtools.csv): each store declares
its grid by regular 1-D coordinates but states no CRS, so the card finds
CRS_NOT_DECLARED. Each assertion restates the transform from the axes and
supplies the CRS, with the evidence for it. One document per dataset, form
and variable, since an assertion is keyed to one store's metadata digest.

Run from the repository root (reads metadata over the network):

    python assertions/ausantarctic/build.py

and check the result with STORECARD_NETWORK=1 pytest tests/test_remote.py.
"""

import json
import pathlib
import sys

from storecard import assertion as A
from storecard import card

SCRATCH = "https://data.source.coop/ausantarctic/ausantarctic-scratch/"
FORMS = ("icechunk", "kerchunk")
BY = {"name": "storecard ausantarctic tier 1", "kind": "known source CRS"}
LEDGER = "https://github.com/rgdal-dev/rasterwise/blob/main/ledger/raadtools.csv"

PLAN_SRS = ("the source files' own grid mapping, as GDAL reads it into the "
            "dataset's plan.vrt <SRS>; the virtual store does not carry it")

# dataset path: (variables, CRS, crs_axes, evidence)
DATASETS = {
    "oisst/oisst-v2.1-daily": (
        ["sst", "anom", "err", "ice"], "EPSG:4326", ("y", "x"),
        {"crs_from": "convention: NCEI OISST v2.1 AVHRR netCDF has no grid_mapping and the "
                     "plan.vrt has no SRS; the product is documented as a regular 0.25 degree "
                     "latitude/longitude grid, read as EPSG:4326 by raadtools",
         "note": "longitude 0 to 360, latitude ascending (south-up storage)"}),
    "seaice/g02202-v6-daily-south": (
        ["cdr_seaice_conc"], "EPSG:3412", ("x", "y"),
        {"crs_from": PLAN_SRS,
         "srs": "PROJCRS NSIDC Sea Ice Polar Stereographic South (Hughes 1980), ID EPSG 3412",
         "plan": SCRATCH + "seaice/g02202-v6-daily-south/plan.vrt"}),
    "seaice/g02202-v6-daily-north": (
        ["cdr_seaice_conc"], "EPSG:3411", ("x", "y"),
        {"crs_from": PLAN_SRS,
         "srs": "PROJCRS NSIDC Sea Ice Polar Stereographic North (Hughes 1980), ID EPSG 3411",
         "plan": SCRATCH + "seaice/g02202-v6-daily-north/plan.vrt"}),
    "seaice/asi-amsr2-v5.4-daily-south": (
        ["z"], "EPSG:3976", ("x", "y"),
        {"crs_from": PLAN_SRS,
         "srs": "WGS 84 / NSIDC Sea Ice Polar Stereographic South, AUTHORITY EPSG 3976",
         "plan": SCRATCH + "seaice/asi-amsr2-v5.4-daily-south/plan.vrt",
         "note": "the files label WGS 84 (raad.virtualize config/seaice-asi-amsr2.sh); the "
                 "Hughes 1980 form EPSG:3412 also fits this grid to 1e-4 cell (see "
                 "f03d-asi-latlon2d.json), so the label decides"}),
    "ghrsst/ghrsst-mur-cog-analysed_sst": (
        ["analysed_sst"], "EPSG:4326", ("y", "x"),
        {"crs_from": "the source COGs (ausantarctic/ghrsst-mur-v2) declare EPSG:4326, origin "
                     "-179.995, 89.995, pixel 0.01 (gdalinfo, GDAL 3.8.4)",
         "note": "base level only; the overview arrays (analysed_sst_x2 ...) are not asserted"}),
}


def main(out=pathlib.Path(__file__).parent):
    n = 0
    for ds, (variables, code, crs_axes, evidence) in DATASETS.items():
        for form in FORMS:
            c = card(SCRATCH + ds + "/" + form, probe_hosts=False)
            for var in variables:
                doc = A.crs_assertion(
                    c, var, {"proj:code": code}, crs_axes=crs_axes,
                    evidence={**evidence, "dataset": ds.split("/")[1], "era": "all",
                              "ledger": LEDGER},
                    by=BY)
                path = out / ds.split("/")[1] / f"{form}-{var}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(doc, indent=1) + "\n")
                n += 1
                print(path.relative_to(out), doc["asserts"]["spatial:transform"], file=sys.stderr)
    print(f"{n} assertions", file=sys.stderr)


if __name__ == "__main__":
    main()
