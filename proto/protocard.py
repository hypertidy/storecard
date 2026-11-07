#!/usr/bin/env python3
"""Prototype store card for local netCDF files: grid and value facts only.

    python3 -I proto/protocard.py FILE [FILE ...] > cards.jsonl

A first cut of the card extractor, run over files rather than stores. It reads
metadata and the coordinate arrays (small), never data variables. Output is
one JSON object per file, with a `findings` list using the codes from the
README. Not the final format: it exists to learn which facts matter.
"""

import json
import sys

import numpy as np

try:
    import netCDF4
except ImportError:
    sys.exit("needs netCDF4")

MERC_R = 6378137.0


def spacing(v):
    """Classify a 1-D coordinate: regular, mercator (lat only), irregular."""
    v = np.asarray(v, dtype="float64")
    if v.size < 3 or not np.all(np.isfinite(v)):
        return "short" if v.size < 3 else "nonfinite"
    d = np.diff(v)
    if np.all(d > 0) or np.all(d < 0):
        span_step = (v[-1] - v[0]) / (v.size - 1)
        if np.max(np.abs(d - span_step)) <= 1e-3 * abs(span_step):
            return "regular"
        if np.all(np.abs(v) < 89.999):
            y = MERC_R * np.log(np.tan(np.pi / 4 + np.deg2rad(v) / 2))
            dy = np.diff(y)
            if np.max(np.abs(dy - dy.mean())) <= 1e-3 * abs(dy.mean()):
                return "mercator"
        return "irregular"
    return "nonmonotonic"


def role(var):
    a = {k: str(getattr(var, k)) for k in var.ncattrs()}
    name = var.name.lower()
    units = a.get("units", "").lower()
    sn = a.get("standard_name", "").lower()
    if sn in ("longitude",) or units.startswith("degree") and ("east" in units or units in ("degrees_e",)) or name in ("lon", "longitude", "nav_lon", "xlong"):
        return "lon"
    if sn in ("latitude",) or units.startswith("degree") and ("north" in units or units in ("degrees_n",)) or name in ("lat", "latitude", "nav_lat", "xlat"):
        return "lat"
    if sn in ("projection_x_coordinate", "grid_longitude") or a.get("axis") == "X":
        return "x"
    if sn in ("projection_y_coordinate", "grid_latitude") or a.get("axis") == "Y":
        return "y"
    return None


def card(path):
    out = {"source": {"path": path, "form": "netcdf"}, "arrays": [], "coords": {},
           "crs": {}, "findings": []}
    try:
        ds = netCDF4.Dataset(path)
    except Exception as e:
        out["findings"].append({"code": "OPEN_FAILED", "detail": str(e)[:120]})
        return out
    ds.set_auto_mask(False)
    roles = {}
    for name, v in ds.variables.items():
        r = role(v)
        if r:
            roles[name] = r
            info = {"role": r, "dims": list(v.dimensions), "shape": list(v.shape)}
            if v.ndim == 1 and v.size <= 200000:
                info["spacing"] = spacing(v[:])
                vals = np.asarray(v[:], dtype="float64")
                if vals.size:
                    info["range"] = [float(np.nanmin(vals)), float(np.nanmax(vals))]
            out["coords"][name] = info
    gms = []
    for name, v in ds.variables.items():
        a = {k: getattr(v, k) for k in v.ncattrs()}
        if "grid_mapping_name" in a:
            gms.append({"var": name, "grid_mapping_name": str(a["grid_mapping_name"]),
                        "has_wkt": "crs_wkt" in a or "spatial_ref" in a})
    out["crs"]["grid_mappings"] = gms

    for name, v in ds.variables.items():
        if name in roles or v.ndim < 2:
            continue
        a = {k: getattr(v, k) for k in v.ncattrs()}
        arr = {"name": name, "dims": list(v.dimensions), "shape": list(v.shape),
               "dtype": str(v.dtype)}
        try:
            ch = v.chunking()
            arr["chunks"] = ch if ch == "contiguous" else list(ch)
        except Exception:
            pass
        for k in ("units", "scale_factor", "add_offset", "_FillValue", "missing_value",
                  "valid_range", "grid_mapping", "coordinates"):
            if k in a:
                val = a[k]
                arr[k] = val.tolist() if hasattr(val, "tolist") else str(val)
        out["arrays"].append(arr)

        named = str(a.get("coordinates", "")).split()
        missing = [c for c in named if c not in ds.variables]
        if missing:
            out["findings"].append({"code": "COORDS_NAMED_MISSING", "array": name, "missing": missing})
        gm = a.get("grid_mapping")
        if gm is not None and str(gm).split(":")[0] not in ds.variables:
            out["findings"].append({"code": "GRID_MAPPING_NAMED_MISSING", "array": name, "grid_mapping": str(gm)})

    # grid classification from the coordinates present
    c1 = {n: c for n, c in out["coords"].items() if len(c["dims"]) == 1}
    c2 = {n: c for n, c in out["coords"].items() if len(c["dims"]) == 2}
    if c2 and any(c["role"] in ("lon", "lat") for c in c2.values()):
        projected_1d = any(c["role"] in ("x", "y") for c in c1.values())
        code = "GRID_2D_WITH_PROJECTED_1D" if projected_1d else "GRID_2D_LONLAT_ONLY"
        out["findings"].append({"code": code,
                                "note": "candidate for a degredation fit (cryptic curvilinear?)" if not projected_1d else "2-D lon/lat beside x/y: lon/lat are derived"})
    for n, c in c1.items():
        sp = c.get("spacing")
        if sp == "mercator":
            out["findings"].append({"code": "LAT_MERCATOR_SPACED", "coord": n})
        elif sp == "irregular":
            out["findings"].append({"code": "COORD_IRREGULAR", "coord": n})
        elif sp == "nonmonotonic":
            out["findings"].append({"code": "COORD_NONMONOTONIC", "coord": n})
        rng = c.get("range")
        if c["role"] == "lon" and rng and rng[1] > 180:
            out["findings"].append({"code": "LON_0_360", "coord": n})
        if c["role"] == "lon" and rng and rng[0] < -180:
            out["findings"].append({"code": "LON_BELOW_MINUS_180", "coord": n})
        if c["role"] == "lat" and sp in ("regular", "irregular", "mercator") and rng:
            vals = ds.variables[n][:]
            if vals.size > 1 and vals[1] > vals[0]:
                out["findings"].append({"code": "Y_ASCENDING", "coord": n})
    if not gms and any(c["role"] in ("x", "y") for c in out["coords"].values()):
        out["findings"].append({"code": "PROJECTED_NO_GRID_MAPPING"})
    for arr in out["arrays"]:
        dims = arr["dims"]
        roles_of = [next((c["role"] for nn, c in c1.items() if c["dims"] == [d]), None) for d in dims]
        sp = [r for r in roles_of if r]
        if len(sp) >= 2 and sp[-2:] in (["lon", "lat"], ["x", "y"]):
            out["findings"].append({"code": "AXES_X_BEFORE_Y", "array": arr["name"], "dims": dims})
    ds.close()
    # de-duplicate findings
    seen, uniq = set(), []
    for f in out["findings"]:
        k = json.dumps(f, sort_keys=True)
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    out["findings"] = uniq
    return out


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(json.dumps(card(p), default=str))
