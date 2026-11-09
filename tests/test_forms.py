"""Virtual store forms: kerchunk JSON, kerchunk Parquet, Icechunk.

Each fixture's virtual twin (tests/virtual.py: same metadata, every chunk a
reference to the fixture's own chunk files) must give the same variables as
the fixture itself, so a card does not depend on the form a store is
delivered in. The twins' references are file paths, which no browser can
follow: CHUNK_REFS_NOT_HTTP is the one finding they add.

Chunk hosts are probed from a sample of the index (first and last chunk of
each data array), and no chunk byte is read: the HTTP tests serve chunk
references pointing at a server that logs every request.
"""

import http.server
import json
import threading

import pytest

import virtual
from storecard import card, forms
from test_fixtures import ALL, FINDINGS

pytest.importorskip("fsspec")

FORMS = {
    "kerchunk json": lambda st, out: virtual.write_kerchunk_json(st, out + ".json"),
    "kerchunk parquet": lambda st, out: virtual.write_kerchunk_parquet(st, out + ".parq"),
    "icechunk": lambda st, out: virtual.icechunk_repo(st, out + ".icechunk"),
}


@pytest.fixture(scope="module")
def twins(fixtures, tmp_path_factory):
    root = tmp_path_factory.mktemp("twins")
    cache = {}

    def get(fid, form):
        if (fid, form) not in cache:
            if form == "icechunk":
                pytest.importorskip("icechunk")
            cache[fid, form] = FORMS[form](fixtures[fid][0], str(root / fid))
        return cache[fid, form]
    return get


@pytest.mark.parametrize("form", list(FORMS))
@pytest.mark.parametrize("fid", ALL)
def test_twin_card_matches_fixture(fixtures, twins, fid, form):
    plain = card(fixtures[fid][0], probe_hosts=False)
    twin = card(twins(fid, form), probe_hosts=False)
    assert twin["source"]["form"] == form
    assert twin["variables"] == plain["variables"]
    # (no STAC here, so F08's FILL_NOT_REPRESENTABLE, from STAC nodata, is absent from both)
    assert set(twin["findings_summary"]) == set(plain["findings_summary"]) | {"CHUNK_REFS_NOT_HTTP"}
    assert set(plain["findings_summary"]) <= FINDINGS[fid]
    chunk_hosts = [h for h in twin["hosts"] if h["role"] == "chunks"]
    assert [(h["protocol"], h["host"]) for h in chunk_hosts] == [("file", "")]
    data = sorted(v["name"] for v in plain["variables"])
    assert sorted(chunk_hosts[0]["arrays"]) == data


def test_detected_form_and_source_fields(twins):
    fid = "f03e-asi-projjson"
    pq = card(twins(fid, "kerchunk parquet"), probe_hosts=False)["source"]
    assert pq["zarr_format"] == 2 and pq["record_size"] == 1000
    js = card(twins(fid, "kerchunk json"), probe_hosts=False)["source"]
    assert js["refs_version"] == 1
    ic = card(twins(fid, "icechunk"), probe_hosts=False)["source"]
    assert ic["zarr_format"] == 3 and ic["branch"] == "main" and ic["snapshot"]
    assert len(ic["virtual_chunk_containers"]) == 1
    assert ic["virtual_chunk_containers"][0].startswith("file://")


def test_icechunk_twin_takes_the_f03d_assertion(fixtures, twins):
    """An Icechunk twin keeps the v3 metadata documents unchanged, so its
    metadata digest is the store's, and an assertion made on the store
    applies to the twin."""
    from storecard import assertion as A
    from test_assertion import BREMEN_SOUTH, BY

    plain = card(fixtures["f03d-asi-latlon2d"][0], probe_hosts=False)
    doc = A.grid_assertion(plain, "z", BREMEN_SOUTH, {"proj:code": "EPSG:3412"},
                           evidence={"method": "fixtures-plan F03"}, by=BY)
    twin = twins("f03d-asi-latlon2d", "icechunk")
    assert card(twin, probe_hosts=False)["source"]["metadata_digest"] == plain["source"]["metadata_digest"]
    asserted = card(twin, probe_hosts=False, assertions=[doc])
    assert asserted["source"]["assertions"][0]["applied"]
    assert asserted["variables"][0]["grid"]["costume"] == "B"


