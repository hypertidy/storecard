#!/usr/bin/env python3
"""Build the F03 Bremen ASI AMSR2 sea ice twins (southern polar stereographic).

Usage:
    python3 -I build/build_f03.py SRC_DIR OUT_DIR BASE_URL

SRC_DIR   directory of ASI AMSR2 v5.4 3.125 km daily netCDF files
          (asi-AMSR2-s3125-YYYYMMDD-v5.4.nc), see build/fetch_asi.sh
OUT_DIR   output root (stores/ and catalog/f03/ are written under it)
BASE_URL  public https URL OUT_DIR is served at, no trailing slash

Source layout: 2656 x 2528 (y, x) at 3125 m on the NSIDC polar stereographic
south grid (EPSG:3412, Hughes 1980 ellipsoid), y ascending (south-up),
float32 `z` in percent with NaN fill, no grid mapping, one row per netCDF
chunk.

Twins (one presentation change each):
    f03a-asi-native        as published (south-up, variable z) plus a CF grid
                           mapping named `crs`; 512 x 512 chunks
    f03b-asi-rowchunk      f03a chunked like the source files: one row per chunk
    f03c-asi-transform     north-up, spatial:/proj: conventions with proj:code,
                           CF grid mapping, 3-level multiscales pyramid
    f03d-asi-latlon2d      2-D lon/lat arrays only: no x/y, no grid mapping
    f03e-asi-projjson      north-up, spatial:transform + proj:projjson only,
                           no CF grid mapping and no proj:code
    f03f-asi-gridmap-named f03a with the CF grid mapping variable named
                           `polar_stereographic`, referenced by grid_mapping
"""

import glob
import json
import os
import re
import sys

import numpy as np
import pyproj
import xarray as xr
import zarr

CHUNK = 512
CRS = pyproj.CRS.from_epsg(3412)
WKT2 = CRS.to_wkt()
WKT1 = CRS.to_wkt("WKT1_GDAL")
PROJJSON = CRS.to_json_dict()

CONV_SPATIAL = {
    "uuid": "689b58e2-cf7b-45e0-9fff-9cfc0883d6b4",
    "schema_url": "https://raw.githubusercontent.com/zarr-conventions/spatial/refs/tags/v1/schema.json",
    "spec_url": "https://github.com/zarr-conventions/spatial/blob/v1/README.md",
    "name": "spatial:", "description": "Spatial coordinate information",
}
CONV_PROJ = {
    "uuid": "f17cb550-5864-4468-aeb7-f3180cfb622f",
    "schema_url": "https://raw.githubusercontent.com/zarr-conventions/proj/refs/tags/v0.1/schema.json",
    "spec_url": "https://github.com/zarr-conventions/proj/blob/v0.1/README.md",
    "name": "proj:", "description": "Coordinate reference system information for geospatial data",
}
CONV_MULTISCALES = {
    "uuid": "d35379db-88df-4056-af3a-620245f8e347",
    "spec_url": "https://github.com/zarr-conventions/multiscales",
    "name": "multiscales", "description": "Multiscale layout of zarr datasets",
}

FNAME = re.compile(r"asi-AMSR2-s3125-(\d{8})-v5\.4\.nc$")


def open_source(src_dir):
    files = sorted(f for f in glob.glob(os.path.join(src_dir, "asi-AMSR2-s3125-*-v5.4.nc"))
                   if FNAME.search(f))
    if not files:
        sys.exit(f"no ASI files in {src_dir}")
    parts = []
    for f in files:
        d = FNAME.search(f).group(1)
        ds = xr.open_dataset(f, engine="netcdf4")[["z"]].load()
        ds = ds.expand_dims(time=[np.datetime64(f"{d[:4]}-{d[4:6]}-{d[6:]}T12:00:00", "ns")])
        parts.append(ds)
    ds = xr.concat(parts, dim="time")
    ds["z"] = ds["z"].astype("float32")
    ds["z"].attrs = {"long_name": "sea ice concentration", "units": "%"}
    for c in ("x", "y"):
        ds[c] = ds[c].astype("float64")
        ds[c].attrs = {"standard_name": f"projection_{c}_coordinate", "units": "m"}
    ds["z"].encoding = {}
    return ds


def grid_mapping_var():
    attrs = CRS.to_cf()
    attrs["crs_wkt"] = WKT2
    attrs["spatial_ref"] = WKT1
    return xr.DataArray(np.int32(0), attrs=attrs)


