"""Build the published cards: one per store, committed under cards/.

Three collections:

  portolan/      the Portolan Zarr fixtures on Pawsey, found from their STAC
                 catalog; one card per fixture (<id>.json)
  ausantarctic/  the ausantarctic scratch virtual stores on source.coop, each
                 as Icechunk and as kerchunk Parquet (<dataset>.<form>.json)
  thelist/       the COGs of the Tasmanian LIST mirror on source.coop; one
                 file per product, one card per line (<product>.jsonl), the
                 files listed in thelist/keys.txt

and cards/index.json, one entry per gallery item: where the card is, a short
summary of it, and the assertions in assertions/ whose subject is that store,
each with whether its digest is current and which findings it clears when
applied. The site's gallery (site/gallery.py) is drawn from index.json alone.

Run from the repository root (reads metadata over the network; the COG
cards need osgeo.gdal):

    python cards/build.py              # build what is missing, then the index
    python cards/build.py --force      # rebuild every card
    python cards/build.py --index      # only rewrite index.json (still applies assertions)

A card is metadata only, so a rebuild reads no data chunk and no pixel block.
"""

import argparse
import concurrent.futures as cf
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent

PAWSEY = "https://projects.pawsey.org.au/aad-derived/portolan-fixtures/catalog/catalog.json"
SCRATCH = "https://data.source.coop/ausantarctic/ausantarctic-scratch/"
THELIST = "https://data.source.coop/mdsumner/thelist-opendata/"

AUSANTARCTIC = [
    "oisst/oisst-v2.1-daily",
    "seaice/g02202-v6-daily-south",
    "seaice/g02202-v6-daily-north",
    "seaice/asi-amsr2-v5.4-daily-south",
    "bluelink/bluelink-daily-salt",
    "ghrsst/ghrsst-mur-cog-analysed_sst",
]
FORMS = ("icechunk", "kerchunk")

COLLECTIONS = {
    "portolan": {
        "title": "Portolan fixtures",
        "about": "Zarr twins on Pawsey: the same data in presentations that should draw identically.",
        "home": "https://projects.pawsey.org.au/aad-derived/portolan-fixtures/catalog/catalog.json",
    },
    "ausantarctic": {
        "title": "ausantarctic virtual stores",
        "about": "Virtual stores on source.coop (Icechunk and kerchunk Parquet) over the publishers' own files.",
        "home": "https://source.coop/ausantarctic/ausantarctic-scratch",
    },
    "thelist": {
        "title": "Tasmanian LIST mirror",
        "about": "Cloud-optimised GeoTIFFs on source.coop, one entry per product.",
        "home": "https://source.coop/mdsumner/thelist-opendata",
    },
}


def _get(url):
    for i in range(6):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except OSError:
            time.sleep(2 * (i + 1))
    raise OSError(f"could not fetch {url}")


def _retry(fn, *args, **kw):
    for i in range(4):
        try:
            return fn(*args, **kw)
        except Exception as e:              # hosts reset connections now and then
            err = e
            time.sleep(3 * (i + 1))
    raise err


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1) + "\n")


# ---------------------------------------------------------------- jobs

def job_portolan(href, path):
    from storecard import card
    col = _get(href)
    data = next(a for a in col["assets"].values() if "data" in a.get("roles", []))["href"]
    c = _retry(card, data, stac=col)
    c["source"]["stac"] = href
    _write(path, c)
    return str(path)


def job_ausantarctic(ds, form, path):
    from storecard import card
    _write(path, _retry(card, SCRATCH + ds + "/" + form))
    return str(path)


def job_thelist(product, keys, path):
    from storecard import card
    lines = [json.dumps(_retry(card, THELIST + k)) for k in keys]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def thelist_products():
    out = {}
    for k in (HERE / "thelist" / "keys.txt").read_text().split():
        out.setdefault(k.split("/")[1], []).append(k)
    return out


def jobs():
    cat = _get(PAWSEY)
    for link in cat["links"]:
        if link["rel"] == "child":
            href = urllib.parse.urljoin(PAWSEY, link["href"])
            fid = href.split("/")[-2]
            yield job_portolan, (href, HERE / "portolan" / f"{fid}.json")
    for ds in AUSANTARCTIC:
        for form in FORMS:
            yield job_ausantarctic, (ds, form, HERE / "ausantarctic" / f"{ds.split('/')[1]}.{form}.json")
    for product, keys in thelist_products().items():
        yield job_thelist, (product, keys, HERE / "thelist" / f"{product}.jsonl")


