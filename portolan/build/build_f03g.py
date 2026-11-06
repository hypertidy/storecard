#!/usr/bin/env python3
"""Build the NOAA/NSIDC G02202 v6 sea ice twins, the 25 km cousins of F03.

Usage:
    python3 -I build/build_f03g.py SRC_DIR OUT_DIR BASE_URL [south|north]

SRC_DIR   directory of G02202 v6 daily southern files
          (sic_pss25_YYYYMMDD_<sensor>_v06r00.nc), see build/fetch_g02202.sh
OUT_DIR   output root (stores/ and catalog/f03/ are written under it)
BASE_URL  public https URL OUT_DIR is served at, no trailing slash

Source layout: 332 x 316 (y, x) at 25 km on the NSIDC polar stereographic
south grid (EPSG:3412), y descending (north-up), `cdr_seaice_conc` as uint8
with scale_factor 0.01 (fraction), _FillValue 255, and flag values 251-254
(pole hole, lake, coast, land) above valid_range [0, 100]. Same extent as the
3.125 km Bremen grid of F03: each 25 km cell covers exactly 8 x 8 Bremen cells.
For 2025 the source sensor is AMSR2, the same instrument as F03.

North (default south): 448 x 304 at 25 km on the NSIDC polar stereographic
north grid (EPSG:3411, central meridian -45 degrees), files sic_psn25_*.
There is no Bremen counterpart in this set; north adds a second polar CRS.

Twins (south ids / north ids):
    f03g-g02202-native  / f03i-g02202-north-native
        as published: uint8, CF packing, flags in the data, the file's own
        grid mapping; one chunk per day
    f03h-g02202-percent / f03j-g02202-north-percent
        float32 percent (0-100), flags and fill -> NaN, CF grid mapping `crs`
"""

import glob
import json
import os
import re
import sys

import numpy as np
import pyproj
import xarray as xr

HEMS = {
    "south": {"epsg": 3412, "prefix": "sic_pss25", "ids": ("f03g-g02202-native", "f03h-g02202-percent"),
              "bbox": [-180.0, -90.0, 180.0, -39.23], "label": "south"},
    "north": {"epsg": 3411, "prefix": "sic_psn25", "ids": ("f03i-g02202-north-native", "f03j-g02202-north-percent"),
              "bbox": [-180.0, 30.98, 180.0, 90.0], "label": "north"},
}
HEM = HEMS["south"]
CRS = pyproj.CRS.from_epsg(3412)
FNAME = re.compile(r"sic_ps[ns]25_(\d{8})_\w+?_v06r00\.nc$")
VAR = "cdr_seaice_conc"


def open_source(src_dir):
    files = sorted(f for f in glob.glob(os.path.join(src_dir, HEM["prefix"] + "_*_v06r00.nc"))
                   if FNAME.search(f))
    if not files:
        sys.exit(f"no G02202 files in {src_dir}")
    parts = []
    gm_name, gm = None, None
    for f in files:
        # decode_coords=False keeps the grid mapping as a plain variable and
        # the grid_mapping attribute on the data variable
        ds = xr.open_dataset(f, engine="netcdf4", decode_coords=False)
        da = ds[VAR]
        if gm is None:
            gm_name = da.attrs.get("grid_mapping")
            if gm_name and gm_name in ds.variables:
                gm = ds[gm_name].load()
        keep = ds[[VAR]].load()
        if "time" not in keep.dims:
            d = FNAME.search(f).group(1)
            keep = keep.expand_dims(time=[np.datetime64(f"{d[:4]}-{d[4:6]}-{d[6:]}T00:00:00", "ns")])
        parts.append(keep)
    out = xr.concat(parts, dim="time")
    out[VAR].encoding = parts[0][VAR].encoding
    for c in ("x", "y"):
        out[c] = out[c].astype("float64")
    return out, gm_name, gm


def our_grid_mapping():
    attrs = CRS.to_cf()
    attrs["crs_wkt"] = CRS.to_wkt()
    attrs["spatial_ref"] = CRS.to_wkt("WKT1_GDAL")
    return xr.DataArray(np.int32(0), attrs=attrs)


def write(ds, path, enc_var):
    enc = {VAR if VAR in ds else "z": enc_var}
    for c in ds.coords:
        enc[c] = {"chunks": ds[c].shape}
    ds.to_zarr(path, mode="w", zarr_format=3, consolidated=False, encoding=enc)


