"""Discovery over plain HTTP, where an unconsolidated store cannot be listed.

The fixtures are served from a local http.server; arrays must be found from
the STAC hints by following dimension, coordinates and grid_mapping names,
and multiscale levels, and give the same card as a local read.
"""

import functools
import http.server
import os
import threading

import pytest

pytest.importorskip("aiohttp")

from storecard import card  # noqa: E402

FIDS = ["f01a-oisst-native", "f01d-oisst-transform", "f03d-asi-latlon2d",
        "f03f-asi-gridmap-named", "f08a-esm-native", "f08c-esm-geo2d"]


class NoListing(http.server.SimpleHTTPRequestHandler):
    """Serves files but no directory indexes, as an object store over HTTP does."""

    def list_directory(self, path):
        self.send_error(404)
        return None

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def server(fixtures):
    root = os.path.dirname(next(iter(fixtures.values()))[0])
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(NoListing, directory=root))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def strip(c):
    """The parts of a card that do not depend on how the store was reached."""
    return ([(v["name"], v["grid"]["costume"], v["grid"]["form"], v["crs"]["declared"], v["cost"])
             for v in c["variables"]],
            sorted(set(c["findings_summary"]) - {"GROUP_NOT_LISTABLE"}))


@pytest.mark.parametrize("fid", FIDS)
def test_http_matches_local(fixtures, server, fid):
    path, stac = fixtures[fid]
    local = card(path, stac=stac, probe_hosts=False)
    remote = card(f"{server}/{fid}.zarr", stac=stac, probe_hosts=False)
    assert remote["source"]["listable"] is False
    assert "GROUP_NOT_LISTABLE" in remote["findings_summary"]
    assert strip(remote) == strip(local)
