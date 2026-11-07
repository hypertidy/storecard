"""Assertions: separate, evidenced claims about someone else's store.

An assertion supplies what a store lacks or corrects what it gets wrong,
without copying or editing a byte of it. It is keyed to the store's URL and
to a digest of the store's metadata at the time it was made, so it stops
applying (goes stale) when the store changes. See ASSERTIONS.md.

Two kinds in v0:

- "grid": the variable is regular in a stated frame. Asserts a transform,
  a shape, the spatial dimensions and a CRS.
- "refusal": the variable is not regular in any frame tried. Asserts
  nothing about the grid; records what was tried.

Emitters write a grid assertion in the forms readers take: zarr-conventions
attributes, a STAC asset patch (RFC 6902), and a GDAL multidimensional VRT.
"""

import datetime
import hashlib
import json
import math
import xml.etree.ElementTree as ET

ASSERTION_VERSION = "0"
KINDS = ("grid", "refusal")
STATUSES = ("proposed", "settled", "withdrawn")

# keys a grid assertion may set on the variable
GRID_KEYS = ("spatial:transform", "spatial:shape", "spatial:dimensions",
             "spatial:registration", "spatial:transform_type",
             "proj:code", "proj:wkt2", "proj:projjson")

CONV_SPATIAL = {
    "uuid": "689b58e2-cf7b-45e0-9fff-9cfc0883d6b4",
    "schema_url": "https://raw.githubusercontent.com/zarr-conventions/spatial/refs/tags/v1/schema.json",
    "spec_url": "https://github.com/zarr-conventions/spatial/blob/v1/README.md",
    "name": "spatial:", "description": "Spatial coordinate information",
}
CONV_PROJ = {
    "uuid": "f17cb550-5864-4468-aeb7-f3180cfb622f",
    "schema_url": "https://raw.githubusercontent.com/zarr-conventions/proj/refs/tags/v0.1/schema.json",
    "spec_url": "https://github.com/zarr-conventions/proj/blob/v0.1/README.md",
    "name": "proj:", "description": "Coordinate reference system information for geospatial data",
}


class AssertionError_(ValueError):
    """An assertion document that does not follow the v0 schema."""


# ---------------------------------------------------------------- digest