def with_grid_mapping(ds, name="crs"):
    ds = ds.copy()
    ds[name] = grid_mapping_var()
    ds["z"].attrs["grid_mapping"] = name
    return ds


def encoding(ds, chunks):
    enc = {"z": {"chunks": chunks, "dtype": "float32", "_FillValue": None,
                 "fill_value": np.float32(np.nan)}}
    for c in ds.coords:
        enc[c] = {"chunks": ds[c].shape}
    for v in ds.data_vars:
        if v != "z":
            enc[v] = {}
    return enc


def write(ds, path, chunks=(1, CHUNK, CHUNK), group=None, mode="w"):
    ds.to_zarr(path, group=group, mode=mode, zarr_format=3, consolidated=False,
               encoding=encoding(ds, chunks))


def transform_of(ds):
    x = ds["x"].values
    y = ds["y"].values
    dx = float(np.round((x[-1] - x[0]) / (x.size - 1), 6))
    dy = float(np.round((y[-1] - y[0]) / (y.size - 1), 6))
    return ([dx, 0.0, float(x[0] - dx / 2), 0.0, dy, float(y[0] - dy / 2)],
            [int(y.size), int(x.size)])


def spatial_attrs(t, s):
    a, _, c, _, e, f = t
    ny, nx = s
    xs = sorted([c, c + a * nx])
    ys = sorted([f, f + e * ny])
    return {"spatial:dimensions": ["y", "x"], "spatial:transform_type": "affine",
            "spatial:transform": t, "spatial:shape": s,
            "spatial:bbox": [xs[0], ys[0], xs[1], ys[1]], "spatial:registration": "pixel"}


def build_pyramid(ds, path, crs_attrs, cf=True):
    levels = [ds]
    for f in (2, 4):
        levels.append(ds.coarsen(y=f, x=f, boundary="trim").mean().astype("float32"))
    layout = []
    for i, lev in enumerate(levels):
        if cf:
            lev = with_grid_mapping(lev)
        write(lev, path, group=str(i), mode="w" if i == 0 else "a")
        t, s = transform_of(lev)
        g = zarr.open_group(path, path=str(i), mode="a", zarr_format=3)
        g.attrs.update({**spatial_attrs(t, s), **crs_attrs,
                        "zarr_conventions": [CONV_SPATIAL, CONV_PROJ]})
        entry = {"asset": str(i), "spatial:transform": t, "spatial:shape": s}
        if i:
            fac = float(2 ** i)
            entry.update({"derived_from": "0", "resampling_method": "mean",
                          "transform": {"scale": [fac, fac], "translation": [0.0, 0.0]}})
        layout.append(entry)
    t0, s0 = transform_of(levels[0])
    root = zarr.open_group(path, mode="a", zarr_format=3)
    root.attrs.update({"multiscales": {"layout": layout}, **spatial_attrs(t0, s0), **crs_attrs,
                       "zarr_conventions": [CONV_MULTISCALES, CONV_SPATIAL, CONV_PROJ]})


def add_conventions(path, ds, crs_attrs):
    t, s = transform_of(ds)
    root = zarr.open_group(path, mode="a", zarr_format=3)
    root.attrs.update({**spatial_attrs(t, s), **crs_attrs,
                       "zarr_conventions": [CONV_SPATIAL, CONV_PROJ]})


def latlon2d(ds):
    xx, yy = np.meshgrid(ds["x"].values, ds["y"].values)
    tr = pyproj.Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    lon, lat = tr.transform(xx, yy)
    out = ds[["z"]].drop_vars(["x", "y"])
    out = out.assign_coords(
        lon=(("y", "x"), lon.astype("float64"), {"standard_name": "longitude", "units": "degrees_east"}),
        lat=(("y", "x"), lat.astype("float64"), {"standard_name": "latitude", "units": "degrees_north"}))
    out["z"].attrs["coordinates"] = "lon lat"
    return out