def test_unavailable_codec_is_recorded_not_needed(fixtures, tmp_path):
    """A codec this environment cannot load (here a made-up filter) does not
    stop the card: the chain is recorded, and decoding is refused."""
    st = fixtures["f03e-asi-projjson"][0]
    refs = virtual.kerchunk_refs(st, only={"z"}, filters=[{"id": "storecard_test_nothing", "k": 1}])
    out = tmp_path / "f03e-filtered.json"
    out.write_text(json.dumps(refs))
    c = card(str(out), probe_hosts=False)
    z = next(a for a in c["arrays"] if a["name"] == "z")
    assert z["codecs"] == ["storecard_test_nothing", "zstd"]
    assert "storecard_test_nothing" in forms.unavailable_codecs()
    g = forms.open_store(str(out)).group
    with pytest.raises(Exception, match="placeholder"):
        g["z"][0]


# ---------------------------------------------------------------- chunk hosts over HTTP

class ChunkHost(http.server.BaseHTTPRequestHandler):
    """A chunk host that logs requests, refuses HEAD with an Origin (as
    THREDDS does), and answers a GET for bytes 0-0 with one byte. With
    cors=True it sends Access-Control-Allow-Origin."""

    cors = False
    log = None

    def _record(self):
        self.log.append((self.command, self.path, self.headers.get("Range")))

    def do_HEAD(self):
        self._record()
        if self.headers.get("Origin"):
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def do_GET(self):
        self._record()
        if self.headers.get("Range") != "bytes=0-0":
            self.send_response(416)
            self.end_headers()
            return
        self.send_response(206)
        self.send_header("Content-Range", "bytes 0-0/100")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", "1")
        if self.cors:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b"C")

    def log_message(self, *a):
        pass


def _serve(cors):
    log = []
    handler = type("H", (ChunkHost,), {"cors": cors, "log": log})
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, log


@pytest.mark.parametrize("cors", [False, True])
def test_chunk_host_probe_reads_no_chunk(fixtures, tmp_path, cors):
    httpd, log = _serve(cors)
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}/"
        st = fixtures["f03e-asi-projjson"][0]
        # the data array's chunks on the HTTP host, past its first byte;
        # the coordinates stay local, so the card reads nothing from the host
        refs = virtual.kerchunk_refs(st, url_base=base, offset=8, only={"z"})
        out = tmp_path / "f03e-http.json"
        out.write_text(json.dumps(refs))
        c = card(str(out))
    finally:
        httpd.shutdown()
    h = next(h for h in c["hosts"] if h["role"] == "chunks")
    assert h["host"] == f"127.0.0.1:{httpd.server_address[1]}"
    assert h["arrays"] == ["z"]
    assert h["head"]["status"] == 403
    assert h["method"] == "GET bytes=0-0" and h["status"] == 206 and h["range"]
    assert (h["cors"] == "*") is cors
    assert ("CHUNK_HOST_NO_CORS" in c["findings_summary"]) is not cors
    assert "CHUNK_REFS_NOT_HTTP" not in c["findings_summary"]
    # one HEAD and one GET of the first byte; no chunk byte requested
    assert [(m, r) for m, _, r in log] == [("HEAD", None), ("GET", "bytes=0-0")]


def test_chunk_host_probe_skips_get_at_offset_zero(fixtures, tmp_path):
    """When the sampled chunk starts at byte 0, the first byte is chunk data:
    a refused HEAD is recorded and no GET is sent."""
    httpd, log = _serve(True)
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}/"
        refs = virtual.kerchunk_refs(fixtures["f03e-asi-projjson"][0], url_base=base,
                                     offset=0, only={"z"})
        out = tmp_path / "f03e-http0.json"
        out.write_text(json.dumps(refs))
        c = card(str(out))
    finally:
        httpd.shutdown()
    h = next(h for h in c["hosts"] if h["role"] == "chunks")
    assert h["method"] == "HEAD" and h["status"] == 403 and "error" in h
    assert [m for m, _, _ in log] == ["HEAD"]
    assert "CHUNK_HOST_NO_CORS" not in c["findings_summary"]
