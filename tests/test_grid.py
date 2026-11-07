"""Costumes, longitude conventions and sharded cost, on small stores written directly."""

import numpy as np
import pytest
import zarr

from storecard import card


def store(tmp_path, axes=None, arrays2d=None, data_dims=("y", "x"), shape=(8, 16),
          chunks=None, shards=None, attrs=None, extra=None):
    g = zarr.open_group(str(tmp_path / "s.zarr"), mode="w", zarr_format=3)
    for name, (vals, a) in (axes or {}).items():
        arr = g.create_array(name, shape=(len(vals),), dtype="float64", dimension_names=[name])
        arr[:] = vals
        arr.attrs.update(a)
    for name, (vals, a) in (arrays2d or {}).items():
        arr = g.create_array(name, shape=vals.shape, dtype="float64", dimension_names=list(data_dims[-2:]))
        arr[:] = vals
        arr.attrs.update(a)
    for name, a in (extra or {}).items():
        g.create_array(name, shape=(), dtype="int32").attrs.update(a)
    kw = {"chunks": chunks or shape}
    if shards:
        kw["shards"] = shards
    v = g.create_array("v", shape=shape, dtype="float32", fill_value=np.float32("nan"),
                       dimension_names=list(data_dims), **kw)
    v.attrs.update(attrs or {})
    return str(tmp_path / "s.zarr")


LON = {"standard_name": "longitude", "units": "degrees_east"}
LAT = {"standard_name": "latitude", "units": "degrees_north"}


def v0(c):
    return c["variables"][0]


def codes(c):
    return {f["code"] for f in c["findings"]}


def test_costume_a(tmp_path):
    c = card(store(tmp_path), probe_hosts=False)
    assert v0(c)["grid"]["costume"] == "A"


def test_costume_d_mercator(tmp_path):
    # latitudes evenly spaced in Mercator y
    y = np.linspace(-1.2, 1.2, 8)
    lat = np.rad2deg(2 * np.arctan(np.exp(y)) - np.pi / 2)
    lon = np.arange(16) * 22.5 - 168.75
    c = card(store(tmp_path, axes={"y": (lat, LAT), "x": (lon, LON)}), probe_hosts=False)
    assert "LAT_MERCATOR_SPACED" in codes(c)
    assert v0(c)["grid"]["costume"] == "D"


def test_costume_g(tmp_path):
    lat = np.array([-60, -40, -25, -10, 0, 10, 30, 60.0])
    lon = np.arange(16) * 22.5 - 168.75
    c = card(store(tmp_path, axes={"y": (lat, LAT), "x": (lon, LON)}), probe_hosts=False)
    assert v0(c)["grid"]["costume"] == "G"


def test_costume_e2_rotated(tmp_path):
    rlat = np.arange(8) * 0.5
    rlon = np.arange(16) * 0.5
    lon2, lat2 = np.meshgrid(rlon + 10, rlat + 40)
    c = card(store(tmp_path,
                   axes={"y": (rlat, {"standard_name": "grid_latitude", "units": "degrees"}),
                         "x": (rlon, {"standard_name": "grid_longitude", "units": "degrees"})},
                   arrays2d={"lon": (lon2, LON), "lat": (lat2, LAT)},
                   attrs={"coordinates": "lon lat", "grid_mapping": "rp"},
                   extra={"rp": {"grid_mapping_name": "rotated_latitude_longitude",
                                 "grid_north_pole_latitude": 39.25, "grid_north_pole_longitude": -162.0}}),
             probe_hosts=False)
    assert v0(c)["grid"]["costume"] == "E2"
    assert "GRID_2D_WITH_PROJECTED_1D" in codes(c)


def test_costume_e3_scan_angle(tmp_path):
    x = (np.arange(16) - 7.5) * 5.6e-5
    y = (7.5 - np.arange(8)) * 5.6e-5
    c = card(store(tmp_path, axes={"y": (y, {"axis": "Y", "units": "rad"}),
                                   "x": (x, {"axis": "X", "units": "rad"})}), probe_hosts=False)
    assert v0(c)["grid"]["costume"] == "E3"


def test_costume_f_projected_2d(tmp_path):
    xx, yy = np.meshgrid(np.arange(16) * 1000.0, np.arange(8) * 1000.0)
    c = card(store(tmp_path, arrays2d={
        "xc": (xx, {"standard_name": "projection_x_coordinate", "units": "m"}),
        "yc": (yy, {"standard_name": "projection_y_coordinate", "units": "m"})},
        attrs={"coordinates": "xc yc"}), probe_hosts=False)
    assert v0(c)["grid"]["costume"] == "F"


def test_lon_0_360_and_overshoot(tmp_path):
    lat = 80 - np.arange(8) * 20.0
    c = card(store(tmp_path, axes={"y": (lat, LAT), "x": (np.arange(16) * 22.5 + 11.25, LON)}),
             probe_hosts=False)
    assert "LON_0_360" in codes(c) and "LON_OVERSHOOT_180" not in codes(c)


def test_lon_overshoot(tmp_path):
    # an overview whose extent rounds up past the antimeridian by a fraction of a cell
    lat = 80 - np.arange(8) * 20.0
    lon = -180 + 23.0 * (np.arange(16) + 0.5)        # last centre 176.5, edge past 180
    lon = lon + 3.6                                  # last centre 180.1
    c = card(store(tmp_path, axes={"y": (lat, LAT), "x": (lon, LON)}), probe_hosts=False)
    f = [f for f in c["findings"] if f["code"] == "LON_OVERSHOOT_180"]
    assert f and "LON_0_360" not in codes(c)
    assert f[0]["overshoot_cells"] == pytest.approx(0.1 / 23.0, abs=1e-4)


def test_sharded_cost(tmp_path):
    # inner chunks one band x 512 x 512, shards 3 bands x 2048 x 2048 (cf. a sharded pyramid)
    c = card(store(tmp_path, data_dims=("band", "y", "x"), shape=(3, 2048, 2048),
                   chunks=(1, 512, 512), shards=(3, 2048, 2048)), probe_hosts=False)
    cost = v0(c)["cost"]
    assert cost["nonspatial_read_factor"] == {"inner": 1, "shard": 3}
    assert cost["tile_amplification"] == {"aligned": 4.0, "worst": 16.0}
