"""Opt-in network test against a real, near-conforming store.

Skipped unless STORECARD_NETWORK=1. Needs the [remote] extra (fsspec, aiohttp).
The expected facts are from a run of the card against this store on
2026-11-07; if the publisher changes the store, update them.
"""

import os

import pytest

from storecard import card

URL = "https://data.source.coop/ftw/global-data/predictions/zarr/alpha/global.zarr"
STAC = "https://data.source.coop/ftw/global-data/predictions/zarr/collection.json"

pytestmark = pytest.mark.skipif(os.environ.get("STORECARD_NETWORK") != "1",
                                reason="set STORECARD_NETWORK=1 to run network tests")


@pytest.fixture(scope="module")
def ftw():
    return card(URL, stac=STAC)


def test_ftw_declares_its_grid(ftw):
    assert ftw["variables"]
    for v in ftw["variables"]:
        assert "transform" in v["grid"]["declared"]
        assert v["crs"]["declared"]
        assert v["grid"]["costume"] == "B"
        assert v["values"].get("fill_agree") in (True, None)


def test_ftw_host(ftw):
    h = ftw["hosts"][0]
    assert h["status"] == 206 and h["cors"] == "*" and h["range"]


def test_ftw_longitude(ftw):
    # the store is -180..180; coarse overviews overshoot the antimeridian slightly
    assert "LON_0_360" not in ftw["findings_summary"]
    assert len(ftw["findings_summary"]["LON_OVERSHOOT_180"]) == 8


def test_ftw_sharded_cost(ftw):
    shard = [v for v in ftw["variables"] if v["cost"]["shards"]]
    assert shard
    v = shard[0]
    assert v["cost"]["nonspatial_read_factor"] == {"inner": 1, "shard": 3}
    assert v["cost"]["tile_amplification"] == {"aligned": 4.0, "worst": 16.0}


PAWSEY = "https://projects.pawsey.org.au/aad-derived/portolan-fixtures/catalog/catalog.json"


def _get(url):
    import json
    import time
    import urllib.request
    for i in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except OSError:
            time.sleep(2 * (i + 1))
    raise OSError(f"could not fetch {url}")


def test_pawsey_published_fixtures_match_local_expectations():
    """The published fixtures give the cards stated in test_fixtures.py."""
    import urllib.parse
    from test_fixtures import COSTUME, FINDINGS
    cat = _get(PAWSEY)
    seen = 0
    for link in cat["links"]:
        if link["rel"] != "child":
            continue
        col = _get(urllib.parse.urljoin(PAWSEY, link["href"]))
        fid = col["id"]
        if fid not in FINDINGS:
            continue                      # e.g. the north G02202 twins, not built locally
        href = next(a for a in col["assets"].values() if "data" in a.get("roles", []))["href"]
        c = card(href, stac=col)
        assert set(c["findings_summary"]) - {"GROUP_NOT_LISTABLE"} == FINDINGS[fid], fid
        assert all(v["grid"]["costume"] == COSTUME[fid] for v in c["variables"]), fid
        assert c["hosts"][0]["cors"] == "*"
        seen += 1
    assert seen >= 15


def test_pawsey_f03d_assertion_matches_twin():
    """The published assertion for f03d makes its card match its declared twin."""
    import json
    import pathlib
    doc = json.loads((pathlib.Path(__file__).parents[1] / "assertions" / "f03d-asi-latlon2d.json").read_text())
    base = "https://projects.pawsey.org.au/aad-derived/portolan-fixtures/catalog/f03/"
    d = _get(base + "f03d-asi-latlon2d/collection.json")
    e = _get(base + "f03e-asi-projjson/collection.json")
    asserted = card(d["assets"]["data"]["href"], stac=d, assertions=[doc])
    twin = card(e["assets"]["data"]["href"], stac=e)
    assert asserted["source"]["assertions"][0]["applied"], asserted["source"]["assertions"]
    va, vt = asserted["variables"][0], twin["variables"][0]
    assert va["grid"]["costume"] == vt["grid"]["costume"] == "B"
    for k in ("spatial:transform", "spatial:shape", "spatial:dimensions"):
        assert va["grid"]["transform"][k] == vt["grid"]["transform"][k]
    assert set(asserted["findings_summary"]) == set(twin["findings_summary"])
