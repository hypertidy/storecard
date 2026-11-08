"""Command line: python -m storecard URL [--stac PATH_OR_URL] [--assertion FILE ...] [--emit FORM] [--fit]"""

import argparse
import json
import sys

from . import assertion as A
from .card import card


def main(argv=None):
    ap = argparse.ArgumentParser(prog="storecard", description="Print a store card as JSON.")
    ap.add_argument("url", help="path or URL of a Zarr store")
    ap.add_argument("--stac", help="STAC collection, item or asset (path or URL)")
    ap.add_argument("--no-hosts", action="store_true", help="do not probe hosts for CORS and range support")
    ap.add_argument("--anon", action="store_true", help="anonymous access for s3:// URLs")
    ap.add_argument("--endpoint", help="S3 endpoint URL, for s3:// URLs outside AWS")
    ap.add_argument("--assertion", action="append", default=[],
                    help="assertion file to apply as an overlay (repeatable)")
    ap.add_argument("--emit", choices=["zarr", "stac", "vrt"],
                    help="print the (first) assertion in this form instead of the card")
    ap.add_argument("--fit", action="store_true",
                    help="print a grid fit of the card's coordinate sample as an assertion (needs osgeo.gdal)")
    ap.add_argument("--variable", help="variable to fit (default: the first with a coordinate sample)")
    a = ap.parse_args(argv)
    so = {}
    if a.anon:
        so["anon"] = True
    if a.endpoint:
        so["client_kwargs"] = {"endpoint_url": a.endpoint}
    if a.emit:
        if not a.assertion:
            ap.error("--emit needs --assertion")
        doc = A.load(a.assertion[0])
        if a.emit == "vrt":
            c = card(a.url, stac=a.stac, storage_options=so or None, probe_hosts=False)
            sys.stdout.write(A.to_vrt(doc, c))
            return
        out = A.to_zarr_attrs(doc) if a.emit == "zarr" else A.to_stac_patch(doc)
        json.dump(out, sys.stdout, indent=1)
        sys.stdout.write("\n")
        return
    if a.fit:
        from . import fit
        c = card(a.url, stac=a.stac, storage_options=so or None, probe_hosts=False)
        json.dump(fit.assertion(c, a.variable), sys.stdout, indent=1)
        sys.stdout.write("\n")
        return
    c = card(a.url, stac=a.stac, storage_options=so or None, probe_hosts=not a.no_hosts,
             assertions=a.assertion)
    json.dump(c, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
