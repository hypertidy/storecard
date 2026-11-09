"""Store forms: plain Zarr, kerchunk references (JSON or Parquet), Icechunk.

Each form opens as a read-only zarr group, so the card is built the same way
from all of them. A virtual store (kerchunk, or Icechunk with virtual chunk
references) also says where its chunk bytes live; `chunk_locations` reads that
from the reference index alone, for a sample of chunks (the first and last of
each array for kerchunk, the first batch for Icechunk). It never reads a
chunk: listing every reference took 25 s to over 3 minutes on the
ausantarctic stores (37.5 million references for BRAN), and the sample is
enough to name the hosts.
"""

import asyncio
import json
import os
import urllib.parse

import zarr

ZARR = "zarr"
KERCHUNK_JSON = "kerchunk json"
KERCHUNK_PARQUET = "kerchunk parquet"
ICECHUNK = "icechunk"

# Icechunk chunk types, from IcechunkStore.array_chunk_iterator
_IC_VIRTUAL = 2
# chunks taken from the start of each Icechunk array's manifest
_IC_BATCH = 4


def _is_remote(url):
    return "://" in url and not url.startswith("file://")


def _local(url):
    return url[len("file://"):] if url.startswith("file://") else url


def _join(url, key):
    return url.rstrip("/") + "/" + key


def _remote_options(url, storage_options):
    so = dict(storage_options or {})
    if url.startswith(("http://", "https://")):
        # honour HTTPS_PROXY and friends, as urllib does for the host probe
        so.setdefault("client_kwargs", {}).setdefault("trust_env", True)
    return so


def _read(url, storage_options=None):
    """Bytes at url (path or URL), or None if it is not there."""
    try:
        if not _is_remote(url):
            p = _local(url)
            if not os.path.isfile(p):
                return None
            with open(p, "rb") as fh:
                return fh.read()
        import fsspec
        fs, path = fsspec.core.url_to_fs(url, **_remote_options(url, storage_options))
        return fs.cat_file(path)
    except Exception:
        return None


def detect(url, storage_options=None):
    """The form of the store at url, from the documents at its root.

    A URL ending .json is a kerchunk reference file. Otherwise an Icechunk
    repository has a `repo` object at its root (an array named "repo" in a
    plain store would be a prefix, not an object); a kerchunk Parquet store
    has a `.zmetadata` with a top-level `record_size`. Anything else is
    opened as plain Zarr."""
    if url.split("?")[0].endswith(".json"):
        return KERCHUNK_JSON, None
    if _read(_join(url, "repo"), storage_options) is not None:
        return ICECHUNK, None
    zm = _read(_join(url, ".zmetadata"), storage_options)
    if zm is not None:
        try:
            doc = json.loads(zm)
        except ValueError:
            doc = {}
        if isinstance(doc, dict) and "record_size" in doc:
            return KERCHUNK_PARQUET, doc
    return ZARR, None


# ---------------------------------------------------------------- codecs

# Placeholder codecs for names this environment has no implementation of.
# Zarr refuses to parse metadata naming a codec it cannot load, but a card
# never decodes a data chunk, so the codec chain is a fact to record, not a
# capability to have. A placeholder parses and keeps its configuration, and
# refuses to encode or decode. {name: kind index}
_STUBS = {}
# placeholder kinds for a Zarr v3 codec, tried in turn until the chain parses
# (an unknown codec before `bytes` is array-to-array, after it bytes-to-bytes)
_KINDS = ("array_array", "bytes_bytes", "array_bytes")
_UNKNOWN = __import__("re").compile(r"codec '([^']+)' is not available")


def unavailable_codecs():
    """Codec names given placeholders in this process, sorted."""
    return sorted(_STUBS)


def _refuse(*a, **kw):
    raise zarr.errors.UnknownCodecError(
        "storecard placeholder codec: this environment cannot decode it, and a card never needs to")


def _stub_v2(codec_id):
    import numcodecs
    from numcodecs.abc import Codec

    def init(self, **config):
        self._config = config

    def get_config(self):
        return {"id": self.codec_id, **self._config}

    cls = type(f"Unavailable_{codec_id}", (Codec,), {
        "codec_id": codec_id, "__init__": init, "get_config": get_config,
        "encode": _refuse, "decode": _refuse})
    numcodecs.register_codec(cls)


def _stub_v3(name, kind):
    import dataclasses
    from zarr.abc import codec as zc
    from zarr import registry

    base = {"array_array": zc.ArrayArrayCodec, "bytes_bytes": zc.BytesBytesCodec,
            "array_bytes": zc.ArrayBytesCodec}[kind]

    @dataclasses.dataclass(frozen=True)
    class Stub(base):
        configuration: dict = dataclasses.field(default_factory=dict)
        is_fixed_size = False

        @classmethod
        def from_dict(cls, data):
            return cls(configuration=dict(data.get("configuration") or {}))

        def to_dict(self):
            return {"name": name, "configuration": dict(self.configuration)}

        def compute_encoded_size(self, input_byte_length, chunk_spec):
            _refuse()

        async def _decode_single(self, *a):
            _refuse()

        async def _encode_single(self, *a):
            _refuse()

    Stub.__name__ = Stub.__qualname__ = f"Unavailable_{kind}"
    reg = registry._codec_registries[name]
    reg.clear()                 # a retry replaces the previous kind
    registry.register_codec(name, Stub, qualname=f"storecard.unavailable.{kind}")


