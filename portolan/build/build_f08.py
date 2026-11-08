#!/usr/bin/env python3
"""Build the F08 ocean-model native grid twins from one year of ACCESS-ESM1.6.

Usage:
    python3 -I build/build_f08.py SRC_FILE OUT_DIR BASE_URL [GRID_FILE ...]

SRC_FILE  one yearly MOM5 history file, ocean-3d-temp-1mon-mean-y_YYYY.nc
          (12 monthly means, 50 depth levels), see build/fetch_esm.sh
OUT_DIR   output root (stores/ and catalog/f08/ are written under it)
BASE_URL  public https URL OUT_DIR is served at, no trailing slash
GRID_FILE optional files holding geolon_t and geolat_t on the same grid, for
          sources that name them in `coordinates` without carrying them (the
          ACCESS-ESM1.6 yearly files do: the positions are in the run's fixed
          fields, ocean-2d-geolon_t-fx.nc and ocean-2d-geolat_t-fx.nc)

The source is a tripolar MOM5 grid, 300 x 360: regular in longitude and
non-uniform in latitude south of the fold (about 65N), curvilinear north of
it. The files carry 1-D nominal axes (xt_ocean from -279.5 to 79.5, yt_ocean
with steps from about 0.25 to 1 degree) and, where the diagnostics include
them, the true 2-D positions geolon_t / geolat_t. The published virtual store
over these files has only the nominal axes, while `temp` still names
geolon_t geolat_t in its `coordinates` attribute.

Twins:
    f08a-esm-native        as the virtual store presents it: nominal 1-D axes,
                           dangling `coordinates`, chunks [1, 25, 150, 180]
    f08b-esm-levelchunk    f08a with chunks [1, 1, 300, 360] (one level per chunk)
    f08c-esm-geo2d         f08b plus the true 2-D geolon_t / geolat_t
                           (only built if the source file has them)
    f08d-esm-regular       regridded (nearest neighbour on the true positions,
                           or on the nominal axes if absent) to a regular
                           1-degree EPSG:4326 grid with a CF grid mapping
"""

import json
import os
import sys

import numpy as np
import pyproj
import xarray as xr

FILL = np.float32(-1.0e20)
WKT_4326 = pyproj.CRS.from_epsg(4326).to_wkt()


def open_source(path, grid_files=()):
    ds = xr.open_dataset(path, engine="netcdf4", decode_coords=False)
    keep = ["temp"] + [v for v in ("geolon_t", "geolat_t") if v in ds.variables]
    ds = ds[keep].load()
    for gf in grid_files:
        g = xr.open_dataset(gf, engine="netcdf4", decode_coords=False, decode_times=False)
        for v in ("geolon_t", "geolat_t"):
            if v not in g.variables or v in ds.variables:
                continue
            for ax in ("xt_ocean", "yt_ocean"):
                if not np.array_equal(g[ax].values, ds[ax].values):
                    sys.exit(f"{gf}: {ax} differs from the source's")
            a = g[v]
            if "time" in a.dims:
                a = a.isel(time=0, drop=True)
            ds[v] = a.drop_vars([c for c in a.coords if c not in ("xt_ocean", "yt_ocean")]).load()
    for c in ("xt_ocean", "yt_ocean", "st_ocean"):
        ds[c] = ds[c].astype("float64")
    return ds


def enc_temp(chunks):
    return {"chunks": chunks, "dtype": "float32", "_FillValue": FILL, "fill_value": FILL}


def write(ds, path, chunks):
    enc = {"temp": enc_temp(chunks)}
    for c in ds.coords:
        enc[c] = {"chunks": ds[c].shape}
    for v in ds.data_vars:
        if v != "temp":
            enc[v] = {"chunks": ds[v].shape} if ds[v].ndim else {}
    ds.to_zarr(path, mode="w", zarr_format=3, consolidated=False, encoding=enc)


def regrid(ds, have_geo):
    """Nearest neighbour onto a regular 1-degree grid, on the sphere."""
    from scipy.spatial import cKDTree
    if have_geo:
        lon = ds["geolon_t"].values
        lat = ds["geolat_t"].values
    else:
        lon, lat = np.meshgrid(ds["xt_ocean"].values, ds["yt_ocean"].values)

    def xyz(lo, la):
        lo, la = np.deg2rad(lo), np.deg2rad(la)
        return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])

    src = xyz(lon.ravel(), lat.ravel())
    ok = np.isfinite(src).all(axis=1)
    tree = cKDTree(src[ok])
    glon = np.arange(-179.5, 180, 1.0)
    glat = np.arange(89.5, -90, -1.0)            # north-up
    tlon, tlat = np.meshgrid(glon, glat)
    dist, idx = tree.query(xyz(tlon.ravel(), tlat.ravel()))
    src_idx = np.flatnonzero(ok)[idx]
    # leave cells farther than about 1.5 source cells empty (outside the model domain)
    far = dist > np.deg2rad(1.5)
    t = ds["temp"].values.reshape(ds.sizes["time"], ds.sizes["st_ocean"], -1)
    out = t[:, :, src_idx].astype("float32")
    out[:, :, far] = np.nan
    out = out.reshape(ds.sizes["time"], ds.sizes["st_ocean"], glat.size, glon.size)
    r = xr.Dataset(
        {"temp": (("time", "st_ocean", "lat", "lon"), out, dict(ds["temp"].attrs))},
        coords={"time": ds["time"], "st_ocean": ds["st_ocean"],
                "lat": ("lat", glat, {"standard_name": "latitude", "units": "degrees_north"}),
                "lon": ("lon", glon, {"standard_name": "longitude", "units": "degrees_east"})})
    r["temp"].attrs.pop("coordinates", None)
    r["temp"].attrs["grid_mapping"] = "crs"
    r["crs"] = xr.DataArray(np.int32(0), attrs={"grid_mapping_name": "latitude_longitude",
                                                "crs_wkt": WKT_4326, "spatial_ref": WKT_4326})
    return r


