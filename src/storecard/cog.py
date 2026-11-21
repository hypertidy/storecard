"""Store cards for GeoTIFF and Cloud Optimized GeoTIFF (COG), via osgeo.gdal.

A GeoTIFF declares its grid in its header: a geotransform and a CRS. So a
COG card is mostly costume B, and what it records is whether those
declarations are exact: a CRS carried as WKT without an authority id, a
nodata value the band's type cannot hold, an origin a hair off the round
number it was meant to be. It also records what the cost and values
sections record for Zarr: block (chunk) shape, overviews, interleave,
compression, colour tables, attribute tables and band names.

Only the header is read (gdal.Open, which fetches the IFDs and tags); never
a pixel block. Each band is one variable, named band_1, band_2, ...

Entry points: card_cog(url) (also reached from storecard.card for .tif
URLs or form="cog"), tidy_assertion(card), to_vrt(doc, card).
"""

import datetime
import hashlib
import json
import math
import xml.etree.ElementTree as ET

from . import assertion as A

COG = "cog"
GEOTIFF = "geotiff"
SUFFIXES = (".tif", ".tiff", ".gtiff", ".cog")

# an origin within this fraction of a cell of a round value is "near round"
NEAR_ROUND_CELLS = 1e-6

_NP = {
    "Byte": "uint8", "Int8": "int8", "UInt16": "uint16", "Int16": "int16",
    "UInt32": "uint32", "Int32": "int32", "UInt64": "uint64", "Int64": "int64",
    "Float32": "float32", "Float64": "float64",
}
_GDAL_TYPE = {v: k for k, v in _NP.items()}

# open options: header reads only, no sidecar listing
_CONFIG = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ",".join(SUFFIXES + (".TIF", ".TIFF")),
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "1",
}


def is_tiff(url):
    """True when url names a GeoTIFF by its suffix."""
    return url.split("?", 1)[0].lower().endswith(SUFFIXES)


def gdal_name(url):
    """The GDAL dataset name for a path or URL."""
    if url.startswith("/vsi"):
        return url
    if url.startswith(("http://", "https://")):
        return "/vsicurl/" + url
    if url.startswith("s3://"):
        return "/vsis3/" + url[len("s3://"):]
    if url.startswith("gs://"):
        return "/vsigs/" + url[len("gs://"):]
    if url.startswith("file://"):
        return url[len("file://"):]
    return url


def _gdal():
    from osgeo import gdal, osr
    gdal.UseExceptions()
    osr.UseExceptions()
    return gdal, osr


def _canon(v):
    return A._canon(v)


# ---------------------------------------------------------------- reading

