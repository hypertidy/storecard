"""One assertion end to end (step 3 of the brief).

f03d presents the EPSG:3412 grid of the Bremen twins as 2-D lon/lat only.
An assertion of that grid, applied as an overlay, must make its card match
its declared twin f03e; written out as zarr-conventions attributes on a
copy, it must give the same card again. f08c, a genuinely curvilinear
tripolar grid, gets a refusal. The source stores are never written.
"""

import json
import shutil
import xml.etree.ElementTree as ET

import pytest
import zarr

from storecard import assertion as A
from storecard import card

# the NSIDC polar stereographic south grid at 3125 m, north-up (fixtures-plan F03)
BREMEN_SOUTH = [3125.0, 0.0, -3950000.0, 0.0, -3125.0, 4350000.0]
BY = {"name": "storecard tests", "method": "known fixture grid"}


@pytest.fixture(scope="module")
def f03d(fixtures):
    return fixtures["f03d-asi-latlon2d"][0]


@pytest.fixture(scope="module")
def f03d_assertion(f03d):
    c = card(f03d, probe_hosts=False)
    return A.grid_assertion(c, "z", BREMEN_SOUTH, {"proj:code": "EPSG:3412"},
                            evidence={"method": "fixtures-plan F03: the grid the twin was built from"},
                            by=BY)


def grid_facts(c):
    v = c["variables"][0]
    t = {k: v["grid"]["transform"][k] for k in ("spatial:transform", "spatial:shape", "spatial:dimensions")}
    return v["grid"]["costume"], v["grid"]["form"], t, sorted(c["findings_summary"])


def test_assertion_validates(f03d_assertion):
    d = f03d_assertion
    assert d["kind"] == "grid" and d["status"] == "proposed"
    assert d["subject"]["variable"] == "z"
    assert d["subject"]["metadata_digest"].startswith("sha256:")
    assert d["asserts"]["spatial:shape"] == [2656, 2528]
    json.dumps(d, allow_nan=False)


def test_overlay_matches_declared_twin(fixtures, f03d, f03d_assertion):
    presented = card(f03d, probe_hosts=False)
    asserted = card(f03d, probe_hosts=False, assertions=[f03d_assertion])
    twin = card(fixtures["f03e-asi-projjson"][0], probe_hosts=False)
    assert grid_facts(asserted) == grid_facts(twin)
    v = asserted["variables"][0]
    assert v["grid"]["costume"] == "B"
    assert v["grid"]["costume_presented"] == ["E", "H"]
    assert v["grid"]["transform"]["from"] == "assertion"
    assert v["crs"]["sources"] == [{"via": "proj:code", "on": "assertion", "value": "EPSG:3412"}]
    assert asserted["source"]["assertions"][0]["applied"] is True
    # the presented card is unchanged by having been asserted over
    assert set(presented["findings_summary"]) == {"GRID_2D_LONLAT_ONLY", "CRS_NOT_DECLARED"}


def test_store_is_not_written(f03d, f03d_assertion):
    before = card(f03d, probe_hosts=False)["source"]["metadata_digest"]
    card(f03d, probe_hosts=False, assertions=[f03d_assertion])
    assert card(f03d, probe_hosts=False)["source"]["metadata_digest"] == before


def test_emitted_zarr_attrs_give_the_same_card(tmp_path, f03d, f03d_assertion):
    copy = tmp_path / "f03d-copy.zarr"
    shutil.copytree(f03d, copy)
    zarr.open_array(str(copy), path="z", mode="r+").attrs.update(A.to_zarr_attrs(f03d_assertion))
    written = card(str(copy), probe_hosts=False)
    overlay = card(f03d, probe_hosts=False, assertions=[f03d_assertion])
    assert grid_facts(written) == grid_facts(overlay)
    assert written["variables"][0]["crs"]["declared"]


def test_stale_assertion_is_not_applied(tmp_path, f03d, f03d_assertion):
    copy = tmp_path / "f03d-changed.zarr"
    shutil.copytree(f03d, copy)
    zarr.open_array(str(copy), path="z", mode="r+").attrs["history"] = "republished"
    c = card(str(copy), probe_hosts=False, assertions=[f03d_assertion])
    assert c["source"]["assertions"][0]["applied"] is False
    assert "ASSERTION_STALE" in c["findings_summary"]
    assert c["variables"][0]["grid"]["costume"] == ["E", "H"]


def test_withdrawn_and_missing(f03d, f03d_assertion):
    w = dict(f03d_assertion, status="withdrawn")
    c = card(f03d, probe_hosts=False, assertions=[w])
    assert c["source"]["assertions"][0] == {**c["source"]["assertions"][0], "applied": False, "reason": "withdrawn"}
    m = dict(f03d_assertion, subject=dict(f03d_assertion["subject"], variable="nope"))
    c = card(f03d, probe_hosts=False, assertions=[m])
    assert "ASSERTION_SUBJECT_MISSING" in c["findings_summary"]


def test_refusal_resolves_to_h(fixtures):
    path = fixtures["f08c-esm-geo2d"][0]
    c = card(path, probe_hosts=False)
    assert c["variables"][0]["grid"]["costume"] == ["E", "H"]
    doc = A.refusal(c, "temp", "curvilinear in every frame tried: tripolar fold north of 65N",
                    frames_tried=["EPSG:4326", "EPSG:3413", "EPSG:3031"],
                    evidence={"nominal_deviation_cells": c["variables"][0]["grid"]["nominal_deviation"]["max_cells"]},
                    by=BY)
    r = card(path, probe_hosts=False, assertions=[doc])
    g = r["variables"][0]["grid"]
    assert g["costume"] == "H" and g["costume_presented"] == ["E", "H"]
    assert g["assertion"]["refuses"]["frames_tried"][0] == "EPSG:4326"
    with pytest.raises(A.AssertionError_):
        A.to_vrt(doc, c)


