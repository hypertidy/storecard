"""Small synthetic stand-ins for the portolan fixture sources.

Each writer produces a netCDF file with the source's layout (grid, dtype,
packing, fill values, attributes), so that the unchanged builders in
portolan/build turn it into stores with the same presentation as the
published fixtures. The values are smooth fields; only the metadata and the
coordinates matter to a card.
"""

import os

import numpy as np
import xarray as xr


def _field(ny, nx, lo, hi):
    yy, xx = np.meshgrid(np.linspace(0, np.pi, ny), np.linspace(0, 2 * np.pi, nx), indexing="ij")
    f = (np.sin(yy) * (1 + 0.3 * np.cos(3 * xx))) / 1.3
    return lo + (hi - lo) * f


def oisst(out_dir, days=("20250101", "20250102")):
    """OISST v2.1 daily: 720 x 1440, lat ascending, lon 0..360, int16 packed."""
    os.makedirs(out_dir, exist_ok=True)
    lat = np.arange(-89.875, 90, 0.25, dtype="float32")
    lon = np.arange(0.125, 360, 0.25, dtype="float32")
    sst = _field(lat.size, lon.size, -1.8, 30.0).astype("float32")
    land = (np.abs(lat[:, None] - 20) < 15) & (np.abs(lon[None, :] - 30) < 25)
    sst[land] = np.nan
    for k, d in enumerate(days):
        ds = xr.Dataset(
            {"sst": (("time", "zlev", "lat", "lon"), sst[None, None] + 0.1 * k,
                     {"long_name": "Daily sea surface temperature", "units": "Celsius",
                      "valid_min": -300, "valid_max": 4500})},
            coords={
                "time": ("time", [float(17000 + k)], {"units": "days since 1978-01-01 12:00:00",
                                                    "long_name": "Center time of the day"}),
                "zlev": ("zlev", np.array([0.0], "float32"), {"units": "meters", "axis": "Z"}),
                "lat": ("lat", lat, {"units": "degrees_north", "long_name": "Latitude"}),
                "lon": ("lon", lon, {"units": "degrees_east", "long_name": "Longitude"}),
            })
        enc = {"sst": {"dtype": "int16", "scale_factor": 0.01, "add_offset": 0.0, "_FillValue": np.int16(-999)}}
        ds.to_netcdf(os.path.join(out_dir, f"oisst-avhrr-v02r01.{d}.nc"), encoding=enc, engine="netcdf4")


