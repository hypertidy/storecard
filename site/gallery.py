"""Draw the card gallery from cards/index.json; run before quarto render.

Writes site/_gallery.qmd, a raw HTML block that index.qmd includes, and
copies cards/ and assertions/ into site/ so the gallery can link to the
JSON it was drawn from. Standard library only: no network, no GDAL. The
index is written by cards/build.py.

    python3 site/gallery.py && quarto render site
"""

import html
import json
import pathlib
import re
import shutil

SITE = pathlib.Path(__file__).parent
ROOT = SITE.parent
REPO = "https://github.com/hypertidy/storecard/blob/main/"

# fixture id prefix: demos that draw it
DEMOS = {
    "costumes.html": ("Five costumes, one grid", ["f03a", "f03c", "f03d", "f03e", "f03f"]),
    "index.html": ("One assertion, end to end", ["f03d", "f03e"]),
    "tripolar.html": ("An honest refusal", ["f08c"]),
    "packing.html": ("The numbers are not the values", ["f01b", "f01e"]),
    "fill.html": ("Which cells are missing?", ["f01b", "f01f", "f08b"]),
}

COSTUME = {
    "A": "no coordinates, no transform",
    "B": "transform and CRS declared",
    "C": "regular 1-D axes",
    "D": "latitude spaced in Mercator",
    "E": "2-D longitude and latitude hiding a regular grid",
    "F": "2-D projected x/y arrays",
    "G": "1-D axes, at least one irregular",
    "H": "2-D longitude and latitude, honestly curvilinear",
}


def esc(x):
    return html.escape(str(x), quote=True)


def finding_meanings():
    out = {}
    for line in (ROOT / "FINDINGS.md").read_text().splitlines():
        m = re.match(r"\| `([A-Z0-9_]+)` \| (.*?) \|", line)
        if m:
            out[m.group(1)] = re.sub(r"`", "", m.group(2))
    return out


def num(x):
    """A transform term without float noise it does not have."""
    return repr(int(x)) if float(x).is_integer() else repr(x)


def grid_line(e):
    g = e.get("grid") or {}
    shape = e.get("spatial_shape")
    parts = []
    if shape:
        parts.append(f"{shape[0]} x {shape[1]}")
    t = g.get("transform")
    if t:
        parts.append("transform [" + ", ".join(num(x) for x in t) + "]")
    else:
        form = {"coords_1d_regular": "regular 1-D axes", "coords_1d_irregular": "irregular 1-D axes",
                "coords_2d": "2-D longitude and latitude only", "coords_named_missing": "coordinates named but missing",
                "none": "no coordinates"}.get(g.get("form"), g.get("form"))
        if form:
            parts.append(form)
    return ", ".join(parts)


def crs_line(e):
    c = e.get("crs") or {}
    labels = "; ".join(c.get("labels") or [])
    if c.get("declared"):
        return esc(labels)
    return '<span class="sc-warn">not declared</span>' + (f" ({esc(labels)})" if labels else "")


def hosts_line(e):
    out = []
    for h in e.get("hosts") or []:
        role = "" if h.get("role") == "metadata" else f" ({esc(h.get('role'))})"
        if not h.get("probed", True):
            state = '<span class="sc-unknown">not probed: host unreachable from the build</span>'
        else:
            state = "CORS " + esc(h["cors"]) if h.get("cors") else '<span class="sc-warn">no CORS</span>'
            state += "" if h.get("range") else ", no ranges"
        out.append(f"<code>{esc(h['host'])}</code>{role}: {state}")
    return "<br>".join(out)


def chips(findings, meanings, total=None):
    if not findings:
        return '<span class="sc-none">no findings</span>'
    out = []
    for code, n in findings.items():
        count = f' <span class="sc-n">{n}/{total}</span>' if total and total > 1 else ""
        out.append(f'<span class="sc-chip" title="{esc(meanings.get(code, ""))}">{esc(code)}{count}</span>')
    return " ".join(out)