def tolerant(fn, tries=12):
    """fn(), registering a placeholder for each codec zarr cannot load.

    For Zarr v3 a placeholder's kind (array-to-array, bytes-to-bytes,
    array-to-bytes) is unknown until the chain parses, so a chain that fails
    to parse after a placeholder is added moves that codec to the next kind."""
    last = None
    for _ in range(tries):
        try:
            return fn()
        except zarr.errors.UnknownCodecError as e:
            m = _UNKNOWN.search(str(e))
            if not m or m.group(1) in _STUBS:
                raise
            last = m.group(1)
            _STUBS[last] = 0
            _stub_v2(last)
            _stub_v3(last, _KINDS[0])
        except TypeError as e:
            # a placeholder of the wrong kind for its place in a v3 chain
            # (zarr: "Invalid codec order. ... Unavailable_<kind>(...)")
            if (last is None or "Invalid codec order" not in str(e)
                    or "Unavailable_" not in str(e) or _STUBS[last] + 1 >= len(_KINDS)):
                raise
            _STUBS[last] += 1
            _stub_v3(last, _KINDS[_STUBS[last]])
    return fn()


class Opened:
    """A store opened read-only: its root group and what its form adds."""

    def __init__(self, url, form, group, meta_key, source=None, refs=None, session=None):
        self.url, self.form, self.group, self.meta_key = url, form, group, meta_key
        self.source = source or {}
        self._refs, self._session = refs, session

    def chunk_locations(self, arrays):
        """{array path: [(location, offset), ...]} for a sample of each
        array's chunks that are references to bytes elsewhere. Inline and
        native chunks are not listed. Empty for plain Zarr."""
        if self.form in (KERCHUNK_JSON, KERCHUNK_PARQUET):
            return _kerchunk_locations(self._refs, arrays)
        if self.form == ICECHUNK:
            return _icechunk_locations(self._session, arrays)
        return {}


def open_store(url, storage_options=None, form=None):
    """Open url as its form (detected unless given) and return an Opened."""
    opened = tolerant(lambda: _open_store(url, storage_options, form))
    try:
        # list once here, so codecs named below the root get placeholders
        tolerant(lambda: list(opened.group.members(max_depth=None)))
    except zarr.errors.UnknownCodecError:
        raise
    except Exception:
        pass                    # an unlistable store; card() finds arrays from hints
    return opened


def _open_store(url, storage_options=None, form=None):
    pq = None
    if form is None:
        form, pq = detect(url, storage_options)
    if form == ICECHUNK:
        return _open_icechunk(url, storage_options)
    if form in (KERCHUNK_JSON, KERCHUNK_PARQUET):
        return _open_kerchunk(url, form, storage_options, pq)
    kw = {"mode": "r"}
    if _is_remote(url):
        kw["storage_options"] = _remote_options(url, storage_options)
    g = zarr.open_group(url, **kw)
    meta = "zarr.json" if g.metadata.zarr_format == 3 else ".zgroup"
    return Opened(url, ZARR, g, meta)


# ---------------------------------------------------------------- kerchunk

def _target_filesystems():
    """One async filesystem per protocol a reference may name.

    Given to ReferenceFileSystem as a dict so it does not scan every
    reference to find the protocols (which, for a lazy Parquet index, loads
    all of it). Only protocols whose fsspec implementation imports are
    included; a reference to any other fails when read, which a card only
    does for coordinate arrays."""
    import fsspec
    from fsspec.implementations.asyn_wrapper import AsyncFileSystemWrapper

    fss = {}
    http = fsspec.filesystem("https", asynchronous=True, client_kwargs={"trust_env": True})
    fss["https"] = fss["http"] = http
    try:
        fss["s3"] = fsspec.filesystem("s3", asynchronous=True, anon=True)
    except Exception:
        pass
    local = AsyncFileSystemWrapper(fsspec.filesystem("file"), asynchronous=True)
    fss["file"] = fss[None] = local
    return fss


