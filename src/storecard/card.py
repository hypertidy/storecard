"""Build a store card from a Zarr store's metadata.

A card is a set of facts read from metadata. The only data it reads are
coordinate arrays (1-D axes in full, 2-D coordinates along their edges and
central cross); it never reads a chunk of a data variable.

Entry point: card(url, stac=None) -> dict
"""

import base64
import datetime
import json
import math
import urllib.parse
import urllib.request

import numpy as np
import zarr

from . import assertion as _assertion

CARD_VERSION = "0"

# relative tolerance on step spread for "regular", by storage dtype
TOL = {"float32": 1e-5, "float64": 1e-7}
TOL_DEFAULT = 1e-5
# 1-D coordinate vectors up to this length are carried whole in coord_sample
SAMPLE_1D_MAX = 4096
# 2-D sample lines are decimated to at most this many points
SAMPLE_2D_POINTS = 257
# tile edge, in cells, for the tile amplification figure
TILE = 256

LON_UNITS = {"degrees_east", "degree_east", "degrees_e", "degree_e", "degreese", "degreee"}
LAT_UNITS = {"degrees_north", "degree_north", "degrees_n", "degree_n", "degreesn", "degreen"}
X_ROLES = {"lon", "x", "rlon"}
Y_ROLES = {"lat", "y", "rlat"}
CF_PACK = ("scale_factor", "add_offset")
CF_VALUES = ("units", "valid_range", "valid_min", "valid_max",
             "flag_values", "flag_masks", "flag_meanings")


# ---------------------------------------------------------------- helpers

def _jsonable(v):
    """Make numpy scalars, arrays and non-finite floats JSON-safe."""
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, np.ndarray):
        return _jsonable(v.tolist())
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return "nan" if math.isnan(v) else ("inf" if v > 0 else "-inf")
    if isinstance(v, bytes):
        return base64.b64encode(v).decode("ascii")
    return v


def _num(v, dtype=None):
    """A fill-like value as a float, or None. Accepts 'nan' strings and
    base64-encoded scalars (as xarray writes NaN attributes to Zarr v3)."""
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return None
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("nan", "+nan", "-nan"):
            return float("nan")
        if s in ("inf", "+inf", "infinity"):
            return float("inf")
        if s in ("-inf", "-infinity"):
            return float("-inf")
        try:
            return float(s)
        except ValueError:
            pass
        try:
            raw = base64.b64decode(v, validate=True)
        except Exception:
            return None
        # the encoded width need not match the array's: xarray writes a
        # float32 array's fill as a base64 float64
        kinds = [np.dtype(dtype)] if dtype is not None else []
        kinds += [np.dtype("<f8"), np.dtype("<f4")]
        for dt in kinds:
            if len(raw) == dt.itemsize:
                return float(np.frombuffer(raw, dtype=dt.newbyteorder("<"))[0])
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _plain_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def _same(a, b):
    if a is None or b is None:
        return False
    if math.isnan(a) and math.isnan(b):
        return True
    return a == b


def _in_dtype(v, dtype):
    """v cast to dtype and back to float, or None if it cannot be cast."""
    if v is None:
        return None
    dt = np.dtype(dtype)
    try:
        if dt.kind in "iu":
            if math.isnan(v) or math.isinf(v):
                return None
            info = np.iinfo(dt)
            if v < info.min or v > info.max:
                return None
        with np.errstate(all="ignore"):
            return float(np.array(v).astype(dt))
    except (TypeError, ValueError, OverflowError):
        return None


def role(name, attrs):
    """Coordinate role from CF attributes, then from the name."""
    sn = str(attrs.get("standard_name", "")).lower()
    units = str(attrs.get("units", "")).strip().lower()
    axis = str(attrs.get("axis", attrs.get("cartesian_axis", ""))).upper()
    lname = name.rsplit("/", 1)[-1].lower()
    if sn == "longitude" or units in LON_UNITS:
        return "lon"
    if sn == "latitude" or units in LAT_UNITS:
        return "lat"
    if sn == "grid_longitude":
        return "rlon"
    if sn == "grid_latitude":
        return "rlat"
    if sn == "projection_x_coordinate":
        return "x"
    if sn == "projection_y_coordinate":
        return "y"
    if sn == "time" or " since " in units or axis == "T":
        return "time"
    if axis == "X":
        return "x"
    if axis == "Y":
        return "y"
    if axis == "Z" or sn in ("depth", "height", "altitude", "air_pressure"):
        return "z"
    if lname in ("lon", "longitude", "nav_lon", "xlon", "glamt"):
        return "lon"
    if lname in ("lat", "latitude", "nav_lat", "xlat", "gphit"):
        return "lat"
    if lname in ("rlon",):
        return "rlon"
    if lname in ("rlat",):
        return "rlat"
    if lname in ("x", "xc") and units in ("m", "km", "metre", "meter", "metres", "meters"):
        return "x"
    if lname in ("y", "yc") and units in ("m", "km", "metre", "meter", "metres", "meters"):
        return "y"
    return "other"