def asi(out_dir, days=("20250915",)):
    """Bremen ASI AMSR2 3.125 km south: 2656 x 2528, y ascending, float32 z."""
    os.makedirs(out_dir, exist_ok=True)
    x = -3950000 + 1562.5 + 3125.0 * np.arange(2528)
    y = -3950000 + 1562.5 + 3125.0 * np.arange(2656)
    z = _field(y.size, x.size, 0.0, 100.0).astype("float32")
    z[: y.size // 4, :] = np.nan
    for d in days:
        ds = xr.Dataset({"z": (("y", "x"), z, {"long_name": "sea ice concentration", "units": "%"})},
                        coords={"x": ("x", x), "y": ("y", y)})
        ds.to_netcdf(os.path.join(out_dir, f"asi-AMSR2-s3125-{d}-v5.4.nc"),
                     encoding={"z": {"_FillValue": np.float32(np.nan), "chunksizes": (1, x.size)}},
                     engine="netcdf4")


def g02202(out_dir, days=("20250915",)):
    """NOAA/NSIDC G02202 v6 south 25 km: 332 x 316, y descending, uint8 packed with flags."""
    os.makedirs(out_dir, exist_ok=True)
    x = -3950000 + 12500.0 + 25000.0 * np.arange(316)
    y = 4350000 - 12500.0 - 25000.0 * np.arange(332)
    c = _field(y.size, x.size, 0.0, 1.0)
    for k, d in enumerate(days):
        v = np.round(c * 100).astype("uint8")
        v[:20, :] = 254          # land flag
        v[20:22, :] = 253        # coast flag
        ds = xr.Dataset(
            {"cdr_seaice_conc": (("time", "y", "x"), v[None],
                                 {"long_name": "NOAA/NSIDC sea ice concentration CDR",
                                  "units": "1", "valid_range": np.array([0, 100], "uint8"),
                                  "flag_values": np.array([251, 252, 253, 254], "uint8"),
                                  "flag_meanings": "pole_hole lake coastal land",
                                  "scale_factor": 0.01, "add_offset": 0.0,
                                  "_FillValue": np.uint8(255),
                                  "grid_mapping": "crs"}),
             "crs": ((), np.int32(0), {"grid_mapping_name": "polar_stereographic",
                                        "straight_vertical_longitude_from_pole": 0.0,
                                        "latitude_of_projection_origin": -90.0,
                                        "standard_parallel": -70.0,
                                        "false_easting": 0.0, "false_northing": 0.0,
                                        "semi_major_axis": 6378273.0,
                                        "inverse_flattening": 298.279411123064,
                                        "srid": "urn:ogc:def:crs:EPSG::3412"})},
            coords={"time": ("time", [float(20345 + k)], {"units": "days since 1970-01-01"}),
                    "x": ("x", x, {"standard_name": "projection_x_coordinate", "units": "meters"}),
                    "y": ("y", y, {"standard_name": "projection_y_coordinate", "units": "meters"})})
        ds.to_netcdf(os.path.join(out_dir, f"sic_pss25_{d}_am2_v06r00.nc"), engine="netcdf4")


def esm(path, levels=50):
    """ACCESS-ESM1.6 MOM5 monthly ocean temperature on the tripolar grid, one month."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    nx, ny = 360, 300
    xt = np.arange(-279.5, 80, 1.0)
    # non-uniform latitude: 1 degree in the south, 1/4 near the equator, 1 north of 30N
    steps = np.where(np.abs(np.linspace(-1, 1, ny - 1)) < 0.2, 0.3, 0.6)
    yt = np.concatenate([[-77.88], -77.88 + np.cumsum(steps)])
    yt = -77.88 + (yt + 77.88) * (89.5 + 77.88) / (yt[-1] + 77.88)
    st = np.cumsum(np.linspace(5, 300, levels))
    glon, glat = np.meshgrid(xt, yt)
    fold = yt > 65
    # north of the fold the true positions bend away from the nominal axes
    bend = np.clip((glat - 65) / 25, 0, 1)
    glat = np.where(fold[:, None], glat - 20 * bend * np.abs(np.cos(np.deg2rad(glon + 100))), glat)
    glon = np.where(fold[:, None], glon + 30 * bend * np.sin(np.deg2rad(glon + 100)), glon)
    t = _field(ny, nx, 271.0, 305.0).astype("float32")
    temp = np.repeat(t[None, None], levels, axis=1)
    fill = np.float32(-1.0e20)
    temp[:, :, :10, :] = fill
    ds = xr.Dataset(
        {"temp": (("time", "st_ocean", "yt_ocean", "xt_ocean"), temp,
                  {"long_name": "Conservative temperature", "units": "K",
                   "missing_value": fill, "_FillValue": fill,
                   "coordinates": "geolon_t geolat_t", "cell_methods": "time: mean"}),
         "geolon_t": (("yt_ocean", "xt_ocean"), glon.astype("float32"),
                      {"long_name": "tracer longitude", "units": "degrees_E"}),
         "geolat_t": (("yt_ocean", "xt_ocean"), glat.astype("float32"),
                      {"long_name": "tracer latitude", "units": "degrees_N"})},
        coords={"time": ("time", [36500.0], {"units": "days since 0001-01-01 00:00:00", "calendar": "proleptic_gregorian"}),
                "st_ocean": ("st_ocean", st, {"units": "meters", "cartesian_axis": "Z", "positive": "down"}),
                "yt_ocean": ("yt_ocean", yt, {"units": "degrees_N", "cartesian_axis": "Y", "long_name": "tcell latitude"}),
                "xt_ocean": ("xt_ocean", xt, {"units": "degrees_E", "cartesian_axis": "X", "long_name": "tcell longitude"})})
    enc = {v: {"_FillValue": None} for v in ("geolon_t", "geolat_t", "xt_ocean", "yt_ocean", "st_ocean")}
    enc["temp"] = {"_FillValue": fill}
    ds["temp"].attrs.pop("_FillValue")
    ds.to_netcdf(path, encoding=enc, engine="netcdf4")
