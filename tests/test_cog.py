"""GeoTIFF and COG cards (storecard.cog), on small synthetic COGs made with
osgeo.gdal that copy the header facts of real files in the Tasmanian LIST
mirror (source.coop mdsumner/thelist-opendata): a 25 m DEM tile with an
unnamed Transverse Mercator WKT and an origin 2e-7 m off round, the same
tile declared cleanly, a 6-band Landsat mosaic with no band names, a class
grid with an internal mask and no nodata, and a stripped GeoTIFF.

Needs osgeo.gdal; skipped without it. The opt-in network tests
(STORECARD_NETWORK=1) check the published LIST files themselves.
"""

import os

import numpy as np
import pytest

gdal = pytest.importorskip("osgeo.gdal")
osr = pytest.importorskip("osgeo.osr")

from storecard import assertion as A  # noqa: E402
from storecard import card, cog  # noqa: E402

gdal.UseExceptions()

# the CRS of half the LIST 25 m DEM tiles: EPSG:28355 in all but name and id
UNNAMED_TM = (
    'PROJCS["unnamed",GEOGCS["GDA94",DATUM["Geocentric_Datum_of_Australia_1994",'
    'SPHEROID["GRS 1980",6378137,298.257222101004]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],'
    'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",147],'
    'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],'
    'PARAMETER["false_northing",10000000],UNIT["metre",1]]'
)
HOBART_GT = (515975.0, 25.0, 0.0, 5256399.9999998, 0.0, -25.0)
MOSAIC_GT = (507500.0, 25.0, 0.0, 5277424.999999801, 0.0, -25.0)

URL = "https://data.source.coop/mdsumner/thelist-opendata/cog/"


def _cog(path, arr, gt, srs, nodata=None, mask=False, options=("COMPRESS=ZSTD", "BLOCKSIZE=64"),
         driver="COG", descriptions=None):
    bands = 1 if arr.ndim == 2 else arr.shape[0]
    ny, nx = arr.shape[-2:]
    dt = gdal.GetDataTypeByName({"uint8": "Byte", "uint16": "UInt16", "float32": "Float32"}[str(arr.dtype)])
    mem = gdal.GetDriverByName("MEM").Create("", nx, ny, bands, dt)
    mem.SetGeoTransform(gt)
    mem.SetProjection(srs)
    for i in range(bands):
        b = mem.GetRasterBand(i + 1)
        b.WriteArray(arr if arr.ndim == 2 else arr[i])
        if nodata is not None:
            b.SetNoDataValue(nodata)
        if descriptions:
            b.SetDescription(descriptions[i])
    if mask:
        mem.CreateMaskBand(gdal.GMF_PER_DATASET)
        mem.GetRasterBand(1).GetMaskBand().WriteArray(np.full((ny, nx), 255, "uint8"))
    gdal.GetDriverByName(driver).CreateCopy(str(path), mem, options=list(options))
    return str(path)


@pytest.fixture(scope="module")
def tifs(tmp_path_factory):
    d = tmp_path_factory.mktemp("cog")
    dem = np.arange(200 * 150, dtype="float32").reshape(200, 150)
    epsg = osr.SpatialReference()
    epsg.ImportFromEPSG(28355)
    out = {
        "dem_unnamed": _cog(d / "dem_unnamed.tif", dem, HOBART_GT, UNNAMED_TM, nodata=-9999.0),
        "dem_clean": _cog(d / "dem_clean.tif", dem, (515975.0, 25.0, 0.0, 5256400.0, 0.0, -25.0),
                          epsg.ExportToWkt(), nodata=-9999.0),
        "mosaic": _cog(d / "mosaic.tif", np.zeros((900, 900), "float32"), MOSAIC_GT,
                       epsg.ExportToWkt(), nodata=-9999.0),
        "landsat": _cog(d / "landsat.tif", np.ones((6, 100, 100), "uint8"),
                        (415035.0, 30.0, 0.0, 5274005.0, 0.0, -30.0), epsg.ExportToWkt(), nodata=0,
                        options=("COMPRESS=ZSTD", "BLOCKSIZE=64", "INTERLEAVE=PIXEL")),
        "classes": _cog(d / "classes.tif", np.ones((100, 100), "uint16"),
                        (208769.62982903194, 30.0, 0.0, 5639399.606977775, 0.0, -30.0),
                        epsg.ExportToWkt(), mask=True),
        "stripped": _cog(d / "stripped.tif", dem, HOBART_GT, epsg.ExportToWkt(), nodata=-9999.0,
                         driver="GTiff", options=("COMPRESS=DEFLATE",)),
    }
    return out


