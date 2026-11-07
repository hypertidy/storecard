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


def test_ftw_sharded_cost(ftw):
    shard = [v for v in ftw["variables"] if v["cost"]["shards"]]
    assert shard
    assert all(v["cost"]["nonspatial_read_factor"]["inner"] <= v["cost"]["nonspatial_read_factor"]["shard"]
               for v in shard)