def _open_kerchunk(url, form, storage_options, pq=None):
    import fsspec
    from fsspec.implementations.reference import LazyReferenceMapper, ReferenceFileSystem

    so = _remote_options(url, storage_options) if _is_remote(url) else {}
    source = {}
    if form == KERCHUNK_PARQUET:
        ref_fs, path = fsspec.core.url_to_fs(url if _is_remote(url) else _local(url), **so)
        refs = LazyReferenceMapper(path.rstrip("/"), fs=ref_fs)
        source["record_size"] = (pq or {}).get("record_size", refs.record_size)
    else:
        with fsspec.open(url if _is_remote(url) else _local(url), "rb", **so) as fh:
            doc = json.load(fh)
        source["refs_version"] = doc.get("version", 0)
        refs = doc
    rfs = ReferenceFileSystem(refs, fs=_target_filesystems(), asynchronous=True)
    store = zarr.storage.FsspecStore(rfs, read_only=True, path="")
    g = zarr.open_group(store, mode="r", zarr_format=2)
    meta = ".zmetadata" if form == KERCHUNK_PARQUET else ""
    return Opened(url, form, g, meta, source, refs=rfs.references)


def _chunk_key(arr, idx):
    md = arr.metadata.to_dict()
    sep = md.get("dimension_separator") or "."
    return sep.join(str(i) for i in idx) if idx else "0"


def _kerchunk_locations(refs, arrays):
    out = {}
    for path, arr in arrays.items():
        grid = [-(-s // c) if c else 1 for s, c in zip(arr.shape, arr.chunks)]
        if any(n == 0 for n in grid):
            continue
        first = [0] * arr.ndim
        last = [n - 1 for n in grid]
        locs = []
        for idx in (first, last) if last != first else (first,):
            try:
                ref = refs[f"{path}/{_chunk_key(arr, idx)}"]
            except Exception:
                continue          # not written: the chunk is all fill
            if isinstance(ref, (list, tuple)) and ref and isinstance(ref[0], str):
                loc = (ref[0], int(ref[1]) if len(ref) > 1 else 0)
                if loc not in locs:
                    locs.append(loc)
        if locs:
            out[path] = locs
    return out


# ---------------------------------------------------------------- icechunk

def _icechunk_storage(url, storage_options):
    import icechunk

    so = storage_options or {}
    parts = urllib.parse.urlsplit(url)
    if parts.scheme in ("http", "https"):
        return icechunk.http_storage(url)
    if parts.scheme == "s3":
        ck = so.get("client_kwargs", {})
        return icechunk.s3_storage(bucket=parts.netloc, prefix=parts.path.strip("/"),
                                   anonymous=bool(so.get("anon")),
                                   endpoint_url=ck.get("endpoint_url"),
                                   region=ck.get("region_name"))
    return icechunk.local_filesystem_storage(_local(url))


def _anonymous(prefix):
    """Anonymous credentials for a virtual chunk container, by its scheme."""
    import icechunk

    scheme = urllib.parse.urlsplit(prefix).scheme
    if scheme in ("http", "https"):
        return icechunk.Credentials.HttpAccess()
    if scheme == "file":
        return icechunk.Credentials.LocalFileSystemAccess()
    if scheme in ("s3", "r2", "tigris"):
        return icechunk.s3_anonymous_credentials()
    return None                 # icechunk's default, deprecated for the schemes above


def _open_icechunk(url, storage_options, branch="main"):
    import icechunk

    storage = _icechunk_storage(url, storage_options)
    repo = icechunk.Repository.open(storage)
    containers = sorted((repo.config.virtual_chunk_containers or {}).keys())
    if containers:
        # anonymous read of each declared container, so coordinate arrays held
        # as virtual references can be read; data chunks are never read
        repo = icechunk.Repository.open(
            storage, authorize_virtual_chunk_access={c: _anonymous(c) for c in containers})
    session = repo.readonly_session(branch=branch)
    g = zarr.open_group(session.store, mode="r", zarr_format=3)
    source = {"branch": branch, "snapshot": session.snapshot_id,
              "virtual_chunk_containers": containers}
    return Opened(url, ICECHUNK, g, "repo", source, session=session)


async def _first_batch(store, path, n=_IC_BATCH):
    it = store.array_chunk_iterator(path, batch_size=n)
    try:
        async for batch in it:
            return batch
    finally:
        r = it.close() if hasattr(it, "close") else None
        if asyncio.iscoroutine(r):
            await r
    return None


def _icechunk_locations(session, arrays):
    out = {}
    for path in arrays:
        try:
            batch = asyncio.run(_first_batch(session.store, "/" + path.lstrip("/")))
        except Exception:
            continue
        if not batch:
            continue
        types, locations, offsets = batch[1], batch[2], batch[3]
        locs = []
        for t, loc, off in zip(types, locations, offsets):
            if int(t) == _IC_VIRTUAL and loc and (loc, int(off)) not in locs:
                locs.append((loc, int(off)))
        if locs:
            out[path] = locs
    return out


# ---------------------------------------------------------------- hosts

def host_of(location):
    """(scheme, netloc) of a chunk location; ("file", "") for a bare path."""
    p = urllib.parse.urlsplit(location)
    if not p.scheme or len(p.scheme) == 1:      # a path, or a Windows drive letter
        return "file", ""
    return p.scheme, p.netloc
