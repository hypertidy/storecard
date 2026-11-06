#!/usr/bin/env python3
"""Static file server with CORS and single byte-range support, for local runs.

    python3 serve/serve_cors.py DIR [PORT]

Serves DIR on http://localhost:PORT (default 8096) with
Access-Control-Allow-Origin: * and Range: bytes=a-b handling (206 responses),
which is what a browser Zarr reader needs. Python's built-in http.server
ignores Range, so it is not enough on its own.

For local testing only. Use object storage with CORS for anything shared.
"""

import http.server
import os
import re
import sys

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".json": "application/json",
        "": "application/octet-stream",
    }

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Expose-Headers",
                         "Content-Range, Content-Length, Accept-Ranges, ETag")
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not rng or os.path.isdir(path) or not os.path.isfile(path):
            return super().send_head()
        m = RANGE_RE.match(rng.strip())
        size = os.path.getsize(path)
        if not m:
            return super().send_head()
        a, b = m.groups()
        if a == "":
            start, end = max(size - int(b), 0), size - 1
        else:
            start = int(a)
            end = min(int(b), size - 1) if b else size - 1
        if start >= size or start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None
        f = open(path, "rb")
        f.seek(start)
        self._remaining = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self._remaining))
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        remaining = getattr(self, "_remaining", None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        while remaining > 0:
            buf = source.read(min(65536, remaining))
            if not buf:
                break
            outputfile.write(buf)
            remaining -= len(buf)
        self._remaining = None


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    root = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8096
    os.chdir(root)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"serving {os.path.abspath(root)} on http://localhost:{port}/ (CORS, byte ranges)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