def spacing(v, dtype):
    """Spacing facts for a 1-D coordinate vector."""
    v = np.asarray(v, dtype="float64")
    out = {"n": int(v.size)}
    if v.size == 0:
        out["spacing"] = "empty"
        return out
    out["first"] = float(v[0])
    out["last"] = float(v[-1])
    out["min"] = float(np.nanmin(v)) if np.isfinite(v).any() else None
    out["max"] = float(np.nanmax(v)) if np.isfinite(v).any() else None
    if not np.isfinite(v).all():
        out["spacing"] = "nonfinite"
        return out
    if v.size < 2:
        out["spacing"] = "single"
        return out
    d = np.diff(v)
    step = float(np.median(d))
    out["step_median"] = step
    out["step_min"] = float(d.min())
    out["step_max"] = float(d.max())
    tol = TOL.get(str(dtype), TOL_DEFAULT)
    out["tolerance"] = tol
    if not ((d > 0).all() or (d < 0).all()):
        out["spacing"] = "nonmonotonic"
        return out
    dev = float(np.ptp(d) / abs(step)) if step else float("inf")
    out["max_rel_dev"] = dev
    out["spacing"] = "regular" if dev <= tol else "irregular"
    out["direction"] = "ascending" if step > 0 else "descending"
    return out


def mercator_regular(lat, tol=1e-4):
    """True if latitude values are evenly spaced in spherical Mercator y."""
    lat = np.asarray(lat, dtype="float64")
    if lat.size < 3 or not np.isfinite(lat).all() or np.abs(lat).max() >= 89.9:
        return False, None
    y = np.log(np.tan(np.pi / 4 + np.deg2rad(lat) / 2))
    d = np.diff(y)
    if not ((d > 0).all() or (d < 0).all()):
        return False, None
    dev = float(np.ptp(d) / abs(np.median(d)))
    return dev <= tol, dev


def _decimate(n, k=SAMPLE_2D_POINTS):
    if n <= k:
        return np.arange(n)
    return np.unique(np.round(np.linspace(0, n - 1, k)).astype(int))


# ---------------------------------------------------------------- store access

def _open(url, storage_options=None):
    kw = {"mode": "r"}
    if "://" in url and not url.startswith("file://"):
        so = dict(storage_options or {})
        if url.startswith(("http://", "https://")):
            # honour HTTPS_PROXY and friends, as urllib does for the host probe
            so.setdefault("client_kwargs", {}).setdefault("trust_env", True)
        kw["storage_options"] = so
    return zarr.open_group(url, **kw)


def _members(group, hints=(), levels=()):
    """All arrays below group as {path: array}, and whether the group listed.

    Listing first. A store over plain HTTP without consolidated metadata
    cannot list, so then arrays are found as a reader without a listing finds
    them: from hints (STAC cube:variables), under each multiscale level, and
    by following the names each found array gives (its dimensions,
    `coordinates`, `grid_mapping`, `bounds`)."""
    out = {}
    try:
        for path, node in group.members(max_depth=None):
            if isinstance(node, zarr.Array):
                out[path] = node
    except Exception:
        out = {}
    if out:
        return out, True
    queue = list(hints) + [f"{lv}/{h}" for lv in levels or () for h in hints]
    tried = set()
    while queue:
        name = queue.pop(0)
        if name in tried:
            continue
        tried.add(name)
        try:
            node = group[name]
        except Exception:
            continue
        if not isinstance(node, zarr.Array):
            continue
        out[name] = node
        attrs = dict(node.attrs)
        names = [d for d in _dims(node) if d]
        names += str(attrs.get("coordinates", "")).split()
        gm = attrs.get("grid_mapping")
        if isinstance(gm, str):
            names += [t[:-1] for t in gm.split() if t.endswith(":")] if ":" in gm else gm.split()
        for k in ("bounds", "ancillary_variables"):
            if isinstance(attrs.get(k), str):
                names += attrs[k].split()
        queue += [_sibling(name, n) for n in names]
    return out, False


