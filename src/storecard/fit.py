"""Grid fit from a card (step 2 of the brief).

A card carries a sample of a variable's 2-D lon/lat coordinates: the edge
rows and columns and the central cross. A fit projects that sample into
each of a list of named frames (CRSs) and asks whether the grid is regular
there: does one affine map from (col, row) to (x, y) put every sampled cell
centre within a small fraction of a cell? If a frame passes, the affine is
snapped to its shortest decimal form, checked again, and returned with the
residuals as evidence. If no frame passes, the result is a refusal that
lists every frame tried and how far off it was.

This is a check of named frames, not open-ended inference: it can say
"regular in EPSG:3412 with this transform" or "regular in none of these".
Choosing a frame for coordinates that match no published grid belongs to
hypertidy/degredation; the frames and tests here are the contract it is
held to.

Only the card is read: no store access, no data chunks. Projection is done
with GDAL's osr (osgeo.gdal), imported when a fit runs.
"""

import math

import numpy as np

from . import assertion as A

# Frames tried by default, in order. Published grids whose cells are regular
# in the frame: polar stereographic (NSIDC, Antarctic and Arctic), EASE and
# EASE-Grid 2.0, web mercator and longitude/latitude itself (a 2-D lon/lat
# pair that is an outer product of 1-D axes, cryptically degenerate).
FRAMES = (
    "EPSG:3412", "EPSG:3411", "EPSG:3976", "EPSG:3413", "EPSG:3031", "EPSG:3995",
    "EPSG:6932", "EPSG:6931", "EPSG:3409", "EPSG:3408", "EPSG:6933", "EPSG:3410",
    "EPSG:3857", "EPSG:4326",
)

# a frame passes when every sampled cell centre is within this many cells
TOL_CELLS = 1e-3
# frames that are geographic are fitted in degrees with longitude unwrapped
GEOGRAPHIC = "geographic"


def _points(cs):
    """(col, row, lon, lat) of the sampled cell centres, finite only."""
    cols, rows, lon, lat = [], [], [], []
    for line in cs["rows"]:
        n = len(line["at"])
        rows += [line["index"]] * n
        cols += list(line["at"])
        lon += list(line["lon"])
        lat += list(line["lat"])
    for line in cs["cols"]:
        n = len(line["at"])
        cols += [line["index"]] * n
        rows += list(line["at"])
        lon += list(line["lon"])
        lat += list(line["lat"])

    def f(v):
        return np.array([x if isinstance(x, (int, float)) else math.nan for x in v], dtype="float64")

    c, r, lo, la = f(cols), f(rows), f(lon), f(lat)
    ok = np.isfinite(lo) & np.isfinite(la) & (np.abs(la) <= 90)
    return c[ok], r[ok], lo[ok], la[ok]


def _srs(code):
    from osgeo import osr
    osr.UseExceptions()
    s = osr.SpatialReference()
    s.SetFromUserInput(code)
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


def _project(code, lon, lat):
    """Easting/northing (or unwrapped lon/lat) of the points in a frame;
    None where the frame cannot take them."""
    from osgeo import osr
    dst = _srs(code)
    if dst.IsGeographic():
        ref = float(np.median(lon))
        return (lon - ref + 180) % 360 - 180 + ref, lat.copy()
    tr = osr.CoordinateTransformation(_srs("EPSG:4326"), dst)
    try:
        xyz = np.array(tr.TransformPoints(np.column_stack([lon, lat])), dtype="float64")
    except RuntimeError:
        return None
    x, y = xyz[:, 0], xyz[:, 1]
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        return None
    return x, y


def _affine(col, row, x, y):
    """Least-squares [a, b, c, d, e, f], cell-corner origin: centres sit at
    (col + 0.5, row + 0.5)."""
    m = np.column_stack([col + 0.5, row + 0.5, np.ones_like(col)])
    (a, b, c), *_ = np.linalg.lstsq(m, x, rcond=None)
    (d, e, f), *_ = np.linalg.lstsq(m, y, rcond=None)
    return [float(a), float(b), float(c), float(d), float(e), float(f)]


def _residual_cells(t, col, row, x, y):
    """Largest distance from a sampled centre to the affine's, in cells."""
    a, b, c, d, e, f = t
    px = a * (col + 0.5) + b * (row + 0.5) + c
    py = d * (col + 0.5) + e * (row + 0.5) + f
    cell = math.sqrt(abs(a * e - b * d))
    if not cell:
        return math.inf
    return float(np.max(np.hypot(px - x, py - y)) / cell)


def _snap(t, col, row, x, y, tol):
    """Round each coefficient to the fewest decimals that keep the fit
    within tol; terms near zero go to exactly zero first."""
    cell = math.sqrt(abs(t[0] * t[4] - t[1] * t[3]))
    out = list(t)
    for i in (1, 3):                      # rotation / shear terms
        trial = out[:]
        trial[i] = 0.0
        if _residual_cells(trial, col, row, x, y) <= tol:
            out = trial
    for i in range(6):
        if out[i] == 0.0:
            continue
        mag = max(abs(out[i]), cell)
        for digits in range(-int(math.floor(math.log10(mag))), 13):
            trial = out[:]
            trial[i] = round(out[i], digits) + 0.0
            if _residual_cells(trial, col, row, x, y) <= tol:
                out = trial
                break
    return out