@pytest.fixture(scope="module")
def cards(tifs):
    return {k: card(p, probe_hosts=False) for k, p in tifs.items()}


def codes(c):
    return set(c["findings_summary"])


def test_form_and_costume(cards):
    for k, c in cards.items():
        assert c["source"]["form"] == ("geotiff" if k == "stripped" else "cog"), k
        for v in c["variables"]:
            assert v["grid"]["costume"] == "B"
            assert v["grid"]["declared"] == ["transform"]
            assert v["crs"]["declared"]


def test_unnamed_crs_and_near_round_origin(cards):
    c = cards["dem_unnamed"]
    assert codes(c) == {"CRS_NO_AUTHORITY_ID", "TRANSFORM_NEAR_ROUND"}
    f = next(x for x in c["findings"] if x["code"] == "CRS_NO_AUTHORITY_ID")
    assert f["best_match"] == "EPSG:28355" and f["equivalent"] is True
    g = c["variables"][0]["grid"]
    assert g["near_round"]["y_origin"]["round"] == 5256400.0
    assert "x_origin" not in g["near_round"]
    assert g["transform"]["spatial:transform"] == [25.0, 0.0, 515975.0, 0.0, -25.0, 5256399.9999998]


def test_clean_tile_has_no_findings(cards):
    c = cards["dem_clean"]
    assert c["findings"] == []
    v = c["variables"][0]
    assert v["crs"]["sources"][0]["id"] == "EPSG:28355"
    assert v["values"]["fill"][0]["raw"] == "-9999"
    assert v["values"]["mask"] == "nodata"
    assert v["cost"]["chunks"] == [64, 64]
    assert v["cost"]["overviews"]  # COG driver builds them down to one block
    assert v["cost"]["coarsest_spatial_chunks"] == 1


def test_fractional_origin_is_not_near_round(cards):
    # the NCH grids sit on origins like 208769.6298...: a fact, not a near miss
    c = cards["classes"]
    assert "TRANSFORM_NEAR_ROUND" not in codes(c)
    assert c["variables"][0]["grid"]["lattice"]["x_offset_cells"] == pytest.approx(0.987661, abs=1e-6)


def test_class_grid_has_mask_not_nodata(cards):
    v = cards["classes"]["variables"][0]
    assert v["values"]["fill"] == []
    assert v["values"]["mask"] == "per dataset"
    assert "FILL_NOT_DECLARED" not in codes(cards["classes"])


def test_landsat_bands_unnamed_and_pixel_interleave(cards):
    c = cards["landsat"]
    assert "BANDS_UNNAMED" in codes(c)
    assert len(c["variables"]) == 6
    assert c["source"]["interleave"] == "PIXEL"
    assert c["variables"][0]["cost"]["nonspatial_read_factor"]["inner"] == 6


def test_stripped_geotiff(cards):
    assert "GEOTIFF_STRIPPED" in codes(cards["stripped"])
    assert cards["stripped"]["variables"][0]["cost"]["tiled"] is False


def test_nodata_tag_read_as_written(tmp_path):
    # a float64 nodata a float32 band cannot hold: GDAL rounds it on read,
    # the tag (what other readers parse) keeps the declared value
    p = _cog(tmp_path / "nd.tif", np.zeros((64, 64), "float32"), HOBART_GT, UNNAMED_TM, nodata=-1e20)
    v = card(p, probe_hosts=False)["variables"][0]
    fl = v["values"]["fill"][0]
    assert fl["raw"] in ("-1e+20", "-1e20", "-100000000000000000000")
    assert fl["value"] == -1e20
    assert fl["representable"] is False


def test_tidy_assertion_applies_and_clears_findings(cards, tifs):
    doc = cog.tidy_assertion(cards["dem_unnamed"])
    a = doc["asserts"]
    assert a["proj:code"] == "EPSG:28355"
    assert a["spatial:transform"] == [25.0, 0.0, 515975.0, 0.0, -25.0, 5256400.0]
    assert doc["crs_axes"] == ["x", "y"]
    c = card(tifs["dem_unnamed"], probe_hosts=False, assertions=[doc])
    assert c["findings"] == []
    v = c["variables"][0]
    assert v["grid"]["transform"]["from"] == "assertion"
    assert v["crs"]["sources"][0] == {"via": "proj:code", "on": "assertion", "value": "EPSG:28355"}
    assert c["source"]["assertions"][0]["applied"] is True
    # the tidied card says what the clean twin says
    clean = cards["dem_clean"]["variables"][0]
    assert v["grid"]["transform"]["spatial:transform"] == clean["grid"]["transform"]["spatial:transform"]