def collection(fid, desc, href, ds, expected, proj, dims, transform=None):
    t = ds["time"].values
    asset = {
        "href": href, "type": "application/vnd.zarr", "roles": ["data"],
        **proj,
        "cube:variables": {"z": {"type": "data", "dimensions": dims, "unit": "%"}},
        "bands": [{"name": "z", "unit": "%", "nodata": "nan",
                   "statistics": {"minimum": 0.0, "maximum": 100.0}}],
    }
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
            "spatial": {"bbox": [[-180.0, -90.0, 180.0, -39.23]]},
            "temporal": {"interval": [[str(t.min())[:19] + "Z", str(t.max())[:19] + "Z"]]},
        },
        "links": [],
        "assets": {"data": asset},
    }


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    src, out, base = sys.argv[1], sys.argv[2], sys.argv[3].rstrip("/")
    stores = os.path.join(out, "stores")
    os.makedirs(stores, exist_ok=True)

    native = open_source(src)                       # y ascending, as published
    north = native.isel(y=slice(None, None, -1))    # north-up
    dims = ["time", "y", "x"]
    code = {"proj:code": "EPSG:3412"}
    pj = {"proj:code": None, "proj:projjson": PROJJSON}
    same = "Draws identically to the other f03 twins."
    cols = []

    def href(fid):
        return f"{base}/stores/{fid}.zarr"

    fid = "f03a-asi-native"
    write(with_grid_mapping(native), os.path.join(stores, f"{fid}.zarr"))
    cols.append(collection(fid, "ASI AMSR2 3.125 km as published: south-up (y ascending), variable z, plus a CF grid mapping `crs` (EPSG:3412, WKT2 crs_wkt, WKT1 spatial_ref).",
                           href(fid), native, same + " Spec draft: fails overviews MUST (30 chunks at level 0).", code, dims))

    fid = "f03b-asi-rowchunk"
    write(with_grid_mapping(native), os.path.join(stores, f"{fid}.zarr"), chunks=(1, 1, native.sizes["x"]))
    cols.append(collection(fid, "f03a chunked like the source netCDF files: one row (1 x 2528) per chunk, as the virtual store over the originals is.",
                           href(fid), native, "May be refused by an amplification check; if drawn, identical to f03a. Spec draft: a 256 px tile reads about 10x the samples it draws, over the bound of 8.", code, dims))

    fid = "f03c-asi-transform"
    build_pyramid(north, os.path.join(stores, f"{fid}.zarr"), code, cf=True)
    cols.append(collection(fid, "North-up, zarr-conventions spatial:transform and proj:code EPSG:3412, CF grid mapping, 3-level multiscales pyramid (levels 1, 2 are means).",
                           href(fid), north, same + " Spec draft: conforms.", code, dims))

    fid = "f03d-asi-latlon2d"
    write(latlon2d(north), os.path.join(stores, f"{fid}.zarr"))
    cols.append(collection(fid, "North-up, 2-D lon/lat coordinate arrays only: no x/y, no grid mapping, no transform. The grid is regular in EPSG:3412 but nothing says so.",
                           href(fid), north, "Refused as a curvilinear grid (the draft excludes 2-D coordinates), although the grid is regular in EPSG:3412.", {"proj:code": None}, dims))

    fid = "f03e-asi-projjson"
    p = os.path.join(stores, f"{fid}.zarr")
    write(north, p)
    add_conventions(p, north, {"proj:projjson": PROJJSON})
    cols.append(collection(fid, "North-up, CRS only as zarr-conventions proj:projjson and spatial:transform in the store; no CF grid mapping, no proj:code.",
                           href(fid), north, same + " Tests whether the zarr proj/spatial conventions alone place the grid; a reader that only knows CF grid mappings refuses it.", pj, dims))

    fid = "f03f-asi-gridmap-named"
    write(with_grid_mapping(native, name="polar_stereographic"), os.path.join(stores, f"{fid}.zarr"))
    cols.append(collection(fid, "f03a with the CF grid mapping variable named `polar_stereographic` (referenced by z:grid_mapping), not `crs` or `spatial_ref`.",
                           href(fid), native, same + " Spec draft as written: non-conformant (requires the name spatial_ref or crs); CF-valid.", code, dims))

    cat = os.path.join(out, "catalog", "f03")
    for c in cols:
        d = os.path.join(cat, c["id"])
        os.makedirs(d, exist_ok=True)
        c["links"] = [{"rel": "root", "href": "../../catalog.json", "type": "application/json"},
                      {"rel": "parent", "href": "../../catalog.json", "type": "application/json"}]
        with open(os.path.join(d, "collection.json"), "w") as fh:
            json.dump(c, fh, indent=2)
        print("wrote", c["id"])


if __name__ == "__main__":
    main()