def _digits(t):
    """Significant decimal characters of a transform: the roundness score."""
    n = 0
    for v in t:
        s = repr(float(v)).rstrip("0").rstrip(".").lstrip("-")
        n += len(s.replace(".", "").strip("0")) if v else 0
    return n


def fit_variable(variable, frames=FRAMES, tol=TOL_CELLS):
    """Fit one card variable's coordinate sample against named frames.

    Returns {"verdict": "fitted" | "refused", ...}. A fitted result carries
    "proj:code", "spatial:transform" (snapped) and the residuals; both carry
    "frames_tried", one entry per frame with its residual in cells.
    """
    cs = variable["grid"].get("coord_sample")
    if not cs:
        return {"verdict": "refused", "reason": "no 2-D coordinate sample on the card",
                "frames_tried": []}
    col, row, lon, lat = _points(cs)
    if len(col) < 6:
        return {"verdict": "refused", "reason": "too few finite sample points",
                "frames_tried": [], "points": int(len(col))}
    tried, passed = [], []
    for code in frames:
        p = _project(code, lon, lat)
        if p is None:
            tried.append({"frame": code, "residual_cells": None, "note": "points outside the frame"})
            continue
        x, y = p
        t = _affine(col, row, x, y)
        res = _residual_cells(t, col, row, x, y)
        entry = {"frame": code, "residual_cells": res}
        tried.append(entry)
        if res <= tol:
            s = _snap(t, col, row, x, y, tol)
            entry["snapped"] = s
            entry["residual_cells_snapped"] = _residual_cells(s, col, row, x, y)
            entry["digits"] = _digits(s)
            passed.append(entry)
    out = {"points": int(len(col)), "tolerance_cells": tol, "frames_tried": tried,
           "shape": cs["shape"], "coords": [cs.get("lon"), cs.get("lat")]}
    if not passed:
        best = min((e for e in tried if e["residual_cells"] is not None),
                   key=lambda e: e["residual_cells"], default=None)
        out.update({"verdict": "refused",
                    "reason": "regular in none of the frames tried",
                    "best": best and {"frame": best["frame"], "residual_cells": best["residual_cells"]}})
        return out
    # the roundest snapped transform wins; residual breaks a tie
    passed.sort(key=lambda e: (e["digits"], e["residual_cells_snapped"]))
    win = passed[0]
    out.update({"verdict": "fitted", "proj:code": win["frame"],
                "spatial:transform": win["snapped"],
                "residual_cells": win["residual_cells_snapped"],
                "also_regular_in": [e["frame"] for e in passed[1:]]})
    return out


def fit(card, variable=None, **kw):
    """Fit a card's variable (the first with a coordinate sample by default)."""
    vs = [v for v in card["variables"] if variable in (None, v["name"])
          and (variable or v["grid"].get("coord_sample"))]
    if not vs:
        raise KeyError(f"no variable {variable!r} with a coordinate sample on the card")
    return vs[0]["name"], fit_variable(vs[0], **kw)


def _g(v):
    """A residual for the record: four significant digits."""
    return None if v is None else float(f"{v:.4g}")


def _software():
    from osgeo import gdal, osr
    proj = ".".join(str(f()) for f in (osr.GetPROJVersionMajor, osr.GetPROJVersionMinor,
                                       osr.GetPROJVersionMicro))
    return {"gdal": gdal.__version__, "proj": proj}


def assertion(card, variable=None, by=None, **kw):
    """The fit as an assertion document: a grid assertion when a frame fits,
    a refusal when none does."""
    name, r = fit(card, variable, **kw)
    by = by or {"name": "storecard.fit", "kind": "fit"}
    evidence = {
        "method": "storecard.fit: affine of projected coord_sample cell centres in named frames",
        "coords": r.get("coords"), "points": r.get("points"),
        "tolerance_cells": r.get("tolerance_cells"),
        "frames_tried": [{"frame": e["frame"], "residual_cells": _g(e["residual_cells"])}
                         for e in r["frames_tried"]],
        "software": _software(),
    }
    if r["verdict"] == "refused":
        if r.get("best"):
            evidence["best"] = {**r["best"], "residual_cells": _g(r["best"]["residual_cells"])}
        return A.refusal(card, name, r["reason"],
                         frames_tried=[e["frame"] for e in r["frames_tried"]],
                         evidence=evidence, by=by)
    evidence["residual_cells"] = _g(r["residual_cells"])
    evidence["also_regular_in"] = r["also_regular_in"]
    geo = _srs(r["proj:code"]).IsGeographic()
    return A.grid_assertion(card, name, r["spatial:transform"], {"proj:code": r["proj:code"]},
                            crs_axes=("y", "x") if geo else ("x", "y"),
                            evidence=evidence, by=by)