def _canon(v):
    if isinstance(v, dict):
        return {str(k): _canon(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            v = v.item()
        except Exception:
            pass
    if isinstance(v, float) and not math.isfinite(v):
        return "nan" if math.isnan(v) else ("inf" if v > 0 else "-inf")
    if isinstance(v, bytes):
        return v.hex()
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def metadata_digest(arrays, root_attrs):
    """sha256 over the store's metadata as read: every array's metadata
    document (shape, dtype, chunks, codecs, fill value, attributes) and the
    root group's attributes, in canonical JSON. Changes whenever the store's
    metadata changes; never reads data."""
    doc = {"root": _canon(dict(root_attrs)),
           "arrays": {p: _canon(a.metadata.to_dict()) for p, a in sorted(arrays.items())}}
    blob = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("ascii", "backslashreplace")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------- making

def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _subject(card, variable):
    names = [v["name"] for v in card["variables"]]
    if variable not in names:
        raise AssertionError_(f"variable {variable!r} not in card (has {names})")
    return {"url": card["source"]["url"], "variable": variable,
            "metadata_digest": card["source"]["metadata_digest"]}


def grid_assertion(card, variable, transform, crs, *, shape=None, dimensions=None,
                   registration="pixel", crs_axes=("x", "y"), evidence=None, by=None,
                   status="proposed"):
    """A grid assertion for one variable of the store a card describes.

    transform: [a, b, c, d, e, f] in the zarr-conventions / STAC order
               (x = a*col + b*row + c, y = d*col + e*row + f, cell corners)
    crs:       {"proj:code": "EPSG:3412"}, {"proj:wkt2": ...} or {"proj:projjson": ...}
    crs_axes:  the variable's spatial dimensions in the CRS's axis order, by
               role: ("x", "y") for easting/northing, ("y", "x") for lat/lon
    """
    subject = _subject(card, variable)
    v = next(x for x in card["variables"] if x["name"] == variable)
    sd = dimensions or v["grid"]["spatial_dims"]
    if shape is None:
        shape = [v["shape"][v["dims"].index(sd[0])], v["shape"][v["dims"].index(sd[1])]]
    asserts = {"spatial:transform": [float(t) for t in transform],
               "spatial:shape": [int(s) for s in shape],
               "spatial:dimensions": list(sd),
               "spatial:transform_type": "affine",
               "spatial:registration": registration}
    asserts.update(crs)
    doc = {
        "assertion_version": ASSERTION_VERSION,
        "kind": "grid",
        "subject": subject,
        "asserts": asserts,
        "crs_axes": list(crs_axes),
        "evidence": evidence or {},
        "by": by or {},
        "made_at": _now(),
        "status": status,
    }
    validate(doc)
    return doc


def refusal(card, variable, reason, *, frames_tried=(), evidence=None, by=None, status="proposed"):
    """A refusal: the variable's grid is regular in no frame tried."""
    doc = {
        "assertion_version": ASSERTION_VERSION,
        "kind": "refusal",
        "subject": _subject(card, variable),
        "refuses": {"reason": reason, "frames_tried": list(frames_tried)},
        "evidence": evidence or {},
        "by": by or {},
        "made_at": _now(),
        "status": status,
    }
    validate(doc)
    return doc


def validate(doc):
    """Raise AssertionError_ if doc is not a v0 assertion; return doc."""
    def need(cond, msg):
        if not cond:
            raise AssertionError_(msg)
    need(isinstance(doc, dict), "an assertion is a JSON object")
    need(doc.get("assertion_version") == ASSERTION_VERSION, "assertion_version must be '0'")
    need(doc.get("kind") in KINDS, f"kind must be one of {KINDS}")
    need(doc.get("status") in STATUSES, f"status must be one of {STATUSES}")
    s = doc.get("subject") or {}
    for k in ("url", "variable", "metadata_digest"):
        need(isinstance(s.get(k), str) and s[k], f"subject.{k} is required")
    need(isinstance(doc.get("evidence"), dict), "evidence is an object")
    need(isinstance(doc.get("by"), dict), "by is an object")
    if doc["kind"] == "grid":
        a = doc.get("asserts") or {}
        need(set(a) <= set(GRID_KEYS), f"asserts may only hold {GRID_KEYS}")
        t = a.get("spatial:transform")
        need(isinstance(t, list) and len(t) == 6 and all(isinstance(x, (int, float)) for x in t),
             "spatial:transform is six numbers")
        need(isinstance(a.get("spatial:shape"), list) and len(a["spatial:shape"]) == 2,
             "spatial:shape is [ny, nx]")
        need(isinstance(a.get("spatial:dimensions"), list) and len(a["spatial:dimensions"]) == 2,
             "spatial:dimensions is [ydim, xdim]")
        need(any(k in a for k in ("proj:code", "proj:wkt2", "proj:projjson")),
             "a grid assertion states a CRS")
        need(doc.get("crs_axes") in (["x", "y"], ["y", "x"]), "crs_axes is ['x', 'y'] or ['y', 'x']")
    else:
        r = doc.get("refuses") or {}
        need(isinstance(r.get("reason"), str) and r["reason"], "refuses.reason is required")
    return doc


def load(path_or_doc):
    if isinstance(path_or_doc, dict):
        return validate(path_or_doc)
    with open(path_or_doc) as fh:
        return validate(json.load(fh))


# ---------------------------------------------------------------- emitting

def _grid(doc):
    validate(doc)
    if doc["kind"] != "grid":
        raise AssertionError_("only a grid assertion can be emitted")
    return doc["asserts"]


def to_zarr_attrs(doc):
    """Attributes for the variable's array (or its group) in the
    zarr-conventions spatial: and proj: forms, for a virtual store's
    metadata or an overlay. The source store is never written."""
    a = dict(_grid(doc))
    a["zarr_conventions"] = [CONV_SPATIAL, CONV_PROJ]
    return a


def to_stac_patch(doc, asset="data"):
    """RFC 6902 operations that add the asserted grid to a STAC asset,
    with the projection extension (proj:transform has the same order as
    spatial:transform)."""
    a = _grid(doc)
    base = f"/assets/{asset}"
    ops = [{"op": "add", "path": f"{base}/proj:shape", "value": a["spatial:shape"]},
           {"op": "add", "path": f"{base}/proj:transform", "value": a["spatial:transform"]}]
    for k in ("proj:code", "proj:wkt2", "proj:projjson"):
        if k in a:
            ops.append({"op": "add", "path": f"{base}/{k}", "value": a[k]})
    return ops


GDAL_TYPES = {"uint8": "Byte", "int8": "Int8", "uint16": "UInt16", "int16": "Int16",
              "uint32": "UInt32", "int32": "Int32", "uint64": "UInt64", "int64": "Int64",
              "float32": "Float32", "float64": "Float64"}


def to_vrt(doc, card, source=None):
    """A GDAL multidimensional VRT that presents the variable on the asserted
    grid: 1-D regularly spaced x and y indexing variables and the asserted
    SRS, with the data read from the store unchanged.

    source: the GDAL name of the store, default ZARR:"/vsicurl/<url>" for
    http(s) URLs and ZARR:"<path>" otherwise.
    """
    a = _grid(doc)
    var = doc["subject"]["variable"]
    v = next(x for x in card["variables"] if x["name"] == var)
    yd, xd = a["spatial:dimensions"]
    ny, nx = a["spatial:shape"]
    ta, tb, tc, td, te, tf = a["spatial:transform"]
    if tb or td:
        raise AssertionError_("a rotated or sheared transform has no 1-D form for a VRT")
    if source is None:
        url = card["source"]["url"]
        source = f'ZARR:"/vsicurl/{url}"' if url.startswith(("http://", "https://")) else f'ZARR:"{url}"'

    root = ET.Element("VRTDataset")
    grp = ET.SubElement(root, "Group", name="/")
    for d, size in zip(v["dims"], v["shape"]):
        attrs = {"name": d, "size": str(size)}
        if d == xd:
            attrs.update(type="HORIZONTAL_X", indexingVariable=d)
        elif d == yd:
            attrs.update(type="HORIZONTAL_Y", indexingVariable=d)
        ET.SubElement(grp, "Dimension", **attrs)
    for d, start, step, n in ((yd, tf + te / 2, te, ny), (xd, tc + ta / 2, ta, nx)):
        arr = ET.SubElement(grp, "Array", name=d)
        ET.SubElement(arr, "DataType").text = "Float64"
        ET.SubElement(arr, "DimensionRef", ref=d)
        ET.SubElement(arr, "RegularlySpacedValues", start=repr(float(start)), increment=repr(float(step)))
    arr = ET.SubElement(grp, "Array", name=var.rsplit("/", 1)[-1])
    ET.SubElement(arr, "DataType").text = GDAL_TYPES.get(v["values"]["dtype"], "Float64")
    for d in v["dims"]:
        ET.SubElement(arr, "DimensionRef", ref=d)
    # 1-based indices of the array's dimensions for each SRS axis, in SRS axis order
    order = [xd, yd] if doc["crs_axes"] == ["x", "y"] else [yd, xd]
    mapping = ",".join(str(v["dims"].index(d) + 1) for d in order)
    srs = a.get("proj:code") or a.get("proj:wkt2") or json.dumps(a.get("proj:projjson"))
    ET.SubElement(arr, "SRS", dataAxisToSRSAxisMapping=mapping).text = srs
    src = ET.SubElement(arr, "Source")
    ET.SubElement(src, "SourceFilename").text = source
    ET.SubElement(src, "SourceArray").text = "/" + var
    ET.indent(root)
    return ET.tostring(root, encoding="unicode") + "\n"
