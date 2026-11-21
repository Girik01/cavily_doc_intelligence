"""Layout-aware reading of Cavli's Canva-made spec PDFs. Plain text extraction scrambles their tables (labels, values and
region columns come out in separate runs), so rows and columns are rebuilt from word positions.
  - column pages (header row C16QS-EA | C16QS-NA | ...): rows = left label, cells go to the nearest header column
  - other pages: words on one line are joined; big horizontal gaps become ' | '; bold 12 pt lines are section headings
Footnote icons (5 pt digits) are dropped: they mark Optional / Needs SDK / In Progress and cannot be attributed to a cell,
so a legend line says so instead."""
import re
from collections import defaultdict

import pymupdf

SMALL = 5.5
HEAD = re.compile(r"^C16QS-[A-Z]{2,3}$")
LEGEND = "(Legend on the page: footnote icons 1 = Optional, 2 = Needs SDK / not available currently, 3 = In Progress; the icons are not attributed to single cells here.)"
MAXLEN = 1400


def _words(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                heavy = "Heavy" in s["font"] or "Bold" in s["font"]
                if not s["text"].strip() or (s["size"] < SMALL and not heavy):   # drops 5 pt footnote icons, keeps small bold labels
                    continue
                x0, y0, x1, y1 = s["bbox"]
                out.append(dict(x0=x0, x1=x1, y=(y0 + y1) / 2, text=s["text"].strip(),
                                heavy=heavy, size=s["size"]))
    return out


def _lines(ws, tol=4):
    ws = sorted(ws, key=lambda w: (w["y"], w["x0"]))
    lines = []
    for w in ws:
        if lines and abs(lines[-1]["y"] - w["y"]) <= tol:
            lines[-1]["w"].append(w)
        else:
            lines.append(dict(y=w["y"], w=[w]))
    for l in lines:
        l["w"].sort(key=lambda w: w["x0"])
    return lines


def _join(ws, gap=22):
    out, last = "", None
    for w in ws:
        out += (" | " if last is not None and w["x0"] - last > gap else (" " if out else "")) + w["text"]
        last = w["x1"]
    return out


RENAME = {"C16QS IOT Module": "Independent operation of GNSS and cellular (diagram)"}


def _heading(ws):
    """A bold line of 10 pt or more at section-heading length (not the decorative title 'C16QS')."""
    if not ws or not all(w["heavy"] and w["size"] >= 9.5 for w in ws) or len(ws) > 5:
        return None
    txt = " ".join(w["text"] for w in ws)
    if len(txt) < 6 or txt == "C16QS":
        return None
    return "Product Variants" if txt.startswith("Features") or txt.startswith("Product Variants") else RENAME.get(txt, txt)


def _is_legend(txt):
    return txt.startswith("Optional") and "Needs SDK" in txt


def page_sections(page, carry=""):
    """-> (kind, [(section, text)])"""
    ws = _words(page)
    heads = [w for w in ws if HEAD.match(w["text"]) and w["size"] >= 12]
    return ("columns", _column_sections(ws, heads, carry)) if len(heads) >= 3 else ("lines", _line_sections(ws, carry))


def _line_sections(ws, carry):
    secs, cur, buf = [], carry, []
    for l in _lines(ws):
        txt = _join(l["w"])
        h = _heading(l["w"])
        if h:
            if buf:
                secs.append((cur, buf))
            cur, buf = h, []
        elif _is_legend(txt):
            buf.append(LEGEND)
        else:
            buf.append(txt)
    if buf:
        secs.append((cur, buf))
    return [(s, "\n".join(b)) for s, b in secs]


def _column_sections(ws, heads, carry):
    heads = sorted(heads, key=lambda h: h["x0"])
    names = [h["text"].replace("C16QS-", "") for h in heads]
    centers = [(h["x0"] + h["x1"]) / 2 for h in heads]
    label_max = heads[0]["x0"] - 30
    hy = max(h["y"] for h in heads)
    body = [w for w in ws if w["y"] > hy + 3]
    labels = [w for w in body if w["x1"] <= label_max + 5]
    cells = [w for w in body if w["x0"] > label_max]
    region_desc = defaultdict(list)       # bold small text right under the header: what each column's region covers
    for w in list(cells):
        if w["heavy"] and w["size"] < 11:
            region_desc[min(range(len(centers)), key=lambda i: abs((w["x0"] + w["x1"]) / 2 - centers[i]))].append(w)
            cells.remove(w)
    rows, section = [], carry
    for l in _lines(labels, tol=5):
        txt = " ".join(w["text"] for w in l["w"])
        if _heading(l["w"]) or all(w["heavy"] for w in l["w"]):
            section = _heading(l["w"]) or txt
            rows.append(dict(kind="section", y=l["y"], label=section))
        else:
            rows.append(dict(kind="row", y=l["y"], label=txt, section=section))
    labrows = [r for r in rows if r["kind"] == "row"]
    byrow = defaultdict(lambda: defaultdict(list))
    for w in cells:
        if labrows:
            col = min(range(len(centers)), key=lambda i: abs((w["x0"] + w["x1"]) / 2 - centers[i]))
            r = min(labrows, key=lambda r: abs(r["y"] - w["y"]))
            byrow[id(r)][col].append(w)
    secs, cur, buf = [], carry, []
    if region_desc:
        buf.append("Region covered | " + " | ".join(f"{names[i]}: " + " ".join(w["text"] for w in sorted(v, key=lambda w: (round(w['y'] / 4), w['x0']))) for i, v in sorted(region_desc.items())))
        cur = "Variant regions"
    for r in rows:
        if r["kind"] == "section":
            if buf:
                secs.append((cur, buf))
            cur, buf = r["label"], []
            continue
        cols = byrow.get(id(r), {})
        parts = [f"{names[i]}: " + " ".join(w["text"] for w in sorted(cols[i], key=lambda w: (round(w["y"] / 4), w["x0"]))) for i in range(len(names)) if i in cols]
        line = f"{r['label']} | " + " | ".join(parts)
        buf.append(LEGEND if _is_legend(line.replace(":", "")) else line)
    if buf:
        secs.append((cur, buf))
    return [(s, "\n".join(b)) for s, b in secs]


def pdf_sections(path):
    """[{page, section, text}] for a whole PDF; a section that continues on the next page keeps its name."""
    doc = pymupdf.open(str(path))
    out, carry = [], ""
    for pno, page in enumerate(doc, 1):
        _, parts = page_sections(page, carry)
        for sec, text in parts:
            if text.strip():
                out.append(dict(page=pno, section=sec, text=text))
        if parts:
            carry = parts[-1][0] or carry
    return out