def assertion_block(e):
    rows = []
    cleared = (e.get("asserted") or {})
    for a in e.get("assertions") or []:
        what = a["kind"]
        if a["kind"] == "grid":
            what = "grid: " + (a.get("asserts") or {}).get("proj:code", "transform")
        state = a.get("status") or ""
        state += ", digest current" if a.get("current") else ", <span class='sc-warn'>digest stale</span>"
        var = f" on <code>{esc(a['variable'])}</code>" if a.get("variable") else ""
        rows.append(f'<li><a href="{esc(a["path"])}">{esc(what)}</a>{var} ({state})</li>')
    if not rows:
        t = e.get("tidy")
        if t:
            codes = ", ".join(t["codes"]) or "the declared CRS"
            return (f'<div class="sc-assert sc-tidy"><b>Tidy assertion available</b> for {t["files"]} of '
                    f'{e.get("n_files", 1)} files: restates the declarations exactly as {esc(codes)} on round origins, '
                    f'clearing {" ".join("<code>" + esc(c) + "</code>" for c in t["clears"])}. '
                    f'Computed by <code>cog.tidy_assertion</code>, not yet published.</div>')
        return ""
    tail = ""
    if cleared.get("clears"):
        bits = []
        for code, n in cleared["clears"].items():
            part = "" if n["cleared"] == n["of"] else f" on {n['cleared']} of {n['of']} arrays"
            bits.append(f"<code>{esc(code)}</code>{part}")
        tail = "Applied, clears " + ", ".join(bits)
        if cleared.get("costumes") and cleared["costumes"] != e.get("costumes"):
            tail += (f'; costume {esc(", ".join(e.get("costumes") or []))} becomes '
                     f'{esc(", ".join(cleared["costumes"]))}')
        tail = f"<p>{tail}.</p>"
    head = "Assertion" if len(rows) == 1 else f"{len(rows)} assertions"
    return f'<div class="sc-assert"><b>{head}</b><ul>{"".join(rows)}</ul>{tail}</div>'


def files_block(e):
    files = e.get("files") or []
    if len(files) < 2:
        return ""
    rows = []
    for f in files:
        name = f["url"].rsplit("/", 1)[-1]
        s = f["spatial_shape"]
        origin = f"{num(f['transform'][2])}, {num(f['transform'][5])}" if f.get("transform") else ""
        rows.append(f'<tr><td><a href="{esc(f["url"])}">{esc(name)}</a></td><td>{s[0]} x {s[1]}</td>'
                    f'<td>{esc(origin)}</td><td>{esc(f["crs"])}</td><td>{esc(" ".join(f["findings"]))}</td></tr>')
    return (f'<details><summary>{len(files)} files</summary><div class="sc-files"><table>'
            '<thead><tr><th>File</th><th>Rows x cols</th><th>Origin</th><th>CRS</th><th>Findings</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></details>')


def entry(e, meanings):
    costumes = e.get("costumes") or []
    badge = "".join(
        f'<span class="sc-costume" title="costume {esc(c.replace("/", " or "))}: '
        f'{esc("; or ".join(COSTUME.get(x, x) for x in c.split("/")))}">{esc(c)}</span>' for c in costumes)
    demos = [f'<a href="demo/{d}">{esc(t)}</a>' for d, (t, ids) in DEMOS.items()
             if e["collection"] == "portolan" and e["id"][:4] in ids]
    links = [f'<a href="{esc(e["card"])}">card JSON</a>', f'<a href="{esc(e["url"])}">store</a>']
    if e.get("stac"):
        links.append(f'<a href="{esc(e["stac"])}">STAC</a>')
    n = e.get("n_files", 1)
    dtype = e.get("dtype")
    dtype = ", ".join(dtype) if isinstance(dtype, list) else dtype
    names = e.get("variables") or []
    vars_ = ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")
    rows = []
    if grid_line(e):
        rows.append(("Grid", esc(grid_line(e))))
    rows.append(("CRS", crs_line(e)))
    rows.append(("Arrays", f"{esc(vars_)} ({esc(dtype)})"))
    rows.append(("Hosts", hosts_line(e)))
    facts = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    search = " ".join([e["id"], e["form"], " ".join(e["findings"]), " ".join((e.get("crs") or {}).get("labels", [])),
                       " ".join(names)]).lower()
    return f'''<article class="sc-card" id="{esc(e["id"])}" data-form="{esc(e["form"])}"
 data-findings="{esc(" ".join(e["findings"]))}" data-asserted="{1 if e.get("assertions") else 0}"
 data-search="{esc(search)}">
<header><h3><a href="#{esc(e["id"])}">{esc(e["id"])}</a></h3>
<span class="sc-form">{esc(e["form"])}{f" x {n}" if n > 1 else ""}</span>{badge}</header>
<dl>{facts}</dl>
<div class="sc-findings">{chips(e["findings"], meanings, n)}</div>
{assertion_block(e)}
{files_block(e)}
<footer>{" | ".join(links)}{"<br>Demo: " + ", ".join(demos) if demos else ""}</footer>
</article>'''


