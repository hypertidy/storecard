#!/usr/bin/env python3
"""Build the F01 OISST presentation twins as Zarr v3 stores, plus a STAC catalog.

Usage:
    python3 -I 03-build-f01.py SRC_DIR OUT_DIR BASE_URL

SRC_DIR   directory of OISST v2.1 daily netCDF files (oisst-avhrr-v02r01.*.nc)
OUT_DIR   local output root (stores/ and catalog/ are created under it)
BASE_URL  public https URL that OUT_DIR will be served at, no trailing slash,
          e.g. https://projects.pawsey.org.au/aad-derived/portolan-fixtures

Twins (same data, one presentation change each):
    f01a-oisst-native     lon 0..360, lat ascending, CF int16 packing
    f01b-oisst-ydesc      f01a with lat descending
    f01c-oisst-180        f01a with lon rolled to -180..180
    f01d-oisst-transform  f01b plus spatial:/proj: conventions and a 3-level
                          multiscales pyramid (levels 1 and 2 are float32 means)
    f01e-oisst-unpacked   f01b stored as float32 physical values, NaN fill
    f01f-oisst-nodata     f01b with bands[].nodata = -999 declared in STAC

All four carry a minimal CF grid mapping (variable "crs", referenced by
sst:grid_mapping) so the browser's CRS guard is not the thing under test.
"""

import glob
import json
import os
import sys

import numpy as np
import pyproj
import xarray as xr

CHUNK_XY = 360  # 720 x 1440 -> 2 x 4 inner chunks at level 0

# zarr-conventions registrations. Verify uuids and URLs against
# https://github.com/zarr-conventions before treating f01d as a reference.
CONV_SPATIAL = {
    "uuid": "689b58e2-cf7b-45e0-9fff-9cfc0883d6b4",
    "schema_url": "https://raw.githubusercontent.com/zarr-conventions/spatial/refs/tags/v1/schema.json",
    "spec_url": "https://github.com/zarr-conventions/spatial/blob/v1/README.md",
    "name": "spatial:",
    "description": "Spatial coordinate information",
}
CONV_PROJ = {
    "uuid": "f17cb550-5864-4468-aeb7-f3180cfb622f",
    "schema_url": "https://raw.githubusercontent.com/zarr-conventions/proj/refs/tags/v0.1/schema.json",
    "spec_url": "https://github.com/zarr-conventions/proj/blob/v0.1/README.md",
    "name": "proj:",
    "description": "Coordinate reference system information for geospatial data",
}
CONV_MULTISCALES = {
    "uuid": "d35379db-88df-4056-af3a-620245f8e347",
    "spec_url": "https://github.com/zarr-conventions/multiscales",
    "name": "multiscales",
    "description": "Multiscale layout of zarr datasets",
}

WKT_4326 = pyproj.CRS.from_epsg(4326).to_wkt()


def open_source(src_dir):
    files = sorted(glob.glob(os.path.join(src_dir, "oisst-avhrr-v02r01.*.nc")))
    if not files:
        sys.exit(f"no OISST files in {src_dir}")
    # keep CF packing on write: xarray re-encodes from the source encoding.
    # Plain open + concat, so dask is not needed.
    parts = [xr.open_dataset(f, engine="netcdf4")[["sst"]].load() for f in files]
    ds = xr.concat(parts, dim="time")
    ds["sst"].encoding = parts[0]["sst"].encoding
    return ds


def add_grid_mapping(ds):
    ds = ds.copy()
    ds["crs"] = xr.DataArray(np.int32(0), attrs={
        "grid_mapping_name": "latitude_longitude",
        "crs_wkt": WKT_4326,
        "spatial_ref": WKT_4326,
    })
    ds["sst"].attrs["grid_mapping"] = "crs"
    return ds


def encoding_for(ds, packed=True):
    enc = {}
    sst_enc = {"chunks": (1, 1, CHUNK_XY, CHUNK_XY)}
    if packed:
        src = ds["sst"].encoding
        for k in ("dtype", "scale_factor", "add_offset", "_FillValue"):
            if k in src:
                sst_enc[k] = src[k]
        # make the Zarr fill_value (missing chunk) agree with the CF _FillValue
        if "_FillValue" in src:
            sst_enc["fill_value"] = src["_FillValue"]
    else:
        # NaN only as the Zarr fill_value; no CF _FillValue attribute (xarray
        # would write a NaN attribute as base64 bytes, which JS readers do not expect)
        sst_enc["dtype"] = "float32"
        sst_enc["_FillValue"] = None
        sst_enc["fill_value"] = np.float32(np.nan)
    enc["sst"] = sst_enc
    for c in ("lat", "lon", "time", "zlev"):
        if c in ds.coords:
            enc[c] = {"chunks": ds[c].shape}
    return enc