def read_header(url):
    """The header facts of a GeoTIFF as plain data: size, geotransform, CRS
    WKT, GCP count, dataset and band metadata, block shape, overviews,
    nodata, scale and offset, colour interpretation and tables. This dict
    is what the metadata digest is taken over."""
    gdal, _ = _gdal()
    with gdal.config_options(_CONFIG):
        ds = gdal.OpenEx(gdal_name(url), gdal.OF_RASTER | gdal.OF_READONLY,
                         allowed_drivers=["GTiff", "COG"])
        try:
            h = {
                "driver": ds.GetDriver().ShortName,
                "size": [ds.RasterYSize, ds.RasterXSize],
                "geotransform": list(ds.GetGeoTransform(can_return_null=True) or []) or None,
                "wkt": ds.GetProjectionRef() or None,
                "gcp_count": ds.GetGCPCount(),
                "metadata": {"": dict(ds.GetMetadata() or {}),
                             "IMAGE_STRUCTURE": dict(ds.GetMetadata("IMAGE_STRUCTURE") or {})},
                "rpc": bool(ds.GetMetadata("RPC")),
                "bands": [],
            }
            for i in range(1, ds.RasterCount + 1):
                b = ds.GetRasterBand(i)
                ovr = []
                for k in range(b.GetOverviewCount()):
                    o = b.GetOverview(k)
                    ovr.append({"shape": [o.YSize, o.XSize], "block": list(o.GetBlockSize())[::-1]})
                nd = b.GetNoDataValue()
                ct = b.GetColorTable()
                rat = b.GetDefaultRAT()
                h["bands"].append({
                    "dtype": gdal.GetDataTypeName(b.DataType),
                    "block": list(b.GetBlockSize())[::-1],
                    "nodata": nd,
                    "scale": b.GetScale(),
                    "offset": b.GetOffset(),
                    "unit": b.GetUnitType() or None,
                    "description": b.GetDescription() or None,
                    "colour_interp": gdal.GetColorInterpretationName(b.GetColorInterpretation()),
                    "colour_table": ct.GetCount() if ct is not None else None,
                    "rat": [rat.GetRowCount(), rat.GetColumnCount()] if rat is not None else None,
                    "mask_flags": b.GetMaskFlags(),
                    "metadata": dict(b.GetMetadata() or {}),
                    "overviews": ovr,
                })
            # the nodata tag as written (an ASCII number shared by all bands):
            # GDAL rounds it to the band type on read, other readers parse it
            h["nodata_tag"] = None
            if h["driver"] in ("GTiff", "COG"):
                f = gdal.VSIFOpenL(gdal_name(url), "rb")
                if f is not None:
                    try:
                        h["nodata_tag"] = _tiff_ascii_tag(f, GDAL_NODATA_TAG)
                    except Exception:
                        pass
                    finally:
                        gdal.VSIFCloseL(f)
            h["gdal_version"] = gdal.__version__
            return h
        finally:
            ds = None


def _tiff_ascii_tag(f, tag):
    """The ASCII value of a tag in the first IFD, from header bytes only.
    f: a gdal VSI file handle. Classic TIFF and BigTIFF, either byte order."""
    import struct
    from osgeo import gdal

    def read(off, n):
        gdal.VSIFSeekL(f, off, 0)
        return gdal.VSIFReadL(1, n, f)
    head = read(0, 16)
    if len(head) < 8 or head[:2] not in (b"II", b"MM"):
        return None
    e = "<" if head[:2] == b"II" else ">"
    magic = struct.unpack(e + "H", head[2:4])[0]
    if magic == 42:
        ifd = struct.unpack(e + "I", head[4:8])[0]
        n = struct.unpack(e + "H", read(ifd, 2))[0]
        ents, size, start = read(ifd + 2, n * 12), 12, 0
        fmt_count, fmt_off, inline = "I", "I", 4
    elif magic == 43:
        ifd = struct.unpack(e + "Q", head[8:16])[0]
        n = struct.unpack(e + "Q", read(ifd, 8))[0]
        ents, size, start = read(ifd + 8, n * 20), 20, 0
        fmt_count, fmt_off, inline = "Q", "Q", 8
    else:
        return None
    for k in range(n):
        ent = ents[start + k * size:start + (k + 1) * size]
        t, typ = struct.unpack(e + "HH", ent[:4])
        if t != tag:
            continue
        cw = struct.calcsize(fmt_count)
        count = struct.unpack(e + fmt_count, ent[4:4 + cw])[0]
        if count <= inline:
            raw = ent[4 + cw:4 + cw + count]
        else:
            off = struct.unpack(e + fmt_off, ent[4 + cw:4 + cw + struct.calcsize(fmt_off)])[0]
            raw = read(off, count)
        return raw.split(b"\0", 1)[0].decode("ascii", "replace").strip()
    return None


GDAL_NODATA_TAG = 42113


def header_digest(h):
    """sha256 over the header facts (not the GDAL version), canonical JSON."""
    doc = {k: v for k, v in h.items() if k != "gdal_version"}
    blob = json.dumps(_canon(doc), sort_keys=True, separators=(",", ":")).encode("ascii", "backslashreplace")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------- facts