def _dims(arr):
    md = arr.metadata
    names = getattr(md, "dimension_names", None)
    if names:
        return [str(n) if n is not None else None for n in names]
    names = arr.attrs.get("_ARRAY_DIMENSIONS")
    if names:
        return [str(n) for n in names]
    return [None] * arr.ndim


def _codecs(arr):
    d = arr.metadata.to_dict()
    if d.get("zarr_format") == 3:
        out = []
        for c in d.get("codecs", []):
            out.append(c.get("name"))
            if c.get("name") == "sharding_indexed":
                inner = c.get("configuration", {}).get("codecs", [])
                out.extend("inner:" + str(i.get("name")) for i in inner)
        return out
    out = [f.get("id") for f in (d.get("filters") or [])]
    comp = d.get("compressor")
    if comp:
        out.append(comp.get("id"))
    return out


def _attrs(arr):
    return {k: v for k, v in dict(arr.attrs).items() if k != "_ARRAY_DIMENSIONS"}


def _parent(path):
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _sibling(path, name):
    p = _parent(path)
    return f"{p}/{name}" if p else name


# ---------------------------------------------------------------- hosts

def _probe_host(url, zarr_format):
    """CORS and range behaviour of the host serving the store's metadata."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    meta = "zarr.json" if zarr_format == 3 else ".zgroup"
    target = url.rstrip("/") + "/" + meta
    req = urllib.request.Request(target, headers={
        "Origin": "https://storecard.invalid", "Range": "bytes=0-0"})
    out = {"host": parts.netloc, "protocol": parts.scheme, "probed": target}
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            h = r.headers
            out["status"] = r.status
            out["cors"] = h.get("Access-Control-Allow-Origin")
            out["range"] = r.status == 206 or h.get("Accept-Ranges", "").lower() == "bytes"
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


# ---------------------------------------------------------------- card

def _load_stac(stac):
    if stac is None:
        return None
    if isinstance(stac, dict):
        return stac
    if "://" in stac:
        with urllib.request.urlopen(stac, timeout=20) as r:
            return json.load(r)
    with open(stac) as fh:
        return json.load(fh)


def _stac_asset(stac):
    """The data asset of a STAC collection or item, or the dict if it is one."""
    if stac is None:
        return None
    if "href" in stac:
        return stac
    assets = stac.get("assets", {})
    for a in assets.values():
        if "data" in a.get("roles", []):
            return a
    return next(iter(assets.values()), None)


def card(url, stac=None, storage_options=None, probe_hosts=True, assertions=()):
    """Build a store card for the Zarr store at url (a path or a URL).

    stac: optional STAC collection, item or asset (dict, path or URL) whose
          proj:code, bands nodata and cube:variables are recorded as sources.
    assertions: assertion documents (dicts or paths) to apply as an overlay.
          One applies only if its metadata digest matches the store as read;
          the card then describes the variable as asserted, and keeps the
          presented costume beside it. The store is never written.
    """
    assertions = [_assertion.load(a) for a in assertions or ()]
    stac = _load_stac(stac)
    asset = _stac_asset(stac)
    hints = list((asset or {}).get("cube:variables", {}).keys())

    root = _open(url, storage_options)
    zf = root.metadata.zarr_format
    consolidated = getattr(root.metadata, "consolidated_metadata", None) is not None
    ms = _multiscales(dict(root.attrs))
    arrays, listable = _members(root, hints, ms["levels"] if ms else ())

    findings = []
    if not listable:
        findings.append({"code": "GROUP_NOT_LISTABLE",
                         "detail": "arrays found only from hints; the store has no consolidated metadata and its host does not list"})

    root_attrs = dict(root.attrs)
    group_attrs = {"": root_attrs}

    def gattrs(path):
        p = _parent(path)
        if p not in group_attrs:
            try:
                group_attrs[p] = dict(root[p].attrs)
            except Exception:
                group_attrs[p] = {}
        return group_attrs[p]

    # first pass: every array, its dims and its role
    info = {}
    for path, arr in sorted(arrays.items()):
        attrs = _attrs(arr)
        info[path] = {
            "arr": arr, "attrs": attrs, "dims": _dims(arr), "role": role(path, attrs),
        }

    digest = _assertion.metadata_digest(arrays, root.attrs)
    applied = []
    for doc in assertions:
        subj = doc["subject"]
        entry = {"kind": doc["kind"], "status": doc["status"], "variable": subj["variable"],
                 "by": doc.get("by", {}), "applied": False}
        if subj["variable"] not in info:
            entry["reason"] = "subject variable not in store"
            findings.append({"code": "ASSERTION_SUBJECT_MISSING", "array": subj["variable"]})
        elif subj["metadata_digest"] != digest:
            entry["reason"] = "store metadata changed since the assertion was made"
            findings.append({"code": "ASSERTION_STALE", "array": subj["variable"],
                             "asserted_digest": subj["metadata_digest"], "digest": digest})
        elif doc["status"] == "withdrawn":
            entry["reason"] = "withdrawn"
        else:
            entry["applied"] = True
            info[subj["variable"]]["assertion"] = doc
        applied.append(entry)

    # coordinates named by data arrays, grid mappings, bounds
    named_coords, grid_mappings, bounds = set(), set(), set()
    for path, i in info.items():
        a = i["attrs"]
        for n in str(a.get("coordinates", "")).split():
            named_coords.add(_sibling(path, n))
        gm = a.get("grid_mapping")
        if isinstance(gm, str) and gm:
            # CF also allows the "crs: x y" form; the names before ":" are the mappings
            toks = [t[:-1] for t in gm.split() if t.endswith(":")] if ":" in gm else gm.split()
            for tok in toks:
                if _sibling(path, tok) in info:
                    grid_mappings.add(_sibling(path, tok))
        if isinstance(a.get("bounds"), str):
            bounds.add(_sibling(path, a["bounds"]))
    for path, i in info.items():
        a = i["attrs"]
        if "grid_mapping_name" in a or ("crs_wkt" in a and i["arr"].ndim == 0):
            grid_mappings.add(path)

    def is_dim_coord(path, i):
        name = path.rsplit("/", 1)[-1]
        return i["arr"].ndim == 1 and i["dims"][0] == name

    def is_coord(path, i):
        if path in grid_mappings or path in bounds or path in named_coords:
            return True
        if is_dim_coord(path, i):
            return True
        if i["arr"].ndim <= 2 and i["role"] in ("lon", "lat") and i["arr"].ndim >= 1:
            return True
        return False

    card_arrays = []
    for path, i in info.items():
        arr = i["arr"]
        kind = ("grid_mapping" if path in grid_mappings else
                "bounds" if path in bounds else
                "coordinate" if is_coord(path, i) else "data")
        i["kind"] = kind
        card_arrays.append({
            "name": path, "kind": kind, "dtype": str(arr.dtype),
            "shape": list(arr.shape), "dims": i["dims"],
            "chunks": list(arr.chunks), "shards": list(arr.shards) if arr.shards else None,
            "codecs": _codecs(arr), "role": i["role"] if kind != "data" else None,
        })

    # 1-D coordinate values, read once each (coordinate arrays are the only data read)
    axis_cache = {}

    def axis(path):
        if path not in axis_cache:
            i = info[path]
            v = np.asarray(i["arr"][...])
            axis_cache[path] = (v, spacing(v, i["arr"].dtype))
        return axis_cache[path]

    variables = []
    for path, i in info.items():
        if i["kind"] != "data" or i["arr"].ndim < 2:
            continue
        doc = i.get("assertion")
        if doc is None:
            v, f = _variable(path, i, info, axis, gattrs, root_attrs, asset, hints)
        else:
            presented, _ = _variable(path, i, info, axis, gattrs, root_attrs, asset, hints)
            overlay = dict(i, attrs={**i["attrs"], **doc.get("asserts", {})},
                           asserted=set(doc.get("asserts", {})))
            v, f = _variable(path, overlay, info, axis, gattrs, root_attrs, asset, hints)
            g = v["grid"]
            g["costume_presented"] = presented["grid"]["costume"]
            g["assertion"] = {"kind": doc["kind"], "status": doc["status"], "by": doc.get("by", {})}
            if doc["kind"] == "refusal":
                g["costume"] = "H"
                g["assertion"]["refuses"] = doc["refuses"]
        variables.append(v)
        findings.extend(f)

    hosts = []
    if probe_hosts:
        h = _probe_host(url, zf)
        if h:
            hosts.append(h)

    form = f"zarr v{zf}"
    return _jsonable({
        "card_version": CARD_VERSION,
        "source": {
            "url": url, "form": form, "zarr_format": zf, "consolidated": consolidated,
            "listable": listable, "multiscales": _multiscales(root_attrs),
            "metadata_digest": digest,
            "assertions": applied,
            "scanned_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "arrays": card_arrays,
        "variables": variables,
        "hosts": hosts,
        "findings": findings,
        "findings_summary": _summary(findings),
    })


def _summary(findings):
    """Findings grouped by code: {code: [arrays]}, in first-seen order."""
    out = {}
    for f in findings:
        arrs = out.setdefault(f["code"], [])
        a = f.get("array")
        if a is not None and a not in arrs:
            arrs.append(a)
    return out


def _multiscales(attrs):
    ms = attrs.get("multiscales")
    if isinstance(ms, dict) and "layout" in ms:
        return {"convention": "zarr-conventions", "levels": [l.get("asset") for l in ms["layout"]]}
    if isinstance(ms, list) and ms:
        ds = ms[0].get("datasets", [])
        return {"convention": "ngff", "levels": [d.get("path") for d in ds]}
    return None


def _variable(path, i, info, axis, gattrs, root_attrs, asset, hints):
    arr, attrs, dims = i["arr"], i["attrs"], i["dims"]
    findings = []

    def find(code, **kw):
        findings.append({"code": code, "array": path, **kw})

    # ---- values
    dtype = str(arr.dtype)
    values = {"dtype": dtype}
    for k in CF_VALUES:
        if k in attrs:
            values[k] = attrs[k]
    packed = {k: attrs[k] for k in CF_PACK if k in attrs}
    if packed:
        values["packing"] = packed
        sf = packed.get("scale_factor", packed.get("add_offset"))
        values["unpacked_dtype"] = "float64" if isinstance(sf, float) else str(np.asarray(sf).dtype)
    fills = []
    zfv = arr.metadata.fill_value
    fills.append({"from": "zarr fill_value", "value": _num(zfv), "raw": zfv})
    for k in ("_FillValue", "missing_value"):
        if k in attrs:
            raw = attrs[k]
            vals = raw if isinstance(raw, (list, tuple)) else [raw]
            for r in vals:
                fl = {"from": "CF " + k, "value": _num(r, dtype), "raw": r}
                if isinstance(r, str) and fl["value"] is not None and not _plain_number(r):
                    fl["encoding"] = "base64"
                fills.append(fl)
    band_nodata = None
    if asset:
        for b in asset.get("bands", []) or []:
            if b.get("name") in (path, path.rsplit("/", 1)[-1]) or len(asset.get("bands", [])) == 1:
                if "nodata" in b:
                    band_nodata = b["nodata"]
        if band_nodata is not None:
            fills.append({"from": "STAC nodata", "value": _num(band_nodata, dtype), "raw": band_nodata})
    for fl in fills:
        fl["in_dtype"] = _in_dtype(fl["value"], dtype)
        if fl["from"] != "zarr fill_value" and fl["value"] is not None:
            fl["representable"] = _same(fl["in_dtype"], fl["value"])
    declared = [fl for fl in fills if fl["from"] != "zarr fill_value"]
    values["fill"] = fills
    if declared:
        stored = [fl["in_dtype"] for fl in fills]
        agree = all(_same(stored[0], s) for s in stored[1:])
        values["fill_agree"] = agree
        if not agree:
            find("FILL_DISAGREE", values={fl["from"]: _jsonable(fl["value"]) for fl in fills})
        for fl in declared:
            if fl.get("representable") is False:
                find("FILL_NOT_REPRESENTABLE", source=fl["from"], value=_jsonable(fl["value"]),
                     in_dtype=_jsonable(fl["in_dtype"]), dtype=dtype)

    # ---- coordinates around this array
    named = [n for n in str(attrs.get("coordinates", "")).split()]
    named_paths = [_sibling(path, n) for n in named]
    missing = [n for n, p in zip(named, named_paths) if p not in info]
    if missing:
        find("COORDS_NAMED_MISSING", missing=missing)
    two_d = [p for p in named_paths if p in info and info[p]["arr"].ndim == 2]
    if not two_d:
        # 2-D lon/lat on this array's dims, even if not named
        for p, j in info.items():
            if (j["arr"].ndim == 2 and j["role"] in ("lon", "lat")
                    and _parent(p) == _parent(path) and j["dims"] == [d for d in dims if d in j["dims"]]
                    and set(j["dims"]) <= set(dims)):
                two_d.append(p)
    lon2 = next((p for p in two_d if info[p]["role"] == "lon"), None)
    lat2 = next((p for p in two_d if info[p]["role"] == "lat"), None)

    dim_coord = {}
    for d in dims:
        if d is None:
            continue
        p = _sibling(path, d)
        if p in info and info[p]["arr"].ndim == 1 and info[p]["kind"] != "data":
            dim_coord[d] = p

    # spatial dims: from 1-D axis roles, else from 2-D coords, else the last two
    xd = next((d for d in dims if d in dim_coord and info[dim_coord[d]]["role"] in X_ROLES), None)
    yd = next((d for d in dims if d in dim_coord and info[dim_coord[d]]["role"] in Y_ROLES), None)
    if (xd is None or yd is None) and lon2:
        cd = info[lon2]["dims"]
        yd, xd = cd[0], cd[1]
    if xd is None or yd is None:
        yd, xd = dims[-2], dims[-1]
    spatial = [yd, xd]
    if dims.index(xd) < dims.index(yd):
        find("AXES_X_BEFORE_Y", dims=dims)

    # ---- grid
    grid = {"spatial_dims": spatial, "axis_order": "yx" if dims.index(yd) < dims.index(xd) else "xy"}
    declared_forms = []
    ga = gattrs(path)
    tr_src = attrs if "spatial:transform" in attrs else ga if "spatial:transform" in ga else None
    if tr_src is not None:
        declared_forms.append("transform")
        grid["transform"] = {"from": "assertion"} if "spatial:transform" in i.get("asserted", ()) else {}
        grid["transform"].update({k: tr_src.get(k) for k in (
            "spatial:transform", "spatial:shape", "spatial:dimensions",
            "spatial:registration", "spatial:transform_type", "spatial:bbox") if k in tr_src})
        shp = tr_src.get("spatial:shape")
        if shp and list(shp) != [arr.shape[dims.index(yd)], arr.shape[dims.index(xd)]]:
            find("TRANSFORM_SHAPE_MISMATCH", transform_shape=shp)
    if lon2 and lat2:
        declared_forms.append("coords_2d")
    axes = {}
    for d, kind in ((xd, "x"), (yd, "y")):
        if d in dim_coord:
            p = dim_coord[d]
            vals, sp = axis(p)
            a = {"name": p, "role": info[p]["role"], "units": info[p]["attrs"].get("units"), **sp}
            if sp["n"] <= SAMPLE_1D_MAX:
                a["values"] = vals
            else:
                a["head"], a["tail"] = vals[:3], vals[-3:]
            if "bounds" in info[p]["attrs"]:
                a["bounds"] = info[p]["attrs"]["bounds"]
            axes[kind] = a
    if "x" in axes and "y" in axes:
        regular = axes["x"]["spacing"] == "regular" and axes["y"]["spacing"] == "regular"
        declared_forms.append("coords_1d_regular" if regular else "coords_1d_irregular")
    if missing and not declared_forms:
        declared_forms.append("coords_named_missing")
    if not declared_forms:
        declared_forms.append("none")
    grid["declared"] = declared_forms
    grid["form"] = declared_forms[0]
    grid["axes"] = axes

    for kind, a in axes.items():
        if a["spacing"] == "nonmonotonic":
            find("COORD_NONMONOTONIC", coord=a["name"])
        elif a["spacing"] == "nonfinite":
            find("COORD_NONFINITE", coord=a["name"])
        elif a["spacing"] == "irregular":
            if a["role"] == "lat":
                ok, dev = mercator_regular(axis(a["name"])[0])
                a["mercator_rel_dev"] = dev
                if ok:
                    find("LAT_MERCATOR_SPACED", coord=a["name"])
                else:
                    find("COORD_IRREGULAR", coord=a["name"])
            else:
                find("COORD_IRREGULAR", coord=a["name"])
        if kind == "y" and a.get("direction") == "ascending":
            find("Y_ASCENDING", coord=a["name"])
        if a["role"] == "lon" and a.get("max") is not None:
            if a["max"] > 180 and a["min"] >= 0:
                find("LON_0_360", coord=a["name"])
            elif a["max"] > 180:
                step = abs(a.get("step_median") or 0.0)
                find("LON_OVERSHOOT_180", coord=a["name"], max=a["max"],
                     overshoot_cells=round((a["max"] - 180) / step, 4) if step else None)
            if a["min"] < -180:
                find("LON_BELOW_MINUS_180", coord=a["name"])

    # ---- coord sample for 2-D coordinates: edges and the central cross
    if lon2 and lat2:
        cs = _sample_2d(info[lon2]["arr"], info[lat2]["arr"])
        cs["lon"], cs["lat"] = lon2, lat2
        grid["coord_sample"] = cs
        one_d_roles = {axes[k]["role"] for k in axes}
        if not axes and "transform" not in declared_forms:
            find("GRID_2D_LONLAT_ONLY", coords=[lon2, lat2])
        elif one_d_roles & {"x", "y", "rlon", "rlat"}:
            find("GRID_2D_WITH_PROJECTED_1D", coords=[lon2, lat2])
        elif one_d_roles & {"lon", "lat"}:
            dev = _nominal_deviation(cs, axes)
            grid["nominal_deviation"] = dev
            if dev is not None and dev["max_cells"] > 0.5:
                find("NOMINAL_AXES_DISAGREE", coords=[lon2, lat2], max_cells=dev["max_cells"])

    # ---- crs
    crs = {"sources": []}
    gm = attrs.get("grid_mapping")
    if isinstance(gm, str) and gm:
        gm_name = gm.split(":")[0].split()[0].strip()
        gp = _sibling(path, gm_name)
        if gp in info:
            ga2 = info[gp]["attrs"]
            crs["sources"].append({
                "via": "cf grid_mapping", "var": gp,
                "grid_mapping_name": ga2.get("grid_mapping_name"),
                "crs_wkt": "crs_wkt" in ga2, "spatial_ref": "spatial_ref" in ga2,
                "proj4": next((k for k in ("proj4", "proj4_params", "proj4text") if k in ga2), None),
            })
        else:
            find("GRID_MAPPING_NAMED_MISSING", grid_mapping=gm)
    for src_name, a in (("array", attrs), ("group", ga), ("root", root_attrs)):
        for k in ("proj:code", "proj:wkt2", "proj:projjson"):
            if a.get(k) is not None:
                entry = {"via": k, "on": src_name}
                if src_name == "array" and k in i.get("asserted", ()):
                    entry["on"] = "assertion"
                if k == "proj:code":
                    entry["value"] = a[k]
                elif k == "proj:projjson":
                    pid = a[k].get("id") if isinstance(a[k], dict) else None
                    entry["name"] = a[k].get("name") if isinstance(a[k], dict) else None
                    if pid:
                        entry["id"] = f"{pid.get('authority')}:{pid.get('code')}"
                crs["sources"].append(entry)
        if src_name == "group" and ga is root_attrs:
            break
    # "declared" means declared in the store; a STAC proj:code is recorded beside it
    crs["declared"] = bool(crs["sources"])
    if asset and asset.get("proj:code"):
        crs["sources"].append({"via": "STAC proj:code", "value": asset["proj:code"]})
    if not crs["declared"]:
        find("CRS_NOT_DECLARED")
        if {a["role"] for a in axes.values()} & {"x", "y"}:
            find("PROJECTED_NO_GRID_MAPPING")

    grid["costume"] = _costume(grid, axes, info, lon2, lat2, crs, findings)

    # ---- cost
    cost = _cost(arr, dims, spatial)

    v = {"name": path, "dims": dims, "shape": list(arr.shape), "values": values,
         "grid": grid, "crs": crs, "cost": cost}
    return v, findings


ANGULAR_UNITS = {"rad", "radian", "radians"}


def _costume(grid, axes, info, lon2, lat2, crs, findings):
    """The costume (regular-in-what, chapter 3) the store presents, from
    metadata alone. A list when metadata cannot decide: 2-D lon/lat only is
    E (regular in some frame) or H (regular in none) until a fit says which."""
    codes = {f["code"] for f in findings}
    forms = grid["declared"]
    roles = {k: a["role"] for k, a in axes.items()}
    gm = next((s for s in crs["sources"] if s["via"] == "cf grid_mapping"), None)
    if "transform" in forms and crs["declared"]:
        return "B"
    if lon2 and lat2:
        if set(roles.values()) & {"rlon", "rlat"} or (gm and gm.get("grid_mapping_name") == "rotated_latitude_longitude"):
            return "E2"
        if not set(roles.values()) & {"x", "y"}:
            return ["E", "H"]
    two_d_projected = [p for p, j in info.items()
                       if j["arr"].ndim == 2 and j["role"] in ("x", "y") and j["kind"] != "data"]
    if two_d_projected and not axes:
        return "F"
    if "x" in axes and "y" in axes:
        units = {str(a.get("units", "")).lower() for a in axes.values()}
        regular = all(a["spacing"] == "regular" for a in axes.values())
        if regular and units <= ANGULAR_UNITS and not crs["declared"]:
            return "E3"
        if regular:
            return "C"
        if "LAT_MERCATOR_SPACED" in codes and axes["x"]["spacing"] == "regular":
            return "D"
        return "G"
    if forms == ["none"] or forms == ["coords_named_missing"]:
        return "A"
    return None


def _sample_2d(lon, lat):
    ny, nx = lon.shape
    rows, cols = sorted({0, ny // 2, ny - 1}), sorted({0, nx // 2, nx - 1})
    ix, iy = _decimate(nx), _decimate(ny)
    out = {"shape": [ny, nx], "rows": [], "cols": []}
    for r in rows:
        out["rows"].append({"index": r, "at": ix,
                            "lon": np.asarray(lon[r, :])[ix], "lat": np.asarray(lat[r, :])[ix]})
    for c in cols:
        out["cols"].append({"index": c, "at": iy,
                            "lon": np.asarray(lon[:, c])[iy], "lat": np.asarray(lat[:, c])[iy]})
    return out


def _nominal_deviation(cs, axes):
    """Largest distance, in cells, between 2-D positions and the 1-D axes'
    outer product, over the sample lines."""
    if "x" not in axes or "y" not in axes or "values" not in axes["x"] or "values" not in axes["y"]:
        return None
    x = np.asarray(axes["x"]["values"], dtype="float64")
    y = np.asarray(axes["y"]["values"], dtype="float64")
    sx = abs(axes["x"].get("step_median") or 1.0)
    sy = abs(axes["y"].get("step_median") or 1.0)
    worst = 0.0
    for line in cs["rows"]:
        at = np.asarray(line["at"])
        dlon = (np.asarray(line["lon"], dtype="float64") - x[at] + 180) % 360 - 180
        dlat = np.asarray(line["lat"], dtype="float64") - y[line["index"]]
        worst = max(worst, float(np.nanmax(np.abs(dlon)) / sx), float(np.nanmax(np.abs(dlat)) / sy))
    for line in cs["cols"]:
        at = np.asarray(line["at"])
        dlon = (np.asarray(line["lon"], dtype="float64") - x[line["index"]] + 180) % 360 - 180
        dlat = np.asarray(line["lat"], dtype="float64") - y[at]
        worst = max(worst, float(np.nanmax(np.abs(dlon)) / sx), float(np.nanmax(np.abs(dlat)) / sy))
    return {"max_cells": worst}


def _cost(arr, dims, spatial):
    """Read cost of a single-index 2-D view.

    Facts for rule packs to threshold, not a verdict: the non-spatial factor
    is given for the inner chunk (what a range reader fetches) and for the
    shard (what a whole-object reader fetches); tile amplification for a
    TILE x TILE window aligned at the origin and for one placed across chunk
    corners, both over inner chunks."""
    shape, chunks = arr.shape, arr.chunks
    shards = arr.shards
    yi, xi = dims.index(spatial[0]), dims.index(spatial[1])

    def nonspatial(unit):
        f = 1
        for k, c in enumerate(unit):
            if k not in (yi, xi):
                f *= int(min(c, shape[k]))
        return f

    def read(n, c, w, worst):
        touched = math.ceil(w / c) if not worst else math.ceil((w - 1) / c) + 1
        touched = min(touched, math.ceil(n / c))
        return min(touched * c, n)

    inner = nonspatial(chunks)
    wy, wx = min(TILE, shape[yi]), min(TILE, shape[xi])
    amp = {}
    for label, worst in (("aligned", False), ("worst", True)):
        ry = read(shape[yi], chunks[yi], wy, worst)
        rx = read(shape[xi], chunks[xi], wx, worst)
        amp[label] = round(inner * (ry * rx) / (wy * wx), 3)
    spatial_chunks = math.ceil(shape[yi] / chunks[yi]) * math.ceil(shape[xi] / chunks[xi])
    return {
        "chunks": list(chunks), "shards": list(shards) if shards else None,
        "nonspatial_read_factor": {"inner": inner, "shard": nonspatial(shards) if shards else inner},
        "tile_amplification": amp,
        "tile": TILE,
        "spatial_chunks": spatial_chunks,
    }