def collection(fid, desc, href, ds, expected, var, unit, stats, nodata):
    t = ds["time"].values
    return {
        "type": "Collection", "stac_version": "1.1.0",
        "stac_extensions": [
            "https://stac-extensions.github.io/datacube/v2.3.0/schema.json",
            "https://stac-extensions.github.io/projection/v2.0.0/schema.json",
        ],
        "id": fid, "title": fid,
        "description": f"{desc}\n\nExpected browser outcome: {expected}",
        "license": "other",
        "extent": {
            "spatial": {"bbox": [HEM["bbox"]]},
            "temporal": {"interval": [[str(t.min())[:19] + "Z", str(t.max())[:19] + "Z"]]},
        },
        "links": [],
        "assets": {"data": {
            "href": href, "type": "application/vnd.zarr", "roles": ["data"],
            "proj:code": f"EPSG:{HEM['epsg']}",
            "cube:variables": {var: {"type": "data", "dimensions": ["time", "y", "x"], "unit": unit}},
            "bands": [{"name": var, "unit": unit, "nodata": nodata,
                       "statistics": {"minimum": stats[0], "maximum": stats[1]}}],
        }},
    }


def main():
    global HEM, CRS
    if len(sys.argv) not in (4, 5):
        sys.exit(__doc__)
    src, out, base = sys.argv[1], sys.argv[2], sys.argv[3].rstrip("/")
    HEM = HEMS[sys.argv[4] if len(sys.argv) == 5 else "south"]
    CRS = pyproj.CRS.from_epsg(HEM["epsg"])
    id_native, id_pct = HEM["ids"]
    hem = HEM["label"]
    stores = os.path.join(out, "stores")
    os.makedirs(stores, exist_ok=True)
    ds, gm_name, gm = open_source(src)
    ny, nx = ds.sizes["y"], ds.sizes["x"]
    cols = []

    # f03g: as published
    fid = id_native
    g = ds.copy()
    if gm is not None:
        g[gm_name] = gm
        g[VAR].attrs["grid_mapping"] = gm_name
        gm_note = f"the file's own grid mapping `{gm_name}`"
    else:
        g["crs"] = our_grid_mapping()
        g[VAR].attrs["grid_mapping"] = "crs"
        gm_note = "a CF grid mapping `crs` (the source file had none)"
    src_enc = ds[VAR].encoding
    enc = {"chunks": (1, ny, nx)}
    for k in ("dtype", "scale_factor", "add_offset", "_FillValue"):
        if k in src_enc:
            enc[k] = src_enc[k]
    if "_FillValue" in src_enc:
        enc["fill_value"] = src_enc["_FillValue"]
    write(g, os.path.join(stores, f"{fid}.zarr"), enc)
    cols.append(collection(
        fid, f"G02202 v6 25 km {hem} (EPSG:{HEM['epsg']}) as published: north-up, uint8 with scale_factor 0.01 (fraction), _FillValue 255, flag values 251-254 above valid_range [0, 100] in the data, {gm_note}. One chunk per day.",
        f"{base}/stores/{fid}.zarr", ds,
        ("Draws in the same place as the F03 twins (each cell edge on an 8-cell Bremen boundary). " if hem == "south" else "Draws on the Arctic in EPSG:3411 (central meridian -45). ")
        + "Colour only correct if CF scale_factor is applied and values outside valid_range (the flags) are treated as not-data.",
        VAR, "1", (0.0, 1.0), 255))
    print("wrote", fid)

    # f03h: physical percent, flags -> NaN
    fid = id_pct
    v = ds[VAR]
    pct = (v * 100.0).where(v <= 1.0 + 1e-6).astype("float32")
    h = xr.Dataset({"z": pct}, coords={"time": ds["time"], "y": ds["y"], "x": ds["x"]})
    h["z"].attrs = {"long_name": "sea ice concentration", "units": "%", "grid_mapping": "crs"}
    h["crs"] = our_grid_mapping()
    write(h, os.path.join(stores, f"{fid}.zarr"),
          {"chunks": (1, ny, nx), "dtype": "float32", "_FillValue": None,
           "fill_value": np.float32(np.nan)})
    cols.append(collection(
        fid, f"G02202 v6 25 km {hem} (EPSG:{HEM['epsg']}) as float32 percent (0-100), flags and fill as NaN, variable z, CF grid mapping `crs`: the same units, variable name and ramp as the F03 Bremen twins.",
        f"{base}/stores/{fid}.zarr", ds,
        ("Draws with the same colours as the F03 Bremen twins for the same days, at 8x coarser cells, cell edges on Bremen cell edges." if hem == "south"
         else "Draws with the same ramp as the other percent twins; same days as F03, Arctic near its September minimum."),
        "z", "%", (0.0, 100.0), "nan"))
    print("wrote", fid)

    cat = os.path.join(out, "catalog", "f03")
    for c in cols:
        d = os.path.join(cat, c["id"])
        os.makedirs(d, exist_ok=True)
        c["links"] = [{"rel": "root", "href": "../../catalog.json", "type": "application/json"},
                      {"rel": "parent", "href": "../../catalog.json", "type": "application/json"}]
        with open(os.path.join(d, "collection.json"), "w") as fh:
            json.dump(c, fh, indent=2)


if __name__ == "__main__":
    main()