def _decimals(x):
    """Decimal places in the shortest repr of x (0 for 25.0, 1 for 0.1)."""
    s = repr(float(x))
    if "e" in s or "E" in s:
        m, e = s.lower().split("e")
        d = len(m.split(".")[1].rstrip("0")) if "." in m else 0
        return max(0, d - int(e))
    frac = s.split(".")[1].rstrip("0") if "." in s else ""
    return len(frac)


def near_round(v, cell):
    """The round value v was meant to be, or None.

    Round means: no more decimals than the cell size has (an origin of a 25 m
    grid is a whole number of metres, of a 0.1 degree grid a tenth). v is
    near round when it is not round but lies within NEAR_ROUND_CELLS of a
    cell of that value."""
    d = _decimals(cell)
    r = round(v, d) + 0.0
    if r == v:
        return None
    if abs(r - v) <= NEAR_ROUND_CELLS * abs(cell):
        return r
    return None


def _crs_facts(wkt):
    """Name, authority id and GDAL's best matches for a WKT."""
    _, osr = _gdal()
    s = osr.SpatialReference()
    s.ImportFromWkt(wkt)
    out = {"via": "GeoTIFF keys", "name": s.GetName(),
           "kind": "geographic" if s.IsGeographic() else "projected" if s.IsProjected() else "other"}
    an, ac = s.GetAuthorityName(None), s.GetAuthorityCode(None)
    if an and ac:
        out["id"] = f"{an}:{ac}"
    matches = []
    try:
        for m, conf in (s.FindMatches() or [])[:3]:
            mn, mc = m.GetAuthorityName(None), m.GetAuthorityCode(None)
            if not (mn and mc):
                continue
            same = bool(s.IsSame(m, ["IGNORE_DATA_AXIS_TO_SRS_AXIS_MAPPING=YES", "CRITERION=EQUIVALENT"]))
            matches.append({"id": f"{mn}:{mc}", "name": m.GetName(), "confidence": int(conf),
                            "equivalent": same})
    except RuntimeError:
        pass
    out["matches"] = matches
    return out


def _cost(shape, block, nbands, interleave, overviews):
    """Read cost of a single-band TILE x TILE view, as storecard.card._cost
    reports it for Zarr: blocks are the inner chunks; pixel interleave puts
    every band in each block, so a single-band read pays for all of them."""
    from .card import TILE
    ny, nx = shape
    by, bx = block
    inner = nbands if interleave == "PIXEL" and nbands > 1 else 1

    def read(n, c, w, worst):
        touched = math.ceil(w / c) if not worst else math.ceil((w - 1) / c) + 1
        touched = min(touched, math.ceil(n / c))
        return min(touched * c, n)

    wy, wx = min(TILE, ny), min(TILE, nx)
    amp = {}
    for label, worst in (("aligned", False), ("worst", True)):
        amp[label] = round(inner * read(ny, by, wy, worst) * read(nx, bx, wx, worst) / (wy * wx), 3)
    levels = [{"shape": o["shape"], "chunks": o["block"],
               "spatial_chunks": math.ceil(o["shape"][0] / o["block"][0]) * math.ceil(o["shape"][1] / o["block"][1])}
              for o in overviews]
    return {
        "chunks": [by, bx], "shards": None,
        "nonspatial_read_factor": {"inner": inner, "shard": inner},
        "tile_amplification": amp, "tile": TILE,
        "spatial_chunks": math.ceil(ny / by) * math.ceil(nx / bx),
        "tiled": bx < nx,
        "overviews": levels,
        "coarsest_spatial_chunks": levels[-1]["spatial_chunks"] if levels else math.ceil(ny / by) * math.ceil(nx / bx),
    }


