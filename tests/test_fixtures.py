"""Known cards for the portolan fixtures.

Each fixture has a stated presentation (portolan/README.md and
portolan/docs/fixtures-plan.md), so the facts its card must record are known
in advance. These tests state them.
"""

import json

import pytest

from storecard import card

ALL = [
    "f01a-oisst-native", "f01b-oisst-ydesc", "f01c-oisst-180", "f01d-oisst-transform",
    "f01e-oisst-unpacked", "f01f-oisst-nodata",
    "f03a-asi-native", "f03b-asi-rowchunk", "f03c-asi-transform", "f03d-asi-latlon2d",
    "f03e-asi-projjson", "f03f-asi-gridmap-named",
    "f03g-g02202-native", "f03h-g02202-percent",
    "f08a-esm-native", "f08b-esm-levelchunk", "f08c-esm-geo2d", "f08d-esm-regular",
]

# finding codes each fixture's card must carry, and no others. The F08 STAC
# nodata is -1e20 as a JSON (float64) number, which no float32 value equals.
FINDINGS = {
    "f01a-oisst-native": {"LON_0_360", "Y_ASCENDING"},
    "f01b-oisst-ydesc": {"LON_0_360"},
    "f01c-oisst-180": {"Y_ASCENDING"},
    "f01d-oisst-transform": {"LON_0_360"},
    "f01e-oisst-unpacked": {"LON_0_360"},
    "f01f-oisst-nodata": {"LON_0_360"},
    "f03a-asi-native": {"Y_ASCENDING"},
    "f03b-asi-rowchunk": {"Y_ASCENDING"},
    "f03c-asi-transform": set(),
    "f03d-asi-latlon2d": {"GRID_2D_LONLAT_ONLY", "CRS_NOT_DECLARED"},
    "f03e-asi-projjson": set(),
    "f03f-asi-gridmap-named": {"Y_ASCENDING"},
    "f03g-g02202-native": set(),
    "f03h-g02202-percent": set(),
    "f08a-esm-native": {"COORDS_NAMED_MISSING", "COORD_IRREGULAR", "LON_BELOW_MINUS_180",
                        "Y_ASCENDING", "CRS_NOT_DECLARED", "FILL_NOT_REPRESENTABLE"},
    "f08b-esm-levelchunk": {"COORDS_NAMED_MISSING", "COORD_IRREGULAR", "LON_BELOW_MINUS_180",
                            "Y_ASCENDING", "CRS_NOT_DECLARED", "FILL_NOT_REPRESENTABLE"},
    "f08c-esm-geo2d": {"COORD_IRREGULAR", "LON_BELOW_MINUS_180", "Y_ASCENDING",
                       "CRS_NOT_DECLARED", "NOMINAL_AXES_DISAGREE", "FILL_NOT_REPRESENTABLE"},
    "f08d-esm-regular": {"FILL_NOT_REPRESENTABLE"},
}

# the declared grid form of the (first, level 0) data variable
FORM = {
    "f01a-oisst-native": "coords_1d_regular",
    "f01d-oisst-transform": "transform",
    "f03c-asi-transform": "transform",
    "f03d-asi-latlon2d": "coords_2d",
    "f03e-asi-projjson": "transform",
    "f08a-esm-native": "coords_1d_irregular",
    "f08c-esm-geo2d": "coords_2d",
    "f08d-esm-regular": "coords_1d_regular",
}


@pytest.fixture(scope="session")
def cards(fixtures):
    return {fid: card(s, stac=c, probe_hosts=False) for fid, (s, c) in fixtures.items()}


def var(c, name=None):
    vs = c["variables"]
    return vs[0] if name is None else next(v for v in vs if v["name"] == name)


def codes(c):
    return {f["code"] for f in c["findings"]}


def test_all_fixtures_built(fixtures):
    assert sorted(fixtures) == sorted(ALL)


@pytest.mark.parametrize("fid", ALL)
def test_card_is_json_and_versioned(cards, fid):
    c = cards[fid]
    json.dumps(c, allow_nan=False)
    assert c["card_version"] == "0"
    assert c["source"]["form"] == "zarr v3"


