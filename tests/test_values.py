"""Fill value cases from the brief, on small stores written directly."""

import numpy as np
import zarr

from storecard import card


def _store(tmp_path, dtype, fill_value, attrs):
    g = zarr.open_group(str(tmp_path / "s.zarr"), mode="w", zarr_format=3)
    y = g.create_array("y", shape=(4,), dtype="float64", dimension_names=["y"])
    y[:] = [3.5, 2.5, 1.5, 0.5]
    y.attrs.update({"standard_name": "latitude", "units": "degrees_north"})
    x = g.create_array("x", shape=(4,), dtype="float64", dimension_names=["x"])
    x[:] = [0.5, 1.5, 2.5, 3.5]
    x.attrs.update({"standard_name": "longitude", "units": "degrees_east"})
    a = g.create_array("v", shape=(4, 4), chunks=(4, 4), dtype=dtype,
                       fill_value=fill_value, dimension_names=["y", "x"])
    a.attrs.update(attrs)
    return str(tmp_path / "s.zarr")


def codes(c):
    return {f["code"] for f in c["findings"]}


def test_zarr_fill_zero_beside_cf_fill(tmp_path):
    # xarray's default for Zarr v3: fill_value 0 beside a CF _FillValue of -999
    c = card(_store(tmp_path, "int16", 0, {"_FillValue": -999}), probe_hosts=False)
    assert "FILL_DISAGREE" in codes(c)
    assert c["variables"][0]["values"]["fill_agree"] is False


def test_float32_fill_from_float64_attribute(tmp_path):
    # -1e20 as a float64 attribute never equals the float32 stored value
    c = card(_store(tmp_path, "float32", np.float32(-1e20), {"_FillValue": -1e20}), probe_hosts=False)
    assert "FILL_NOT_REPRESENTABLE" in codes(c)
    assert "FILL_DISAGREE" not in codes(c)


def test_agreeing_fills(tmp_path):
    c = card(_store(tmp_path, "int16", -999, {"_FillValue": -999, "missing_value": -999}), probe_hosts=False)
    assert not {"FILL_DISAGREE", "FILL_NOT_REPRESENTABLE"} & codes(c)
    assert c["variables"][0]["values"]["fill_agree"] is True


def test_base64_nan_attribute(tmp_path):
    # xarray writes a NaN _FillValue for Zarr v3 as base64
    import base64
    b = base64.b64encode(np.array([np.nan], "<f8").tobytes()).decode()
    c = card(_store(tmp_path, "float32", np.float32("nan"), {"_FillValue": b}), probe_hosts=False)
    fills = {f["from"]: f for f in c["variables"][0]["values"]["fill"]}
    assert fills["CF _FillValue"]["value"] == "nan"
    assert fills["CF _FillValue"]["encoding"] == "base64"
    assert c["variables"][0]["values"]["fill_agree"] is True