SCRIPT = """
<script>
(function () {
  var q = document.getElementById('sc-q'), form = document.getElementById('sc-form'),
      code = document.getElementById('sc-code'), asserted = document.getElementById('sc-asserted'),
      count = document.getElementById('sc-count');
  var cards = Array.prototype.slice.call(document.querySelectorAll('.sc-card'));
  function apply() {
    var words = q.value.toLowerCase().split(/\\s+/).filter(Boolean), shown = 0;
    cards.forEach(function (c) {
      var ok = words.every(function (w) { return c.dataset.search.indexOf(w) >= 0; })
        && (!form.value || c.dataset.form === form.value)
        && (!code.value || (' ' + c.dataset.findings + ' ').indexOf(' ' + code.value + ' ') >= 0)
        && (!asserted.checked || c.dataset.asserted === '1');
      c.hidden = !ok;
      if (ok) shown++;
    });
    document.querySelectorAll('.sc-collection').forEach(function (s) {
      s.hidden = !s.querySelector('.sc-card:not([hidden])');
    });
    count.textContent = shown + ' of ' + cards.length + ' entries';
  }
  [q, form, code, asserted].forEach(function (el) { el.addEventListener('input', apply); });
  apply();
})();
</script>
"""


def render(index):
    meanings = finding_meanings()
    entries = index["entries"]
    forms = sorted({e["form"] for e in entries})
    codes = sorted({c for e in entries for c in e["findings"]})
    n_cards = sum(e.get("n_files", 1) for e in entries)
    n_asserted = sum(1 for e in entries if e.get("assertions"))
    out = [f'''<div class="sc-gallery">
<p class="sc-lede">{len(entries)} entries, {n_cards} cards, {n_asserted} stores with a published assertion.
Every fact below was read from metadata; hover a finding or a costume letter for its meaning.</p>
<div class="sc-filter">
<input id="sc-q" type="search" placeholder="Filter: name, CRS, variable, finding" aria-label="Filter cards">
<select id="sc-form" aria-label="Form"><option value="">any form</option>{"".join(f"<option>{esc(f)}</option>" for f in forms)}</select>
<select id="sc-code" aria-label="Finding"><option value="">any finding</option>{"".join(f"<option>{esc(c)}</option>" for c in codes)}</select>
<label><input id="sc-asserted" type="checkbox"> has an assertion</label>
<span id="sc-count"></span>
</div>''']
    for key, col in index["collections"].items():
        mine = [e for e in entries if e["collection"] == key]
        if not mine:
            continue
        out.append(f'<section class="sc-collection"><h2 id="{esc(key)}">{esc(col["title"])}</h2>'
                   f'<p>{esc(col["about"])} <a href="{esc(col["home"])}">Source</a>. '
                   f'{len(mine)} entries.</p><div class="sc-grid">')
        out.extend(entry(e, meanings) for e in mine)
        out.append("</div></section>")
    out.append("</div>")
    out.append(SCRIPT)
    return "\n".join(out)


def main():
    index = json.loads((ROOT / "cards" / "index.json").read_text())
    (SITE / "_gallery.qmd").write_text("```{=html}\n" + render(index) + "\n```\n")
    for name in ("cards", "assertions"):
        dst = SITE / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(ROOT / name, dst, ignore=shutil.ignore_patterns("*.py", "__pycache__", "keys.txt"))


if __name__ == "__main__":
    main()
