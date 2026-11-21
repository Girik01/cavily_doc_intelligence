"""Documents -> passages that carry a citable location.
   HTML: one passage per page section; the location is the section name (e.g. "Bands – EU"). No page numbers are invented.
   PDF : one or more passages per page; the location is the real page number."""
import re

from docint import cavli_html as H

PDF_MAX = 1100


def html_passages(src, html: str):
    s = html if isinstance(html, str) else html.decode("utf-8", "replace")
    H.CHUNKS.clear()
    if src["parser"] == "product":
        H.product_chunks(H.parse_product("C16QS", s))
    else:
        H.category_chunks(H.parse_category("LTE Cat 1bis", s))
    out = []
    for c in H.CHUNKS:
        body = c["text"].split("\n", 1)[1] if "\n" in c["text"] else c["text"]
        out.append(dict(location=c["section"], text=body.strip(), chunk_type=c["chunk_type"], local_id=c["id"]))
    H.CHUNKS.clear()
    return out


def _faq_passages(html):
    """Question/answer pairs that a web app ships inside its page data (not in the visible text): location = the question."""
    pairs, seen = re.findall(r'\\"question\\":\\"(.+?)\\",\\"answer\\":\\"(.+?)\\"\}', html, re.S), set()
    clean = lambda t: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t.replace("\\\\n", " ").replace('\\"', '"').replace("\\u0026", "&"))).strip()
    out = []
    for q, a in pairs:
        q, a = clean(q), clean(a)
        if q in seen or len(a) < 20:
            continue
        seen.add(q)
        out.append(dict(location=q[:90], text=f"Q: {q}\nA: {a}", chunk_type="faq", local_id=f"f{len(out) + 1}"))
    return out if len(out) >= 3 else []


def generic_html_passages(html):
    """Any web page: one passage per heading section; the location is the heading text (no page numbers are invented)."""
    faq = _faq_passages(html if isinstance(html, str) else html.decode("utf-8", "replace"))
    if faq:
        return faq
    from bs4 import BeautifulSoup
    s = BeautifulSoup(html, "html.parser")
    for t in s(["script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"]):
        t.decompose()
    root = s.find("main") or s.body or s
    secs, head, buf = [], "Introduction", []
    flush = lambda: secs.append((head, "\n".join(buf))) if buf else None
    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "tr", "pre"]):
        txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if not txt:
            continue
        if el.name in ("h1", "h2", "h3", "h4"):
            flush()
            head, buf = txt[:80], []
        elif not (el.name in ("p", "li") and el.find_parent(["li", "tr"])):
            buf.append(txt)
    flush()
    out = []
    for h, text in secs:
        parts, cur = [], ""
        for line in text.split("\n"):
            if cur and len(cur) + len(line) > 1400:
                parts.append(cur)
                cur = line
            else:
                cur = f"{cur}\n{line}".strip()
        if cur:
            parts.append(cur)
        parts = [x for x in parts if len(x) >= 25]
        for i, txt in enumerate(parts, 1):
            out.append(dict(location=h + (f" (part {i} of {len(parts)})" if len(parts) > 1 else ""), text=txt, chunk_type="web_section",
                            local_id=f"s{len(out) + 1}"))
    return out


def pdf_passages(path):
    from pypdf import PdfReader
    out = []
    for pno, page in enumerate(PdfReader(str(path)).pages, start=1):
        lines = [re.sub(r"[ \t]+", " ", l).strip() for l in (page.extract_text() or "").split("\n")]
        lines = [l for l in lines if l]
        parts, cur = [], ""
        for l in lines:
            if cur and len(cur) + len(l) > PDF_MAX:
                parts.append(cur)
                cur = l
            else:
                cur = f"{cur}\n{l}".strip()
        if cur:
            parts.append(cur)
        for i, txt in enumerate(parts, start=1):
            loc = f"page {pno}" + (f" (part {i} of {len(parts)})" if len(parts) > 1 else "")
            out.append(dict(location=loc, page=pno, text=txt, chunk_type="pdf_page", local_id=f"p{pno}.{i}"))
    return out


def spec_passages(path):
    """Layout-aware passages for the Canva-made spec PDFs: location = real page + the section name printed on the page."""
    from docint import pdf_tables
    out = []
    for s in pdf_tables.pdf_sections(path):
        text = s["text"]
        parts, cur = [], ""
        for line in text.split("\n"):
            if cur and len(cur) + len(line) > 1400:
                parts.append(cur)
                cur = line
            else:
                cur = f"{cur}\n{line}".strip()
        if cur:
            parts.append(cur)
        parts = [x for x in parts if len(x) >= 25]  # drop orphan headings / decorative one-word lines
        for i, txt in enumerate(parts, 1):
            loc = f"page {s['page']}" + (f", {s['section']}" if s["section"] else "") + (f" (part {i} of {len(parts)})" if len(parts) > 1 else "")
            out.append(dict(location=loc, page=s["page"], text=txt, chunk_type="spec_section", local_id=f"p{s['page']}.{i}"))
    return out


def _html_parser(doc):
    """Cavli's product and category pages have a known structure and a dedicated reader (section names like "Bands - EU");
    every other web page uses the generic heading-based reader."""
    u = doc.get("url", "")
    if "/iot-modules/c-series/" in u:
        return "product"
    if "/iot-modules/lte-" in u.lower():
        return "category"
    return "generic"


def passages_for(doc, version, root):
    """All passages of one stored version, with the metadata every citation needs."""
    path = root / version["file"]
    if doc["kind"] == "pdf":
        # long technical PDFs have tables that plain text extraction scrambles: use the layout-aware reader for them
        raw = None
        if (version.get("pdf") or {}).get("pages", 0) >= 5:
            try:
                raw = spec_passages(path) or None
            except Exception:
                raw = None
        raw = raw or pdf_passages(path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        kind = _html_parser(doc)
        raw = html_passages(dict(parser=kind), text) if kind in ("product", "category") else generic_html_passages(text)
    out = []
    title = doc["title"] + (f" ({version['label']})" if version.get("label") else "")
    for i, p in enumerate(raw, start=1):
        meta = dict(passage_id=f"{doc['doc_id']}@v{version['version']}#{i}", doc_id=doc["doc_id"], version=version["version"],
                    title=title, url=version.get("source_url", doc["url"]), doc_type=doc["doc_type"], revision=version.get("revision"),
                    published=version.get("published"), date_note=version.get("date_note"), host=version.get("host"),
                    provenance=version.get("provenance"), status=version["status"],
                    location=p["location"], page=p.get("page"), chunk_type=p["chunk_type"], sha256=version["sha256"][:12])
        header = f"[Document: {title} | Location: {p['location']}]"
        out.append(dict(**meta, text=p["text"], embed_text=f"{header}\n{p['text']}"))
    return out