def build(force=False, workers=6):
    todo = [(f, a) for f, a in jobs() if force or not a[-1].exists()]
    failed = 0
    with cf.ProcessPoolExecutor(workers) as ex:
        futs = {ex.submit(f, *a): a[-1] for f, a in todo}
        for fut in cf.as_completed(futs):
            try:
                print("built", pathlib.Path(fut.result()).relative_to(ROOT), file=sys.stderr)
            except Exception as e:
                failed += 1
                print("FAILED", futs[fut].relative_to(ROOT), repr(e), file=sys.stderr)
    return failed


# ---------------------------------------------------------------- index

def _crs(v):
    """The CRS a variable declares, as short labels: one per distinct source.

    {"declared": bool, "labels": [...]}; a STAC proj:code is listed (marked
    STAC) but, as in the card, does not make the store's CRS declared."""
    c = v.get("crs") or {}
    labels = []
    for s in c.get("sources") or []:
        via = s.get("via") or ""
        if s.get("id") or s.get("value"):
            lab = str(s.get("id") or s.get("value"))
            if via.startswith("STAC"):
                lab += " (STAC only)"
        elif s.get("grid_mapping_name"):
            lab = f"CF {s['grid_mapping_name']}"
        elif s.get("name"):
            m = next((m for m in s.get("matches", []) if m.get("equivalent")), None)
            lab = f"{s['name']}, no id" + (f" (equivalent to {m['id']})" if m else "")
        else:
            lab = via or "unknown"
        if lab not in labels:
            labels.append(lab)
    return {"declared": bool(c.get("declared")), "labels": labels}


def _costumes(vs):
    """Costume labels of some variables; an undecided one (a list) as "E/H"."""
    out = set()
    for v in vs:
        c = v["grid"].get("costume")
        if c:
            out.add("/".join(c) if isinstance(c, list) else c)
    return sorted(out)


def _grid(v):
    g = v["grid"]
    out = {"form": g.get("form"), "declared": g.get("declared", [])}
    t = (g.get("transform") or {}).get("spatial:transform")
    if t:
        out["transform"] = t
    if g.get("costume_presented"):
        out["costume_presented"] = g["costume_presented"]
    return out


def _spatial_shape(v):
    sd = v["grid"].get("spatial_dims") or []
    dims = v.get("dims") or []
    if sd and all(d in dims for d in sd):
        return [v["shape"][dims.index(d)] for d in sd]
    return v["shape"][-2:]


def summary(c):
    """The gallery's view of one card: its first variable stands for the grid."""
    vs = c["variables"]
    out = {
        "url": c["source"]["url"],
        "form": c["source"]["form"],
        "metadata_digest": c["source"].get("metadata_digest"),
        "scanned_at": c["source"].get("scanned_at"),
        "variables": [v["name"] for v in vs],
        "costumes": _costumes(vs),
        "hosts": [{**{k: h.get(k) for k in ("role", "host", "cors", "range")}, "probed": "error" not in h}
                  for h in c["hosts"]],
        "findings": {k: len(a) for k, a in c["findings_summary"].items()},
    }
    if vs:
        v = vs[0]
        out["shape"] = v["shape"]
        out["dims"] = v.get("dims")
        out["spatial_shape"] = _spatial_shape(v)
        out["dtype"] = v["values"].get("dtype")
        out["grid"] = _grid(v)
        out["crs"] = _crs(v)
    return out


def _assertions():
    docs = []
    for p in sorted((ROOT / "assertions").rglob("*.json")):
        d = json.loads(p.read_text())
        if "subject" in d:
            docs.append((p.relative_to(ROOT).as_posix(), d))
    return docs


def _apply(c, docs, stac=None):
    """Findings left once the assertions are applied (a metadata re-read)."""
    from storecard import card
    a = _retry(card, c["source"]["url"], stac=stac, assertions=[d for _, d in docs], probe_hosts=False)
    applied = {x.get("variable"): x for x in a["source"]["assertions"]}
    return a, applied