def test_nothing_to_tidy_on_clean_tile(cards):
    with pytest.raises(A.AssertionError_):
        cog.tidy_assertion(cards["dem_clean"])


def test_stale_assertion(cards, tifs, tmp_path):
    doc = cog.tidy_assertion(cards["dem_unnamed"])
    other = _cog(tmp_path / "other.tif", np.zeros((200, 150), "float32"), HOBART_GT, UNNAMED_TM, nodata=-1.0)
    c = card(other, probe_hosts=False, assertions=[doc])
    assert "ASSERTION_STALE" in codes(c)
    assert c["source"]["assertions"][0]["applied"] is False


def test_vrt_opens_with_asserted_grid(cards, tifs, tmp_path):
    doc = cog.tidy_assertion(cards["dem_unnamed"])
    vrt = A.to_vrt(doc, cards["dem_unnamed"])
    p = tmp_path / "tidy.vrt"
    p.write_text(vrt)
    ds = gdal.Open(str(p))
    assert ds.GetGeoTransform() == (515975.0, 25.0, 0.0, 5256400.0, 0.0, -25.0)
    srs = ds.GetSpatialRef()
    assert (srs.GetAuthorityName(None), srs.GetAuthorityCode(None)) == ("EPSG", "28355")
    assert ds.GetRasterBand(1).GetNoDataValue() == -9999.0
    src = gdal.Open(tifs["dem_unnamed"])
    assert np.array_equal(ds.ReadAsArray(), src.ReadAsArray())


def test_lattice_member(cards, tifs):
    # tile and mosaic on one 25 m lattice, both origins a hair off round
    tile, mosaic = cards["dem_unnamed"], cards["mosaic"]
    w = cog.lattice_member(tile, mosaic)
    assert w == {"col": 339, "row": 841, "ncol": 150, "nrow": 200, "inside": False}
    assert cog.lattice_member(cards["classes"], mosaic) is None


def test_card_digest_ignores_gdal_version(tifs):
    h = cog.read_header(tifs["dem_clean"])
    d1 = cog.header_digest(h)
    h["gdal_version"] = "0.0.0"
    assert cog.header_digest(h) == d1


# ---------------------------------------------------------------- network

network = pytest.mark.skipif(os.environ.get("STORECARD_NETWORK") != "1",
                             reason="set STORECARD_NETWORK=1 to run network tests")


@network
@pytest.mark.parametrize("lga,crs_name,nodata_raw", [
    ("brighton", "GDA_1994_Transverse_Mercator", "3.3999999521443642e+38"),
    ("hobart", "unnamed", "-9999"),
])
def test_list_dem_tiles(lga, crs_name, nodata_raw):
    # facts from a run on 2026-11-21; update if the mirror is rebuilt
    c = card(f"{URL}list_dem_25m/{lga}/list_dem_25m_{lga}.tif")
    assert c["source"]["form"] == "cog"
    assert codes(c) == {"CRS_NO_AUTHORITY_ID", "TRANSFORM_NEAR_ROUND"}
    v = c["variables"][0]
    assert v["crs"]["sources"][0]["name"] == crs_name
    fl = v["values"]["fill"][0]
    assert fl["raw"] == nodata_raw and fl["representable"] is True
    assert c["hosts"][0]["cors"] == "*" and c["hosts"][0]["range"]
    doc = cog.tidy_assertion(c)
    assert doc["asserts"]["proj:code"] == "EPSG:28355"
    assert card(c["source"]["url"], probe_hosts=False, assertions=[doc])["findings"] == []


@network
def test_list_dem_tile_is_window_of_statewide():
    t = card(f"{URL}list_dem_25m/hobart/list_dem_25m_hobart.tif", probe_hosts=False)
    m = card(f"{URL}list_dem_25m/statewide/list_dem_25m_statewide.tif", probe_hosts=False)
    assert codes(m) == {"TRANSFORM_NEAR_ROUND"}
    assert cog.lattice_member(t, m) == {"col": 11556, "row": 16222, "ncol": 543, "nrow": 438, "inside": True}


@network
def test_list_landsat_bands_unnamed():
    c = card(f"{URL}tas_landsat_mosaic_2013_2014/statewide/tas_landsat_mosaic_1314_mga55.tif", probe_hosts=False)
    assert codes(c) == {"BANDS_UNNAMED"}
    assert len(c["variables"]) == 6