@pytest.mark.parametrize("fid", ALL)
def test_findings(cards, fid):
    assert codes(cards[fid]) == FINDINGS[fid]


@pytest.mark.parametrize("fid", sorted(FORM))
def test_grid_form(cards, fid):
    assert var(cards[fid])["grid"]["form"] == FORM[fid]


def test_twins_share_shape_and_grid(cards):
    """f01a, b, c differ in presentation only: same shape, same steps."""
    ref = var(cards["f01a-oisst-native"])
    for fid in ("f01b-oisst-ydesc", "f01c-oisst-180", "f01e-oisst-unpacked", "f01f-oisst-nodata"):
        v = var(cards[fid])
        assert v["shape"] == ref["shape"] == [2, 1, 720, 1440]
        assert abs(v["grid"]["axes"]["x"]["step_median"]) == 0.25
        assert abs(v["grid"]["axes"]["y"]["step_median"]) == 0.25


def test_packing_recorded(cards):
    v = var(cards["f01a-oisst-native"])["values"]
    assert v["dtype"] == "int16"
    assert v["packing"] == {"scale_factor": 0.01, "add_offset": 0.0}
    assert v["fill_agree"] is True
    assert "packing" not in var(cards["f01e-oisst-unpacked"])["values"]


def test_flags_and_valid_range(cards):
    v = var(cards["f03g-g02202-native"])["values"]
    assert v["dtype"] == "uint8"
    assert v["packing"]["scale_factor"] == 0.01
    assert v["valid_range"] == [0, 100]
    assert v["flag_values"] == [251, 252, 253, 254]


def test_stac_nodata_is_a_fill_source(cards):
    fills = {f["from"]: f for f in var(cards["f01f-oisst-nodata"])["values"]["fill"]}
    assert fills["STAC nodata"]["value"] == -999
    assert "STAC nodata" not in {f["from"] for f in var(cards["f01b-oisst-ydesc"])["values"]["fill"]}


def test_transform_declared(cards):
    g = var(cards["f03c-asi-transform"], "0/z")["grid"]
    t = g["transform"]
    assert t["spatial:shape"] == [2656, 2528]
    assert t["spatial:transform"][0] == 3125.0
    assert t["spatial:transform"][4] == -3125.0
    assert "coords_1d_regular" in g["declared"]


def test_crs_sources(cards):
    via = lambda fid: {s["via"] for s in var(cards[fid])["crs"]["sources"]}
    assert via("f03e-asi-projjson") == {"proj:projjson"}
    pj = var(cards["f03e-asi-projjson"])["crs"]["sources"][0]
    assert pj["id"] == "EPSG:3412"
    gm = var(cards["f03f-asi-gridmap-named"])["crs"]["sources"][0]
    assert gm["via"] == "cf grid_mapping" and gm["var"] == "polar_stereographic"
    assert gm["grid_mapping_name"] == "polar_stereographic" and gm["crs_wkt"]
    assert not var(cards["f03d-asi-latlon2d"])["crs"]["declared"]


def test_multiscales(cards):
    assert cards["f01d-oisst-transform"]["source"]["multiscales"]["levels"] == ["0", "1", "2"]
    names = [v["name"] for v in cards["f03c-asi-transform"]["variables"]]
    assert names == ["0/z", "1/z", "2/z"]


def test_amplification(cards):
    cost = lambda fid: var(cards[fid])["cost"]
    # f03b is chunked one row per chunk: a 256 px tile reads about 10x what it draws,
    # wherever the window falls (rows are whole)
    assert cost("f03b-asi-rowchunk")["tile_amplification"] == {"aligned": 9.875, "worst": 9.875}
    # 512 px chunks: 4x aligned, 16x across a chunk corner
    assert cost("f03a-asi-native")["tile_amplification"] == {"aligned": 4.0, "worst": 16.0}
    # f08a packs 25 depth levels per chunk; f08b one level per chunk; no shards
    assert cost("f08a-esm-native")["nonspatial_read_factor"] == {"inner": 25, "shard": 25}
    assert cost("f08b-esm-levelchunk")["nonspatial_read_factor"] == {"inner": 1, "shard": 1}