def _asserted(c, docs, stac=None):
    """Index records for the assertions about card c, and what they clear."""
    mine = [(p, d) for p, d in docs if d["subject"]["url"].rstrip("/") == c["source"]["url"].rstrip("/")]
    if not mine:
        return [], None
    recs = []
    for p, d in mine:
        r = {"path": p, "kind": d["kind"], "variable": d["subject"].get("variable"), "status": d.get("status"),
             "by": (d.get("by") or {}).get("name"),
             "current": d["subject"].get("metadata_digest") == c["source"].get("metadata_digest")}
        if d["kind"] == "grid":
            r["asserts"] = {k: d["asserts"][k] for k in ("proj:code", "spatial:transform") if k in d["asserts"]}
        if d["kind"] == "refusal":
            r["refuses"] = d.get("refuses")
        recs.append(r)
    grids = [(p, d) for p, d in mine if d["kind"] != "refusal"]
    after = None
    if grids:
        a, _ = _apply(c, grids, stac)
        before, left = c["findings_summary"], a["findings_summary"]
        # per code: arrays it was found on, and how many of those the assertions clear
        clears = {k: {"of": len(v), "cleared": len(set(v) - set(left.get(k, [])))}
                  for k, v in before.items() if set(v) - set(left.get(k, []))}
        after = {"clears": clears, "adds": sorted(set(left) - set(before)),
                 "costumes": _costumes(a["variables"])}
    return recs, after


def _tidy(c):
    """What cog.tidy_assertion would clear on a GeoTIFF card, or None."""
    from storecard import assertion as A
    from storecard import cog
    try:
        d = cog.tidy_assertion(c)
    except A.AssertionError_:
        return None
    return {"proj:code": d["asserts"].get("proj:code"), "spatial:transform": d["asserts"]["spatial:transform"]}


def index():
    docs = _assertions()
    entries = []
    for p in sorted((HERE / "portolan").glob("*.json")):
        c = json.loads(p.read_text())
        e = {"id": p.stem, "collection": "portolan", "card": p.relative_to(ROOT).as_posix(), **summary(c)}
        e["stac"] = c["source"].get("stac")
        e["assertions"], e["asserted"] = _asserted(c, docs, stac=e["stac"])
        entries.append(e)
    for p in sorted((HERE / "ausantarctic").glob("*.json")):
        c = json.loads(p.read_text())
        e = {"id": p.stem, "collection": "ausantarctic", "card": p.relative_to(ROOT).as_posix(), **summary(c)}
        e["assertions"], e["asserted"] = _asserted(c, docs)
        entries.append(e)
    for p in sorted((HERE / "thelist").glob("*.jsonl")):
        cards = [json.loads(line) for line in p.read_text().splitlines() if line]
        ss = [summary(c) for c in cards]
        findings = {}
        for s in ss:
            for k in s["findings"]:
                findings[k] = findings.get(k, 0) + 1          # files with the finding
        tidy = [t for t in map(_tidy, cards) if t]
        files = []
        for c, s in zip(cards, ss):
            files.append({"url": s["url"], "spatial_shape": s["spatial_shape"], "crs": "; ".join(s["crs"]["labels"]),
                          "transform": s["grid"].get("transform"), "findings": sorted(s["findings"]),
                          "bands": len(s["variables"]), "dtype": s["dtype"]})
        e = {"id": p.stem, "collection": "thelist", "card": p.relative_to(ROOT).as_posix(),
             "url": THELIST + "cog/" + p.stem + "/", "form": ss[0]["form"],
             "n_files": len(cards), "files": files,
             "variables": ss[0]["variables"], "dtype": sorted({s["dtype"] for s in ss}),
             "costumes": sorted({x for s in ss for x in s["costumes"]}),
             "crs": {"declared": all(s["crs"]["declared"] for s in ss),
                     "labels": sorted({x for s in ss for x in s["crs"]["labels"]})},
             "hosts": ss[0]["hosts"], "findings": findings,
             "scanned_at": max(s["scanned_at"] for s in ss),
             "assertions": [], "asserted": None,
             "tidy": {"files": len(tidy), "codes": sorted({t["proj:code"] for t in tidy if t["proj:code"]}),
                      "clears": sorted(set(findings) & {"CRS_NO_AUTHORITY_ID", "TRANSFORM_NEAR_ROUND"})}
             if tidy else None}
        if len(cards) == 1:
            e["url"] = ss[0]["url"]
            e["spatial_shape"] = ss[0]["spatial_shape"]
            e["grid"] = ss[0]["grid"]
        entries.append(e)
    doc = {"index_version": "0", "collections": COLLECTIONS, "entries": entries}
    _write(HERE / "index.json", doc)
    print(f"{len(entries)} entries", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="rebuild cards that already exist")
    ap.add_argument("--index", action="store_true", help="only rewrite index.json")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    failed = 0 if a.index else build(a.force, a.workers)
    index()
    sys.exit(1 if failed else 0)
