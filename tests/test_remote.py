"""Opt-in network test against a real, near-conforming store.

Skipped unless STORECARD_NETWORK=1. Needs the [remote] extra (fsspec, aiohttp).
The expected facts are from a run of the card against this store on
2026-11-07; if the publisher changes the store, update them.
"""

import json
import os
import pathlib

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


# ---------------------------------------------------------------- ausantarctic virtual stores

SCRATCH = "https://data.source.coop/ausantarctic/ausantarctic-scratch/"
# store: (host its chunk references point at, that host's CORS answer, findings)
# from runs on 2026-11-09; both forms (kerchunk Parquet, Icechunk) give the same
VIRTUAL = {
    "oisst/oisst-v2.1-daily": (
        "noaa-cdr-sea-surface-temp-optimum-interpolation-pds.s3.amazonaws.com", "*",
        {"LON_0_360", "Y_ASCENDING", "CRS_NOT_DECLARED"}),
    "seaice/g02202-v6-daily-south": (
        "noaadata.apps.nsidc.org", None,
        {"CRS_NOT_DECLARED", "PROJECTED_NO_GRID_MAPPING", "CHUNK_HOST_NO_CORS"}),
    "seaice/asi-amsr2-v5.4-daily-south": (
        "data.seaice.uni-bremen.de", None,
        {"Y_ASCENDING", "CRS_NOT_DECLARED", "PROJECTED_NO_GRID_MAPPING", "CHUNK_HOST_NO_CORS"}),
    "bluelink/bluelink-daily-salt": (
        "thredds.nci.org.au", "*",
        {"COORDS_NAMED_MISSING", "LON_0_360", "Y_ASCENDING", "CRS_NOT_DECLARED"}),
    "ghrsst/ghrsst-mur-cog-analysed_sst": (
        "data.source.coop", "*", {"CRS_NOT_DECLARED"}),
}
# raad.virtualize writes CF _FillValue into the Icechunk form only; the
# kerchunk form carries the same value as Zarr fill_value alone
KERCHUNK_NO_CF_FILL = {"oisst/oisst-v2.1-daily", "seaice/g02202-v6-daily-south",
                       "bluelink/bluelink-daily-salt", "ghrsst/ghrsst-mur-cog-analysed_sst"}


@pytest.fixture(scope="module")
def virtual_cards():
    cache = {}

    def get(store, form):
        if (store, form) not in cache:
            cache[store, form] = card(SCRATCH + store + "/" + form)
        return cache[store, form]
    return get


@pytest.mark.parametrize("form", ["kerchunk", "icechunk"])
@pytest.mark.parametrize("store", list(VIRTUAL))
def test_ausantarctic_virtual_store(virtual_cards, store, form):
    host, cors, findings = VIRTUAL[store]
    c = virtual_cards(store, form)
    assert c["source"]["form"] == ("kerchunk parquet" if form == "kerchunk" else "icechunk")
    assert set(c["findings_summary"]) == findings
    meta, *chunks = c["hosts"]
    assert meta["role"] == "metadata" and meta["cors"] == "*"
    assert [h["host"] for h in chunks] == [host]
    assert chunks[0]["cors"] == cors and chunks[0]["range"]
    if host == "thredds.nci.org.au":
        # THREDDS refuses HEAD with an Origin and serves the browser's GET
        assert chunks[0]["head"]["status"] == 403 and chunks[0]["method"] == "GET bytes=0-0"
    if form == "icechunk":
        assert c["source"]["snapshot"]
        assert c["source"]["virtual_chunk_containers"] == [f"https://{host}/"]


@pytest.mark.parametrize("store", list(VIRTUAL))
def test_ausantarctic_forms_agree(virtual_cards, store):
    k, i = virtual_cards(store, "kerchunk"), virtual_cards(store, "icechunk")
    for vk, vi in zip(k["variables"], i["variables"]):
        cf = [f for f in vi["values"]["fill"] if f["from"] == "CF _FillValue"]
        if store in KERCHUNK_NO_CF_FILL:
            assert cf and cf[0]["value"] == vk["values"]["fill"][0]["value"]
            vi = dict(vi, values=dict(vi["values"], fill=[f for f in vi["values"]["fill"] if f not in cf]))
            vi["values"].pop("fill_agree", None)
            vk = dict(vk, values=dict(vk["values"]))
            vk["values"].pop("fill_agree", None)
        assert vk == vi, vk["name"]


# the published CRS assertions for these stores (assertions/ausantarctic/,
# built by its build.py): each must still apply (digest current) and clear
# the CRS findings, leaving the store's other findings as they are
ASSERTED = {
    "oisst/oisst-v2.1-daily": "EPSG:4326",
    "seaice/g02202-v6-daily-south": "EPSG:3412",
    "seaice/g02202-v6-daily-north": "EPSG:3411",
    "seaice/asi-amsr2-v5.4-daily-south": "EPSG:3976",
    "ghrsst/ghrsst-mur-cog-analysed_sst": "EPSG:4326",
}
ASSERTIONS_DIR = pathlib.Path(__file__).parent.parent / "assertions" / "ausantarctic"


@pytest.mark.parametrize("form", ["kerchunk", "icechunk"])
@pytest.mark.parametrize("store", list(ASSERTED))
def test_ausantarctic_crs_assertions_apply(store, form):
    docs = sorted((ASSERTIONS_DIR / store.split("/")[1]).glob(f"{form}-*.json"))
    assert docs
    c = card(SCRATCH + store + "/" + form, probe_hosts=False, assertions=docs)
    assert all(a["applied"] for a in c["source"]["assertions"]), c["source"]["assertions"]
    asserted = {json.loads(d.read_text())["subject"]["variable"] for d in docs}
    for v in c["variables"]:
        if v["name"] in asserted:
            assert v["crs"]["declared"]
            assert v["crs"]["sources"][0] == {"via": "proj:code", "on": "assertion",
                                               "value": ASSERTED[store]}
    if store in VIRTUAL:
        # the GHRSST overview arrays are not asserted, so they keep CRS_NOT_DECLARED
        crs = {"PROJECTED_NO_GRID_MAPPING"} | ({"CRS_NOT_DECLARED"} if not store.startswith("ghrsst") else set())
        # hosts are not probed here, so no host findings either
        assert set(c["findings_summary"]) == VIRTUAL[store][2] - crs - {"CHUNK_HOST_NO_CORS"}
