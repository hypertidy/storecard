#!/usr/bin/env python3
"""Write OUT_DIR/catalog/catalog.json listing every collection under it.

    python3 -I build/catalog.py OUT_DIR

Run after any builder. Collections live at catalog/<family>/<id>/collection.json;
the root catalog links all of them, so families can be built independently.
"""

import glob
import json
import os
import sys


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    cat = os.path.join(sys.argv[1], "catalog")
    paths = sorted(glob.glob(os.path.join(cat, "*", "*", "collection.json")))
    links = [{"rel": "root", "href": "./catalog.json", "type": "application/json"}]
    for p in paths:
        rel = os.path.relpath(p, cat).replace(os.sep, "/")
        title = json.load(open(p)).get("id", rel)
        links.append({"rel": "child", "href": f"./{rel}", "type": "application/json", "title": title})
    root = {
        "type": "Catalog", "stac_version": "1.1.0", "id": "portolan-fixtures",
        "description": "Zarr conformance fixtures: polar, ocean and virtual cases, built as twins.",
        "links": links,
    }
    with open(os.path.join(cat, "catalog.json"), "w") as fh:
        json.dump(root, fh, indent=2)
    print(f"catalog.json: {len(paths)} collections")


if __name__ == "__main__":
    main()