def collection(fid, desc, href, ds, expected, dims, proj):
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
        "extent": {"spatial": {"bbox": [[-180.0, -78.0, 180.0, 90.0]]},
                   "temporal": {"interval": [[str(t.min())[:19] + "Z", str(t.max())[:19] + "Z"]]}},
        "links": [],
        "assets": {"data": {
            "href": href, "type": "application/vnd.zarr", "roles": ["data"], **proj,
            "cube:variables": {"temp": {"type": "data", "dimensions": dims, "unit": "K"}},
            "bands": [{"name": "temp", "unit": "K", "nodata": -1.0e20,
                       "statistics": {"minimum": 271.0, "maximum": 305.0}}],
        }},
    }


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    src, out, base = sys.argv[1], sys.argv[2], sys.argv[3].rstrip("/")
    stores = os.path.join(out, "stores")
    os.makedirs(stores, exist_ok=True)
    ds = open_source(src, sys.argv[4:])
    have_geo = "geolon_t" in ds and "geolat_t" in ds
    nominal = ds[["temp"]]
    nominal["temp"].attrs["coordinates"] = "geolon_t geolat_t"   # as published: names arrays it lacks
    dims = ["time", "st_ocean", "yt_ocean", "xt_ocean"]
    code = {"proj:code": "EPSG:4326"}
    ny, nx = ds.sizes["yt_ocean"], ds.sizes["xt_ocean"]
    cols = []

    def href(fid):
        return f"{base}/stores/{fid}.zarr"

    fid = "f08a-esm-native"
    write(nominal, os.path.join(stores, f"{fid}.zarr"), (1, 25, 150, 180))
    cols.append(collection(fid,
        "ACCESS-ESM1.6 historical ocean temp, one year of monthly means, 50 levels, as the virtual store presents it: 1-D nominal xt_ocean (-279.5 to 79.5) and yt_ocean (non-uniform), `coordinates` naming geolon_t geolat_t which the store lacks, chunks [1, 25, 150, 180], no grid mapping.",
        href(fid), ds,
        "Refused: yt_ocean is not regular, and one level reads 25x what it draws (draft bound 8). A client that skips both checks draws it with the Arctic misplaced (the nominal axes are wrong north of the tripolar fold).",
        dims, code))

    fid = "f08b-esm-levelchunk"
    write(nominal, os.path.join(stores, f"{fid}.zarr"), (1, 1, ny, nx))
    cols.append(collection(fid,
        "f08a with one depth level per chunk [1, 1, 300, 360]: amplification 1.",
        href(fid), ds,
        "Refused only for the non-uniform yt_ocean axis; the amplification reason is gone. Separates the two refusals of f08a.",
        dims, code))

    if have_geo:
        fid = "f08c-esm-geo2d"
        g = ds.copy()
        g["temp"].attrs["coordinates"] = "geolon_t geolat_t"
        write(g, os.path.join(stores, f"{fid}.zarr"), (1, 1, ny, nx))
        cols.append(collection(fid,
            "f08b plus the true 2-D cell positions geolon_t / geolat_t from the model output, which the `coordinates` attribute names: a correct CF description of a tripolar grid.",
            href(fid), ds,
            "Refused as curvilinear: a genuinely curvilinear grid, correctly out of scope for the draft's v1 profile (needs a per-pixel warp).",
            dims, {"proj:code": None}))

    fid = "f08d-esm-regular"
    r = regrid(ds, have_geo)
    write(r, os.path.join(stores, f"{fid}.zarr"), (1, 1, 180, 360))
    how = "the true geolon_t / geolat_t" if have_geo else "the nominal axes (no true positions in the source)"
    cols.append(collection(fid,
        f"f08a regridded by nearest neighbour on {how} to a regular 1-degree EPSG:4326 grid (lon -179.5..179.5, lat 89.5..-89.5), one level per chunk, CF grid mapping `crs`.",
        href(fid), r,
        "Draws. Shows level 0 (surface) unless a style can select a depth index, which the draft cannot yet express.",
        ["time", "st_ocean", "lat", "lon"], code))

    cat = os.path.join(out, "catalog", "f08")
    for c in cols:
        d = os.path.join(cat, c["id"])
        os.makedirs(d, exist_ok=True)
        c["links"] = [{"rel": "root", "href": "../../catalog.json", "type": "application/json"},
                      {"rel": "parent", "href": "../../catalog.json", "type": "application/json"}]
        with open(os.path.join(d, "collection.json"), "w") as fh:
            json.dump(c, fh, indent=2)
        print("wrote", c["id"])
    if not have_geo:
        print("NOTE: source has no geolon_t/geolat_t; f08c skipped, f08d regridded from nominal axes")


if __name__ == "__main__":
    main()