def write(ds, path, packed=True, group=None, mode="w"):
    ds.to_zarr(path, group=group, mode=mode, zarr_format=3,
               consolidated=False, encoding=encoding_for(ds, packed))


def affine_from_coords(ds):
    """GDAL-order affine [a, b, c, d, e, f] for cell corners, from 1-D centres."""
    lon = ds["lon"].values.astype("float64")
    lat = ds["lat"].values.astype("float64")
    nx, ny = lon.size, lat.size
    dx = (lon[-1] - lon[0]) / (nx - 1)   # step across the span, not cell to cell
    dy = (lat[-1] - lat[0]) / (ny - 1)
    dx = float(np.round(dx, 10))
    dy = float(np.round(dy, 10))
    x0 = float(np.round(lon[0] - dx / 2, 10))
    y0 = float(np.round(lat[0] - dy / 2, 10))
    return [dx, 0.0, x0, 0.0, dy, y0], [ny, nx]


def spatial_attrs(transform, shape):
    a, _, c, _, e, f = transform
    ny, nx = shape
    xs = sorted([c, c + a * nx])
    ys = sorted([f, f + e * ny])
    return {
        "spatial:dimensions": ["lat", "lon"],
        "spatial:transform_type": "affine",
        "spatial:transform": transform,
        "spatial:shape": shape,
        "spatial:bbox": [xs[0], ys[0], xs[1], ys[1]],
        "spatial:registration": "pixel",
    }


def build_f01d(ds_ydesc, path):
    """Level 0 = f01b (packed), levels 1, 2 = 2x, 4x float32 means."""
    import zarr
    levels = [ds_ydesc]
    for f in (2, 4):
        lev = ds_ydesc.coarsen(lat=f, lon=f, boundary="exact").mean()
        lev["sst"] = lev["sst"].astype("float32")
        levels.append(lev)

    layout = []
    for i, lev in enumerate(levels):
        lev = add_grid_mapping(lev)
        write(lev, path, packed=(i == 0), group=str(i), mode="w" if i == 0 else "a")
        t, s = affine_from_coords(lev)
        g = zarr.open_group(path, path=str(i), mode="a", zarr_format=3)
        g.attrs.update({**spatial_attrs(t, s), "proj:code": "EPSG:4326",
                        "zarr_conventions": [CONV_SPATIAL, CONV_PROJ]})
        entry = {"asset": str(i), "spatial:transform": t, "spatial:shape": s}
        if i > 0:
            fac = float(2 ** i)
            entry["derived_from"] = "0"
            entry["transform"] = {"scale": [fac, fac], "translation": [0.0, 0.0]}
            entry["resampling_method"] = "mean"
        layout.append(entry)

    t0, s0 = affine_from_coords(levels[0])
    root = zarr.open_group(path, mode="a", zarr_format=3)
    root.attrs.update({
        "multiscales": {"layout": layout},
        **spatial_attrs(t0, s0),
        "proj:code": "EPSG:4326",
        "zarr_conventions": [CONV_MULTISCALES, CONV_SPATIAL, CONV_PROJ],
    })