COSTUME = {
    "f01a-oisst-native": "C", "f01b-oisst-ydesc": "C", "f01c-oisst-180": "C",
    "f01d-oisst-transform": "B", "f01e-oisst-unpacked": "C", "f01f-oisst-nodata": "C",
    "f03a-asi-native": "C", "f03b-asi-rowchunk": "C", "f03c-asi-transform": "B",
    "f03d-asi-latlon2d": ["E", "H"], "f03e-asi-projjson": "B", "f03f-asi-gridmap-named": "C",
    "f03g-g02202-native": "C", "f03h-g02202-percent": "C",
    # the tripolar grid presents as G; NOMINAL_AXES_DISAGREE on f08c is the evidence it is not
    "f08a-esm-native": "G", "f08b-esm-levelchunk": "G", "f08c-esm-geo2d": ["E", "H"],
    "f08d-esm-regular": "C",
}


@pytest.mark.parametrize("fid", ALL)
def test_costume(cards, fid):
    for v in cards[fid]["variables"]:
        assert v["grid"]["costume"] == COSTUME[fid]


def test_findings_summary(cards):
    s = cards["f01d-oisst-transform"]["findings_summary"]
    assert s == {"LON_0_360": ["0/sst", "1/sst", "2/sst"]}


def test_coord_sample_for_grid_fit(cards):
    """f03d: the 2-D lon/lat sample is what a grid fit needs (edges plus central cross)."""
    g = var(cards["f03d-asi-latlon2d"])["grid"]
    cs = g["coord_sample"]
    assert cs["shape"] == [2656, 2528]
    assert [r["index"] for r in cs["rows"]] == [0, 1328, 2655]
    assert [c["index"] for c in cs["cols"]] == [0, 1264, 2527]
    for line in cs["rows"] + cs["cols"]:
        assert len(line["at"]) == len(line["lon"]) == len(line["lat"]) <= 257
        assert line["at"][0] == 0


def test_stac_nodata_not_representable(cards):
    f = [f for f in cards["f08a-esm-native"]["findings"] if f["code"] == "FILL_NOT_REPRESENTABLE"]
    assert [x["source"] for x in f] == ["STAC nodata"]
    # the store's own fills agree with each other
    fills = var(cards["f08a-esm-native"])["values"]["fill"]
    zf = next(x for x in fills if x["from"] == "zarr fill_value")
    cf = next(x for x in fills if x["from"] == "CF _FillValue")
    assert zf["in_dtype"] == cf["in_dtype"]


def test_crs_only_in_stac(cards):
    crs = var(cards["f08a-esm-native"])["crs"]
    assert crs["declared"] is False
    assert crs["sources"] == [{"via": "STAC proj:code", "value": "EPSG:4326"}]


def test_tripolar_nominal_axes_flagged(cards):
    g = var(cards["f08c-esm-geo2d"])["grid"]
    assert g["nominal_deviation"]["max_cells"] > 0.5
    assert g["axes"]["y"]["spacing"] == "irregular"
    assert "values" in g["axes"]["y"]          # 300 values: carried whole


def test_no_data_chunks_read(fixtures, monkeypatch):
    """A card reads coordinate arrays only, never a data variable's chunks."""
    import zarr
    read = []
    orig = zarr.Array.__getitem__

    def spy(self, sel):
        read.append(self.path)
        return orig(self, sel)

    monkeypatch.setattr(zarr.Array, "__getitem__", spy)
    for fid in ("f01a-oisst-native", "f03d-asi-latlon2d", "f08c-esm-geo2d"):
        read.clear()
        c = card(fixtures[fid][0], probe_hosts=False)
        data = {v["name"] for v in c["variables"]}
        assert read and not (set(read) & data)