def test_stac_patch(fixtures, f03d_assertion):
    col = json.load(open(fixtures["f03d-asi-latlon2d"][1]))
    for op in A.to_stac_patch(f03d_assertion):
        assert op["op"] == "add"
        keys = op["path"].strip("/").split("/")
        node = col
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = op["value"]
    asset = col["assets"]["data"]
    assert asset["proj:code"] == "EPSG:3412"
    assert asset["proj:transform"] == BREMEN_SOUTH
    assert asset["proj:shape"] == [2656, 2528]


def test_vrt(f03d, f03d_assertion):
    c = card(f03d, probe_hosts=False)
    root = ET.fromstring(A.to_vrt(f03d_assertion, c))
    grp = root.find("Group")
    dims = {d.get("name"): d.attrib for d in grp.findall("Dimension")}
    assert dims["x"]["type"] == "HORIZONTAL_X" and dims["y"]["size"] == "2656"
    arrays = {a.get("name"): a for a in grp.findall("Array")}
    x = arrays["x"].find("RegularlySpacedValues").attrib
    assert float(x["start"]) == -3950000.0 + 1562.5 and float(x["increment"]) == 3125.0
    y = arrays["y"].find("RegularlySpacedValues").attrib
    assert float(y["start"]) == 4350000.0 - 1562.5 and float(y["increment"]) == -3125.0
    z = arrays["z"]
    assert z.find("SRS").text == "EPSG:3412"
    assert z.find("SRS").get("dataAxisToSRSAxisMapping") == "3,2"   # (time, y, x): easting is dim 3
    assert z.find("Source/SourceArray").text == "/z"
    assert z.find("DataType").text == "Float32"


def test_invalid_documents(f03d_assertion):
    bad = dict(f03d_assertion, asserts={**f03d_assertion["asserts"], "units": "m"})
    with pytest.raises(A.AssertionError_):
        A.validate(bad)
    bad = dict(f03d_assertion, asserts={k: v for k, v in f03d_assertion["asserts"].items() if not k.startswith("proj:")})
    with pytest.raises(A.AssertionError_):
        A.validate(bad)
    with pytest.raises(A.AssertionError_):
        A.validate(dict(f03d_assertion, status="maybe"))


def test_cli_applies_and_emits(tmp_path, f03d, f03d_assertion, capsys):
    from storecard.__main__ import main
    p = tmp_path / "a.json"
    p.write_text(json.dumps(f03d_assertion))
    main([f03d, "--no-hosts", "--assertion", str(p)])
    assert json.loads(capsys.readouterr().out)["variables"][0]["grid"]["costume"] == "B"
    main([f03d, "--assertion", str(p), "--emit", "zarr"])
    assert json.loads(capsys.readouterr().out)["proj:code"] == "EPSG:3412"
    main([f03d, "--assertion", str(p), "--emit", "vrt"])
    assert capsys.readouterr().out.startswith("<VRTDataset>")


# ---------------------------------------------------------------- CRS from regular axes

def _axes_card(x, y):
    """A minimal card: one variable on regular 1-D axes, no CRS."""
    def ax(name, first, last, n):
        return {"name": name, "n": n, "first": first, "last": last, "spacing": "regular"}
    return {"source": {"url": "memory://axes", "metadata_digest": "sha256:0"},
            "variables": [{"name": "v", "shape": [3, y[2], x[2]], "dims": ["time", "lat", "lon"],
                           "grid": {"spatial_dims": ["lat", "lon"],
                                    "axes": {"x": ax("lon", *x), "y": ax("lat", *y)}}}]}


def test_axes_transform_restates_regular_axes():
    # OISST: 0.25 degree centres from 0.125, latitude ascending
    c = _axes_card((0.125, 359.875, 1440), (-89.875, 89.875, 720))
    assert A.axes_transform(c["variables"][0]) == [0.25, 0.0, 0.0, 0.0, 0.25, -90.0]
    # MUR: descending latitude, float noise in the axis arithmetic snapped
    c = _axes_card((-179.99, 180.0, 36000), (89.99, -89.99, 17999))
    assert A.axes_transform(c["variables"][0]) == [0.01, 0.0, -179.995, 0.0, -0.01, 89.995]


def test_crs_assertion_is_a_valid_grid_assertion():
    c = _axes_card((0.125, 359.875, 1440), (-89.875, 89.875, 720))
    doc = A.crs_assertion(c, "v", {"proj:code": "EPSG:4326"}, crs_axes=("y", "x"),
                          evidence={"crs_from": "convention"}, by=BY)
    assert doc["asserts"]["spatial:shape"] == [720, 1440]
    assert doc["asserts"]["spatial:dimensions"] == ["lat", "lon"]
    assert doc["crs_axes"] == ["y", "x"]
    assert doc["evidence"]["axes"] == {"x": "lon", "y": "lat"}
    assert doc["evidence"]["crs_from"] == "convention"


def test_crs_assertion_refuses_irregular_axes():
    c = _axes_card((0.125, 359.875, 1440), (-89.875, 89.875, 720))
    c["variables"][0]["grid"]["axes"]["y"]["spacing"] = "irregular"
    assert A.axes_transform(c["variables"][0]) is None
    with pytest.raises(A.AssertionError_):
        A.crs_assertion(c, "v", {"proj:code": "EPSG:4326"})