def _band(h, i, asserts, findings):
    """One band as a card variable. asserts: the applied assertion's keys."""
    from .card import _in_dtype, _jsonable, _same
    b = h["bands"][i]
    name = f"band_{i + 1}"
    ny, nx = h["size"]
    dtype = _NP.get(b["dtype"], b["dtype"].lower())

    def find(code, **kw):
        findings.append({"code": code, "array": name, **kw})

    # ---- values
    values = {"dtype": dtype, "colour_interp": b["colour_interp"]}
    for k in ("unit", "description"):
        if b[k]:
            values[k] = b[k]
    if b["scale"] not in (None, 1.0) or b["offset"] not in (None, 0.0):
        values["packing"] = {"scale_factor": b["scale"] if b["scale"] is not None else 1.0,
                             "add_offset": b["offset"] if b["offset"] is not None else 0.0}
    if b["colour_table"] is not None:
        values["colour_table_entries"] = b["colour_table"]
    if b["rat"] is not None:
        values["rat"] = {"rows": b["rat"][0], "columns": b["rat"][1]}
    if b["metadata"].get("LAYER_TYPE"):
        values["layer_type"] = b["metadata"]["LAYER_TYPE"]
    fills = []
    if b["nodata"] is not None:
        nd = b["nodata"]
        raw = h.get("nodata_tag")
        try:
            declared = float(raw) if raw is not None else nd
        except ValueError:
            declared = nd
        fl = {"from": "GDAL nodata", "value": declared, "raw": raw if raw is not None else repr(nd),
              "gdal_value": nd}
        nd = declared
        fl["in_dtype"] = _in_dtype(nd, dtype)
        fl["representable"] = _same(fl["in_dtype"], nd)
        fills.append(fl)
        if not fl["representable"]:
            find("FILL_NOT_REPRESENTABLE", source="GDAL nodata", value=_jsonable(nd),
                 in_dtype=_jsonable(fl["in_dtype"]), dtype=dtype)
    elif not b["mask_flags"] & (0x02 | 0x04) and b["colour_interp"] != "Alpha":
        # no nodata, no per-dataset (internal mask) or alpha mask
        find("FILL_NOT_DECLARED", dtype=dtype)
    values["fill"] = fills
    mf = b["mask_flags"]
    values["mask"] = ("per dataset" if mf & 0x02 else "alpha" if mf & 0x04 else
                      "nodata" if mf & 0x08 else "all valid" if mf & 0x01 else str(mf))

    # ---- grid
    gt = h["geotransform"]
    grid = {"spatial_dims": ["y", "x"], "axis_order": "yx", "axes": {}}
    declared = []
    if "spatial:transform" in asserts:
        t = list(asserts["spatial:transform"])
        grid["transform"] = {"from": "assertion"}
    elif gt and list(gt) != [0.0, 1.0, 0.0, 0.0, 0.0, 1.0]:
        t = [gt[1], gt[2], gt[0], gt[4], gt[5], gt[3]]
        grid["transform"] = {}
    else:
        t = None
    if t is not None:
        declared.append("transform")
        aop = h["metadata"][""].get("AREA_OR_POINT", "Area")
        grid["transform"].update({
            "spatial:transform": t, "spatial:shape": [ny, nx], "spatial:dimensions": ["y", "x"],
            "spatial:registration": "pixel" if aop == "Area" else "node",
            "spatial:transform_type": "affine",
        })
        a, bb, c, d, e, f = t
        if bb == 0.0 and d == 0.0:
            grid["lattice"] = {"x_offset_cells": round((c / a) % 1.0, 9), "y_offset_cells": round((f / e) % 1.0, 9)}
            snapped = {}
            for key, v, cell in (("x_origin", c, a), ("y_origin", f, e)):
                r = near_round(v, cell)
                if r is not None:
                    snapped[key] = {"stored": v, "round": r, "cells": abs(r - v) / abs(cell)}
            if snapped:
                grid["near_round"] = snapped
                find("TRANSFORM_NEAR_ROUND", **snapped)
        if h["metadata"][""].get("AREA_OR_POINT") == "Point":
            find("REGISTRATION_POINT")
    if h["gcp_count"]:
        declared.append("gcps")
        grid["gcp_count"] = h["gcp_count"]
    if h["rpc"]:
        declared.append("rpc")
    if not declared:
        declared.append("none")
    grid["declared"] = declared
    grid["form"] = declared[0]

    # ---- crs
    crs = {"sources": []}
    if "proj:code" in asserts:
        crs["sources"].append({"via": "proj:code", "on": "assertion", "value": asserts["proj:code"]})
    elif "proj:wkt2" in asserts:
        crs["sources"].append({"via": "proj:wkt2", "on": "assertion"})
    elif h["wkt"]:
        cf = _crs_facts(h["wkt"])
        crs["sources"].append(cf)
        if "id" not in cf:
            best = cf["matches"][0] if cf["matches"] else None
            find("CRS_NO_AUTHORITY_ID", name=cf["name"],
                 best_match=best["id"] if best else None,
                 confidence=best["confidence"] if best else None,
                 equivalent=best["equivalent"] if best else None)
    crs["declared"] = bool(crs["sources"])
    if not crs["declared"]:
        find("CRS_NOT_DECLARED")

    if "transform" in declared and crs["declared"]:
        grid["costume"] = "B"
    elif declared == ["none"]:
        grid["costume"] = "A"
    else:
        grid["costume"] = None

    interleave = h["metadata"]["IMAGE_STRUCTURE"].get("INTERLEAVE", "BAND")
    cost = _cost([ny, nx], b["block"], len(h["bands"]), interleave, b["overviews"])
    if not cost["tiled"]:
        find("GEOTIFF_STRIPPED", block=b["block"])

    return {"name": name, "dims": ["y", "x"], "shape": [ny, nx], "values": values,
            "grid": grid, "crs": crs, "cost": cost}


