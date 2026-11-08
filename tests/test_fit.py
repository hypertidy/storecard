"""Grid fit from a card (step 2 of the brief).

f03d presents the EPSG:3412 grid of the Bremen twins as 2-D lon/lat only:
the fit must recover EPSG:3412 and the exact transform from the card's
coordinate sample. f08c is a genuinely curvilinear tripolar grid: the fit
must refuse it. Needs osgeo.gdal; skipped without it.
"""

import json
import pathlib

import numpy as np
import pytest

pytest.importorskip("osgeo.osr")

from storecard import assertion as A  # noqa: E402
from storecard import card, fit  # noqa: E402

BREMEN_SOUTH = [3125.0, 0.0, -3950000.0, 0.0, -3125.0, 4350000.0]
ROOT = pathlib.Path(__file__).parents[1]


@pytest.fixture(scope="module")
def f03d_card(fixtures):
    return card(fixtures["f03d-asi-latlon2d"][0], probe_hosts=False)


@pytest.fixture(scope="module")
def f08c_card(fixtures):
    return card(fixtures["f08c-esm-geo2d"][0], probe_hosts=False)


def test_f03d_recovers_epsg3412_and_exact_transform(f03d_card):
    name, r = fit.fit(f03d_card)
    assert name == "z"
    assert r["verdict"] == "fitted"
    assert r["proj:code"] == "EPSG:3412"
    assert r["spatial:transform"] == BREMEN_SOUTH
    assert r["residual_cells"] < 1e-6
    # same projection on the WGS84 ellipsoid fits within tolerance at a
    # pixel size that is not round; recorded, not chosen
    assert set(r["also_regular_in"]) == {"EPSG:3976", "EPSG:3031"}


def test_f08c_refused(f08c_card):
    name, r = fit.fit(f08c_card)
    assert name == "temp"
    assert r["verdict"] == "refused"
    assert r["best"]["residual_cells"] > 100
    assert len(r["frames_tried"]) == len(fit.FRAMES)


def test_fitted_assertion_matches_declared_twin(fixtures, f03d_card):
    doc = fit.assertion(f03d_card)
    assert doc["kind"] == "grid"
    assert doc["asserts"]["spatial:transform"] == BREMEN_SOUTH
    assert doc["asserts"]["proj:code"] == "EPSG:3412"
    assert doc["evidence"]["residual_cells"] < 1e-6
    json.dumps(doc, allow_nan=False)
    asserted = card(fixtures["f03d-asi-latlon2d"][0], probe_hosts=False, assertions=[doc])
    twin = card(fixtures["f03e-asi-projjson"][0], probe_hosts=False)
    va, vt = asserted["variables"][0], twin["variables"][0]
    assert va["grid"]["costume"] == vt["grid"]["costume"] == "B"
    for k in ("spatial:transform", "spatial:shape", "spatial:dimensions"):
        assert va["grid"]["transform"][k] == vt["grid"]["transform"][k]
    assert set(asserted["findings_summary"]) == set(twin["findings_summary"])


def test_refusal_document(f08c_card):
    doc = fit.assertion(f08c_card)
    assert doc["kind"] == "refusal"
    assert doc["refuses"]["frames_tried"] == list(fit.FRAMES)
    assert doc["evidence"]["best"]["residual_cells"] > 100
    A.validate(doc)


def test_published_assertion_is_the_fit(f03d_card):
    """assertions/f03d-asi-latlon2d.json asserts what the fit finds."""
    doc = json.loads((ROOT / "assertions" / "f03d-asi-latlon2d.json").read_text())
    fitted = fit.assertion(f03d_card)
    assert doc["asserts"] == fitted["asserts"]
    assert doc["evidence"]["method"] == fitted["evidence"]["method"]


def _sample(lon2, lat2):
    """A card-like variable over 2-D arrays, sampled as the card samples."""
    from storecard.card import _jsonable, _sample_2d
    cs = _jsonable(_sample_2d(lon2, lat2))
    cs["lon"], cs["lat"] = "lon", "lat"
    return {"name": "v", "grid": {"coord_sample": cs}}


def test_cryptically_degenerate_lonlat_fits_4326():
    lon = 100.125 + 0.25 * np.arange(400)          # crosses the antimeridian
    lon = (lon + 180) % 360 - 180
    lat = 60.0 - 0.25 * (np.arange(200) + 0.5)
    lon2, lat2 = np.meshgrid(lon, lat)
    r = fit.fit_variable(_sample(lon2, lat2))
    assert r["verdict"] == "fitted"
    assert r["proj:code"] == "EPSG:4326"
    assert r["spatial:transform"] == [0.25, 0.0, 100.0, 0.0, -0.25, 60.0]


def test_jittered_grid_refused():
    lon2, lat2 = np.meshgrid(np.linspace(-170, 170, 300), np.linspace(-60, 60, 200))
    lon2 = lon2 + 0.3 * np.sin(lat2 / 7.0)
    r = fit.fit_variable(_sample(lon2, lat2))
    assert r["verdict"] == "refused"


def test_no_sample_refused():
    r = fit.fit_variable({"name": "v", "grid": {}})
    assert r["verdict"] == "refused" and r["frames_tried"] == []
