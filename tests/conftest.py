"""Build the portolan fixtures from small synthetic sources, once per session.

The builders in portolan/build run unchanged, so the stores have the same
presentation, shapes and chunking as the published fixtures. Set
STORECARD_FIXTURES to a directory to keep the build between runs.
"""

import glob
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PORTOLAN = os.path.join(os.path.dirname(HERE), "portolan")
BASE = "https://projects.pawsey.org.au/aad-derived/portolan-fixtures"

sys.path.insert(0, HERE)
import synth  # noqa: E402


def _build(root):
    src = os.path.join(root, "src")
    out = os.path.join(root, "out")
    synth.oisst(os.path.join(src, "oisst"))
    synth.asi(os.path.join(src, "asi"))
    synth.g02202(os.path.join(src, "g02202"))
    esm = os.path.join(src, "esm", "ocean-3d-temp-1mon-mean-y_1850.nc")
    synth.esm(esm)
    runs = [
        ["build/build_f01.py", os.path.join(src, "oisst"), out, BASE],
        ["build/build_f03.py", os.path.join(src, "asi"), out, BASE],
        ["build/build_f03g.py", os.path.join(src, "g02202"), out, BASE, "south"],
        ["build/build_f08.py", esm, out, BASE],
    ]
    for r in runs:
        subprocess.run([sys.executable, "-I", *r], cwd=PORTOLAN, check=True,
                       stdout=subprocess.DEVNULL)
    return out


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory):
    """{fixture id: (store path, collection.json path)}"""
    keep = os.environ.get("STORECARD_FIXTURES")
    if keep and os.path.isdir(os.path.join(keep, "out", "stores")):
        out = os.path.join(keep, "out")
    else:
        root = keep or str(tmp_path_factory.mktemp("portolan"))
        os.makedirs(root, exist_ok=True)
        out = _build(root)
    found = {}
    for s in sorted(glob.glob(os.path.join(out, "stores", "*.zarr"))):
        fid = os.path.basename(s)[:-5]
        cols = glob.glob(os.path.join(out, "catalog", "*", fid, "collection.json"))
        found[fid] = (s, cols[0] if cols else None)
    return found