def card_cog(url, probe_hosts=True, assertions=(), header=None):
    """Build a store card for the GeoTIFF or COG at url (path, http(s), s3,
    or a GDAL /vsi name). header: facts from read_header, to skip the read."""
    from .card import CARD_VERSION, _jsonable, _probe_host, _summary
    h = header or read_header(url)
    digest = header_digest(h)
    assertions = [A.load(a) for a in assertions or ()]
    names = [f"band_{i + 1}" for i in range(len(h["bands"]))]

    findings = []
    applied, per_band = [], {}
    for doc in assertions:
        subj = doc["subject"]
        entry = {"kind": doc["kind"], "status": doc["status"], "variable": subj["variable"],
                 "by": doc.get("by", {}), "applied": False}
        if subj["variable"] not in names:
            entry["reason"] = "subject variable not in store"
            findings.append({"code": "ASSERTION_SUBJECT_MISSING", "array": subj["variable"]})
        elif subj["metadata_digest"] != digest:
            entry["reason"] = "store metadata changed since the assertion was made"
            findings.append({"code": "ASSERTION_STALE", "array": subj["variable"],
                             "asserted_digest": subj["metadata_digest"], "digest": digest})
        elif doc["status"] == "withdrawn":
            entry["reason"] = "withdrawn"
        elif doc["kind"] != "grid":
            entry["reason"] = "only grid assertions apply to a GeoTIFF"
        else:
            entry["applied"] = True
            per_band[subj["variable"]] = doc
        applied.append(entry)

    ist = h["metadata"]["IMAGE_STRUCTURE"]
    arrays, variables = [], []
    for i, name in enumerate(names):
        b = h["bands"][i]
        codecs = [{"name": (ist.get("COMPRESSION") or "none").lower()}]
        if ist.get("PREDICTOR"):
            codecs[0]["predictor"] = int(ist["PREDICTOR"])
        arrays.append({"name": name, "kind": "data", "dtype": _NP.get(b["dtype"], b["dtype"].lower()),
                       "shape": h["size"], "dims": ["y", "x"], "chunks": b["block"], "shards": None,
                       "codecs": codecs, "role": None})
        doc = per_band.get(name)
        if doc is None:
            v = _band(h, i, {}, findings)
        else:
            presented = _band(h, i, {}, [])
            v = _band(h, i, doc["asserts"], findings)
            v["grid"]["costume_presented"] = presented["grid"]["costume"]
            v["grid"]["assertion"] = {"kind": doc["kind"], "status": doc["status"], "by": doc.get("by", {})}
        variables.append(v)
    if len(names) > 1 and not any(b["description"] for b in h["bands"]) \
            and not {b["colour_interp"] for b in h["bands"]} <= {"Red", "Green", "Blue", "Alpha"}:
        findings.append({"code": "BANDS_UNNAMED", "arrays": names,
                         "colour_interp": [b["colour_interp"] for b in h["bands"]]})

    hosts = []
    if probe_hosts and url.startswith(("http://", "https://")):
        hp = _probe_host(url, None)
        if hp:
            hosts.append(hp)

    form = COG if ist.get("LAYOUT") == "COG" else GEOTIFF
    return _jsonable({
        "card_version": CARD_VERSION,
        "source": {
            "url": url, "form": form, "driver": h["driver"],
            "interleave": ist.get("INTERLEAVE"), "compression": ist.get("COMPRESSION"),
            "gdal_version": h["gdal_version"],
            "metadata_digest": digest,
            "assertions": applied,
            "scanned_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "arrays": arrays,
        "variables": variables,
        "hosts": hosts,
        "findings": findings,
        "findings_summary": _summary(findings),
    })


# ---------------------------------------------------------------- assertions

def tidy_assertion(card, variable="band_1", *, by=None, min_confidence=0, status="proposed"):
    """A grid assertion that restates a GeoTIFF's own declarations exactly:
    each near-round origin snapped to its round value, and a CRS carried as
    WKT without an authority id named by the EPSG code GDAL matches it to.

    The CRS is named only if GDAL finds the WKT equivalent to the matched
    definition (osr IsSame, criterion EQUIVALENT), whatever its confidence
    score; min_confidence can raise that bar. Raises AssertionError_ when
    there is nothing to tidy or the match is not equivalent."""
    v = next((x for x in card["variables"] if x["name"] == variable), None)
    if v is None:
        raise A.AssertionError_(f"variable {variable!r} not in card")
    tr = (v["grid"].get("transform") or {}).get("spatial:transform")
    if tr is None:
        raise A.AssertionError_(f"{variable} declares no transform")
    t = list(tr)
    nr = v["grid"].get("near_round") or {}
    if "x_origin" in nr:
        t[2] = nr["x_origin"]["round"]
    if "y_origin" in nr:
        t[5] = nr["y_origin"]["round"]
    src = v["crs"]["sources"][0] if v["crs"]["sources"] else None
    if src is None:
        raise A.AssertionError_(f"{variable} declares no CRS")
    evidence = {"method": "GeoTIFF declarations restated: near-round origins snapped to the cell's decimals; "
                          "a CRS without an authority id named by an equivalent EPSG definition"}
    if "id" in src:
        code = src["id"]
        evidence["crs"] = {"declared_id": code}
    else:
        best = next((m for m in src.get("matches", []) if m["equivalent"]), None)
        if best is None or best["confidence"] < min_confidence:
            raise A.AssertionError_(f"{variable}: no equivalent authority match for CRS {src.get('name')!r}")
        code = best["id"]
        evidence["crs"] = {"declared_name": src.get("name"), "matched": code,
                           "gdal_confidence": best["confidence"], "equivalent": True}
    if nr:
        evidence["near_round"] = nr
    if not nr and "id" in src:
        raise A.AssertionError_(f"{variable}: nothing to tidy (round origin, CRS has an id)")
    evidence["gdal_version"] = card["source"].get("gdal_version")
    _, osr = _gdal()
    s = osr.SpatialReference()
    s.SetFromUserInput(code)
    crs_axes = ("y", "x") if (s.EPSGTreatsAsLatLong() or s.EPSGTreatsAsNorthingEasting()) else ("x", "y")
    return A.grid_assertion(card, variable, t, {"proj:code": code}, shape=v["shape"],
                            dimensions=["y", "x"], registration=v["grid"]["transform"]["spatial:registration"],
                            crs_axes=crs_axes, evidence=evidence, by=by or {"name": "storecard.cog.tidy_assertion"},
                            status=status)


def to_vrt(doc, card, source=None):
    """A classic GDAL VRT that presents the GeoTIFF with the asserted
    geotransform and SRS, reading every band from the source unchanged."""
    a = A._grid(doc)
    ny, nx = a["spatial:shape"]
    ta, tb, tc, td, te, tf = a["spatial:transform"]
    source = source or gdal_name(card["source"]["url"])
    root = ET.Element("VRTDataset", rasterXSize=str(nx), rasterYSize=str(ny))
    srs = a.get("proj:code") or a.get("proj:wkt2") or json.dumps(a.get("proj:projjson"))
    mapping = "1,2" if doc["crs_axes"] == ["x", "y"] else "2,1"
    ET.SubElement(root, "SRS", dataAxisToSRSAxisMapping=mapping).text = srs
    ET.SubElement(root, "GeoTransform").text = ", ".join(repr(float(x)) for x in (tc, ta, tb, tf, td, te))
    for i, v in enumerate(card["variables"]):
        b = ET.SubElement(root, "VRTRasterBand", dataType=_GDAL_TYPE.get(v["values"]["dtype"], "Float64"),
                          band=str(i + 1))
        fill = v["values"].get("fill") or []
        if fill:
            ET.SubElement(b, "NoDataValue").text = repr(float(fill[0]["value"]))
        if v["values"].get("description"):
            ET.SubElement(b, "Description").text = v["values"]["description"]
        s = ET.SubElement(b, "SimpleSource")
        ET.SubElement(s, "SourceFilename", relativeToVRT="0").text = source
        ET.SubElement(s, "SourceBand").text = str(i + 1)
    ET.indent(root)
    return ET.tostring(root, encoding="unicode") + "\n"


def lattice_member(tile, mosaic, variable="band_1"):
    """Whether tile's grid is a window of mosaic's: same cell size and CRS,
    and an origin a whole number of cells from mosaic's. Returns the window
    (col, row offsets, in mosaic cells) or None. Uses the asserted
    (tidied) transforms if the cards were built with assertions."""
    vt = next(x for x in tile["variables"] if x["name"] == variable)
    vm = next(x for x in mosaic["variables"] if x["name"] == variable)
    tt = (vt["grid"].get("transform") or {}).get("spatial:transform")
    tm = (vm["grid"].get("transform") or {}).get("spatial:transform")
    if not tt or not tm or tt[0] != tm[0] or tt[4] != tm[4] or tt[1] or tt[3] or tm[1] or tm[3]:
        return None

    def ident(v):
        s = v["crs"]["sources"][0] if v["crs"]["sources"] else {}
        if "value" in s:
            return s["value"]
        if "id" in s:
            return s["id"]
        m = next((m for m in s.get("matches", []) if m["equivalent"]), None)
        return m["id"] if m else None
    if ident(vt) is None or ident(vt) != ident(vm):
        return None
    col = (tt[2] - tm[2]) / tm[0]
    row = (tt[5] - tm[5]) / tm[4]
    if abs(col - round(col)) > NEAR_ROUND_CELLS or abs(row - round(row)) > NEAR_ROUND_CELLS:
        return None
    return {"col": int(round(col)), "row": int(round(row)), "ncol": vt["shape"][1], "nrow": vt["shape"][0],
            "inside": (col >= 0 and row >= 0 and col + vt["shape"][1] <= vm["shape"][1]
                       and row + vt["shape"][0] <= vm["shape"][0])}
