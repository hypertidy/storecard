"""The published cards, their index and the gallery drawn from it (offline)."""

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).parents[1]
INDEX = json.loads((ROOT / "cards" / "index.json").read_text())


def _load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_index_entries_point_at_cards():
    ids = [e["id"] for e in INDEX["entries"]]
    assert len(ids) == len(set(ids))
    for e in INDEX["entries"]:
        assert e["collection"] in INDEX["collections"]
        path = ROOT / e["card"]
        assert path.exists(), e["card"]
        if path.suffix == ".jsonl":
            cards = [json.loads(line) for line in path.read_text().splitlines() if line]
            assert len(cards) == e["n_files"] == len(e["files"])
        else:
            c = json.loads(path.read_text())
            assert c["source"]["url"] == e["url"]
            assert set(e["findings"]) == set(c["findings_summary"])


def test_every_card_file_is_indexed():
    files = {p.relative_to(ROOT).as_posix() for p in (ROOT / "cards").rglob("*.json*") if p.name != "index.json"}
    assert files == {e["card"] for e in INDEX["entries"]}


def test_indexed_assertions_exist_and_are_current():
    listed = set()
    for e in INDEX["entries"]:
        for a in e["assertions"]:
            assert (ROOT / a["path"]).exists()
            assert a["current"], (e["id"], a["path"])
            listed.add(a["path"])
    published = {p.relative_to(ROOT).as_posix() for p in (ROOT / "assertions").rglob("*.json")}
    assert listed == published


def test_gallery_renders_every_entry():
    g = _load(ROOT / "site" / "gallery.py")
    page = g.render(INDEX)
    for e in INDEX["entries"]:
        assert f'id="{e["id"]}"' in page
    assert page.isascii()
    meanings = g.finding_meanings()
    for e in INDEX["entries"]:
        for code in e["findings"]:
            assert code in meanings, code
