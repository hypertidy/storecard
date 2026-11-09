"""Virtual twins of the local fixtures: the same metadata, chunks by reference.

Each builder takes a plain Zarr v3 fixture store and writes an index whose
chunk references point at the fixture's own chunk files (whole files, offset
0, or a given URL base and offset), as raad.virtualize writes indexes over
netCDF and TIFF sources:

- kerchunk_refs: kerchunk reference dict (Zarr v2 metadata), for JSON or
  Parquet. The fixtures' codecs are `bytes` + `zstd`, which in v2 is a
  `zstd` compressor over the same bytes, so the references decode.
- icechunk_repo: an Icechunk repository with the same v3 metadata and every
  chunk a virtual reference.
"""

import json
import os

import numpy as np


def _nodes(store):
    """[(path, zarr.json dict)] for every node below store, root first."""
    out = []
    for dirpath, dirnames, filenames in os.walk(store):
        dirnames.sort()
        if "zarr.json" in filenames:
            rel = os.path.relpath(dirpath, store)
            with open(os.path.join(dirpath, "zarr.json")) as fh:
                out.append(("" if rel == "." else rel.replace(os.sep, "/"), json.load(fh)))
    return out


def _chunks(store, path):
    """[(chunk index, file path)] for an array's written chunks."""
    base = os.path.join(store, path, "c") if path else os.path.join(store, "c")
    out = []
    if os.path.isfile(base):                      # a 0-d array: key "c"
        return [((), base)]
    for dirpath, _, filenames in os.walk(base):
        for f in filenames:
            full = os.path.join(dirpath, f)
            idx = tuple(int(p) for p in os.path.relpath(full, base).split(os.sep))
            out.append((idx, full))
    return sorted(out)


def _v2_array(doc):
    codecs = {c["name"]: c.get("configuration", {}) for c in doc.get("codecs", [])}
    assert set(codecs) <= {"bytes", "zstd"}, codecs
    dt = np.dtype(doc["data_type"])
    if dt.itemsize > 1:
        dt = dt.newbyteorder("<" if codecs.get("bytes", {}).get("endian", "little") == "little" else ">")
    comp = None
    if "zstd" in codecs:
        comp = {"id": "zstd", "level": codecs["zstd"].get("level", 0)}
    zarray = {
        "zarr_format": 2, "shape": doc["shape"],
        "chunks": doc["chunk_grid"]["configuration"]["chunk_shape"],
        "dtype": dt.str, "compressor": comp, "filters": None,
        "fill_value": doc["fill_value"], "order": "C", "dimension_separator": ".",
    }
    zattrs = dict(doc.get("attributes", {}))
    if doc.get("dimension_names"):
        zattrs["_ARRAY_DIMENSIONS"] = list(doc["dimension_names"])
    return zarray, zattrs


def kerchunk_refs(store, url_base=None, offset=0, only=None, filters=None):
    """Kerchunk references (version 1) for a v3 fixture store.

    Chunk references are absolute file paths. With url_base, the chunks of
    the arrays in `only` (all arrays if None) are referenced as url_base +
    the chunk's path in the store instead, at `offset` (for tests that look
    at the references, never the bytes). filters: v2 filters to declare on
    the arrays in `only`."""
    refs = {}
    for path, doc in _nodes(store):
        pre = f"{path}/" if path else ""
        if doc["node_type"] == "group":
            refs[pre + ".zgroup"] = json.dumps({"zarr_format": 2})
            refs[pre + ".zattrs"] = json.dumps(doc.get("attributes", {}))
            continue
        zarray, zattrs = _v2_array(doc)
        chosen = only is None or path in only
        moved = url_base is not None and chosen
        if chosen and filters:
            zarray["filters"] = filters
        refs[pre + ".zarray"] = json.dumps(zarray)
        refs[pre + ".zattrs"] = json.dumps(zattrs)
        for idx, full in _chunks(store, path):
            key = pre + (".".join(str(i) for i in idx) if idx else "0")
            size = os.path.getsize(full)
            if moved:
                loc = url_base.rstrip("/") + "/" + os.path.relpath(full, store).replace(os.sep, "/")
                refs[key] = [loc, offset, size]
            else:
                refs[key] = [os.path.abspath(full), 0, size]
    return {"version": 1, "refs": refs}


def write_kerchunk_json(store, out, **kw):
    with open(out, "w") as fh:
        json.dump(kerchunk_refs(store, **kw), fh)
    return out


def write_kerchunk_parquet(store, out, record_size=1000, **kw):
    import fsspec
    from fsspec.implementations.reference import LazyReferenceMapper

    refs = kerchunk_refs(store, **kw)["refs"]
    fs = fsspec.filesystem("file")
    os.makedirs(out, exist_ok=True)
    m = LazyReferenceMapper.create(out, fs=fs, record_size=record_size)
    for k, v in refs.items():
        m[k] = v.encode() if isinstance(v, str) else v
    m.flush()
    return out


def icechunk_repo(store, out):
    """An Icechunk repository over a v3 fixture store, every chunk virtual."""
    import asyncio

    import icechunk
    from zarr.core.buffer import cpu

    prefix = "file://" + os.path.abspath(store).rstrip("/") + "/"
    config = icechunk.RepositoryConfig.default()
    config.set_virtual_chunk_container(
        icechunk.VirtualChunkContainer(prefix, icechunk.local_filesystem_store(os.path.abspath(store))))
    repo = icechunk.Repository.create(
        icechunk.local_filesystem_storage(out), config=config,
        authorize_virtual_chunk_access={prefix: icechunk.Credentials.LocalFileSystemAccess()})
    session = repo.writable_session("main")
    st = session.store

    async def put(key, doc):
        await st.set(key, cpu.Buffer.from_bytes(json.dumps(doc).encode()))

    for path, doc in _nodes(store):
        asyncio.run(put(f"{path}/zarr.json" if path else "zarr.json", doc))
        if doc["node_type"] != "array":
            continue
        for idx, full in _chunks(store, path):
            key = (f"{path}/" if path else "") + "c" + "".join(f"/{i}" for i in idx)
            st.set_virtual_ref(key, "file://" + os.path.abspath(full),
                               offset=0, length=os.path.getsize(full))
    session.commit("virtual twin of " + os.path.basename(store))
    return out
