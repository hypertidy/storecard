"""Command line: python -m storecard URL [--stac PATH_OR_URL] [--no-hosts]"""

import argparse
import json
import sys

from .card import card


def main(argv=None):
    ap = argparse.ArgumentParser(prog="storecard", description="Print a store card as JSON.")
    ap.add_argument("url", help="path or URL of a Zarr store")
    ap.add_argument("--stac", help="STAC collection, item or asset (path or URL)")
    ap.add_argument("--no-hosts", action="store_true", help="do not probe hosts for CORS and range support")
    ap.add_argument("--anon", action="store_true", help="anonymous access for s3:// URLs")
    ap.add_argument("--endpoint", help="S3 endpoint URL, for s3:// URLs outside AWS")
    a = ap.parse_args(argv)
    so = {}
    if a.anon:
        so["anon"] = True
    if a.endpoint:
        so["client_kwargs"] = {"endpoint_url": a.endpoint}
    c = card(a.url, stac=a.stac, storage_options=so or None, probe_hosts=not a.no_hosts)
    json.dump(c, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