def stac_collection(fid, title, desc, href, ds, expected, nodata=None):
    lon = ds["lon"].values
    lat = ds["lat"].values
    t = ds["time"].values
    w, e = float(lon.min()), float(lon.max())
    if w >= 0 and e > 180:  # 0..360 store spanning the globe
        bbox = [-180.0, float(lat.min()), 180.0, float(lat.max())]
    else:
        bbox = [w, float(lat.min()), e, float(lat.max())]
    return {
        "type": "Collection",
        "stac_version": "1.1.0",
        "stac_extensions": [
            "https://stac-extensions.github.io/datacube/v2.3.0/schema.json",
            "https://stac-extensions.github.io/projection/v2.0.0/schema.json",
        ],
        "id": fid,
        "title": title,
        "description": f"{desc}\n\nExpected browser outcome: {expected}",
        "license": "other",
        "extent": {
            "spatial": {"bbox": [bbox]},
            "temporal": {"interval": [[str(t.min())[:19] + "Z", str(t.max())[:19] + "Z"]]},
        },
        "links": [],
        "assets": {
            "data": {
                "href": href,
                "type": "application/vnd.zarr",
                "roles": ["data"],
                "proj:code": "EPSG:4326",
                "cube:variables": {
                    "sst": {"type": "data", "dimensions": ["time", "zlev", "lat", "lon"],
                            "unit": "degC"},
                },
                "bands": [dict({"name": "sst", "unit": "degC",
                                "statistics": {"minimum": -2.0, "maximum": 35.0}},
                               **({"nodata": nodata} if nodata is not None else {}))],
            }
        },
    }


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    src_dir, out_dir, base = sys.argv[1], sys.argv[2], sys.argv[3].rstrip("/")
    stores = os.path.join(out_dir, "stores")
    cat_dir = os.path.join(out_dir, "catalog", "f01")
    os.makedirs(stores, exist_ok=True)
    os.makedirs(cat_dir, exist_ok=True)

    native = open_source(src_dir)
    ydesc = native.isel(lat=slice(None, None, -1))
    roll = native.assign_coords(lon=(((native["lon"] + 180) % 360) - 180)).sortby("lon")
    for v in (ydesc, roll):
        v["sst"].encoding = native["sst"].encoding

    same = "Draws identically to the other f01 twins."
    twins = [
        ("f01a-oisst-native", native, "OISST as published: lon 0..360, lat ascending, CF int16 packing.",
         same + " Spec draft: fails overviews MUST (no pyramid)."),
        ("f01b-oisst-ydesc", ydesc, "f01a with lat descending (north-up).",
         same + " Spec draft: fails overviews MUST (no pyramid)."),
        ("f01c-oisst-180", roll, "f01a with lon rolled to -180..180.",
         same + " Spec draft: fails overviews MUST (no pyramid)."),
    ]
    collections = []
    for fid, ds, desc, expected in twins:
        p = os.path.join(stores, f"{fid}.zarr")
        write(add_grid_mapping(ds), p)
        collections.append(stac_collection(fid, fid, desc, f"{base}/stores/{fid}.zarr", ds, expected))
        print("wrote", p)

    fid = "f01d-oisst-transform"
    p = os.path.join(stores, f"{fid}.zarr")
    build_f01d(ydesc, p)
    collections.append(stac_collection(
        fid, fid, "f01b plus spatial:/proj: conventions and a 3-level multiscales pyramid.",
        f"{base}/stores/{fid}.zarr", ydesc,
        same + " Spec draft: conforms, if the pyramid convention is read as declared."))
    print("wrote", p)

    fid = "f01e-oisst-unpacked"
    p = os.path.join(stores, f"{fid}.zarr")
    write(add_grid_mapping(ydesc), p, packed=False)
    collections.append(stac_collection(
        fid, fid, "f01b stored as float32 physical values (degC), NaN fill, no CF packing.",
        f"{base}/stores/{fid}.zarr", ydesc,
        same + " Separates 'CF packing not applied' from other colour causes."))
    print("wrote", p)

    fid = "f01f-oisst-nodata"
    p = os.path.join(stores, f"{fid}.zarr")
    write(add_grid_mapping(ydesc), p)
    collections.append(stac_collection(
        fid, fid, "f01b with bands[].nodata = -999 declared on the STAC asset.",
        f"{base}/stores/{fid}.zarr", ydesc,
        same + " Land should be transparent; if f01b shows land as a colour and this does not, nodata came only from STAC.",
        nodata=-999))
    print("wrote", p)

    for c in collections:
        cdir = os.path.join(cat_dir, c["id"])
        os.makedirs(cdir, exist_ok=True)
        c["links"] = [
            {"rel": "root", "href": "../../catalog.json", "type": "application/json"},
            {"rel": "parent", "href": "../../catalog.json", "type": "application/json"},
        ]
        with open(os.path.join(cdir, "collection.json"), "w") as fh:
            json.dump(c, fh, indent=2)

    catalog = {
        "type": "Catalog", "stac_version": "1.1.0", "id": "portolan-fixtures",
        "description": "Zarr conformance fixtures: polar, ocean and virtual cases, built as twins.",
        "links": [{"rel": "root", "href": "./catalog.json", "type": "application/json"}] + [
            {"rel": "child", "href": f"./f01/{c['id']}/collection.json", "type": "application/json"}
            for c in collections],
    }
    with open(os.path.join(out_dir, "catalog", "catalog.json"), "w") as fh:
        json.dump(catalog, fh, indent=2)
    print("wrote catalog with", len(collections), "collections")


if __name__ == "__main__":
    main()
