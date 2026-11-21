"""Adding documents and new versions. A document comes from a link or an uploaded PDF; a changed link or a newer upload becomes the next
version: the previous one is marked superseded (kept for audit), the new one is indexed and the review queue is refreshed."""
import hashlib, json, re

from docint import conflicts, config, fetch, index, retrieve


def add_upload(data, filename, doc_id=None, title=None, doc_type=None, label=None, step=print, refresh=True):
    """The user supplies a PDF file."""
    if not data.startswith(b"%PDF"):
        raise ValueError("only PDF files can be uploaded")
    return add_document(data, "pdf", f"uploaded file: {filename}", {}, doc_id, title, doc_type, label, step,
                        host="uploaded by the user", provenance="uploaded by the user (not downloaded from a public link)", refresh=refresh)


def add_link(url, doc_id=None, title=None, doc_type=None, label=None, step=print, refresh=True):
    """The user gives a link to a PDF or a web page. It is fetched now and fetched again on every 'Fetch again' run."""
    if not re.match(r"https?://", url or ""):
        raise ValueError("the link must start with http:// or https://")
    step("downloading the link")
    data, headers = fetch.download(url)
    kind = fetch.sniff_kind(data)
    return add_document(data, kind, url, headers, doc_id, title, doc_type, label, step, watch=url,
                        provenance="added by the user by link (public)", refresh=refresh)


def add_document(data, kind, url, headers, doc_id, title, doc_type, label, step, host=None, provenance="", watch=None, refresh=True):
    """Make `data` the next version of an existing document, or the first version of a new one: the previous current version is
    marked superseded and kept, the new one is indexed, and the review queue is refreshed."""
    inv = fetch.load_inventory()
    docs = {d["doc_id"]: d for d in inv["documents"]}
    sha = fetch.content_hash(data, kind)
    d = docs.get(doc_id) if doc_id else None
    if doc_id and d is None:
        raise ValueError("unknown document")
    if d is None and watch:
        d = next((x for x in inv["documents"] if x.get("watch_url") == watch or x["url"] == watch), None)
        doc_id = d["doc_id"] if d else None
    if d is None:
        if not (title or "").strip():
            raw = re.sub(r"\.pdf$", "", re.sub(r"^(https?://|uploaded file: )", "", url), flags=re.I).replace("_", " ")
            if url.startswith("uploaded file:"):
                raw = raw.replace("-", " ")
            stem = re.sub(r"(\s*\(\d+\))?([\s-]+[Vv]\d+(\.\d+)*)?(\s*\(\d+\))?\s*$", "", raw)[:80].strip()
            meta = fetch.page_title(data) if kind == "html" else fetch.pdf_facts_title(data)
            title = (stem if url.startswith("uploaded file:") else (meta or stem)) or "Added document"
        key = lambda t: re.sub(r"[^a-z0-9]+", "", t.lower())
        same_title = next((x for x in inv["documents"] if x["kind"] == kind and key(x["title"]) == key(title)), None)
        if same_title:       # never guess: the user says which document a file is a newer version of
            raise ValueError(f"a document called \"{same_title['title']}\" is already loaded. If this file is a newer version of it, use \"Add a newer version\" on that document. Otherwise give this file a different name.")
        doc_id = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "added-document"
        while doc_id in docs:
            doc_id += "-2"
    if d is not None:
        if d["kind"] != kind:
            raise ValueError(f"this is a {kind.upper()} but the document is a {d['kind'].upper()}")
        same = next((v for v in d["versions"] if v["sha256"] == sha), None)
        if same:
            raise ValueError(f"this is identical to version {same['version']} of this document, so there is nothing new to index")
    versions = d["versions"] if d else []
    n = max((v["version"] for v in versions), default=0) + 1
    label = (label or "").strip() or None
    rec = fetch.new_record(data, kind, url, doc_id, n, label, provenance, headers, host=host)
    step(f"saved as version {n}")
    prev = next((v for v in versions if v["status"] == "current"), None)
    if d is None:
        d = dict(doc_id=doc_id, title=title.strip(), url=url, doc_type=(doc_type or "").strip() or ("PDF document" if kind == "pdf" else "web page"),
                 kind=kind, parser="generic", module=fetch.config_module(), notes="Added by the user.", versions=[])
        if watch:
            d["watch_url"] = watch
        inv["documents"].append(d)
    if prev:
        prev["status"], prev["superseded_by"] = "superseded", n
    d["versions"].append(rec)
    fetch.save_inventory(inv)
    index.ensure_collection()
    if prev:
        index.set_status(doc_id, prev["version"], "superseded")
        step(f"version {prev['version']} marked superseded (kept for audit)")
    k = index.add_version(d, rec)
    step(f"indexed {k} passages")
    retrieve.reset_cache()
    new = []
    if refresh:
        step("comparing with the other versions and sources")
        items = conflicts.refresh_review_queue(step)
        new = [r for r in items if doc_id in r["doc_ids"] and r["type"] in ("revision_change", "conflict")]
    return dict(doc_id=doc_id, version=n, replaced=prev["version"] if prev else None, passages=k, review_items=len(new))


def remove_document(doc_id, step=print):
    """Stop using a document: its stored files, its passages in the index and its review items go."""
    from qdrant_client import models
    from docint import store
    inv = fetch.load_inventory()
    d = next((x for x in inv["documents"] if x["doc_id"] == doc_id), None)
    if d is None:
        raise ValueError("unknown document")
    index.ensure_collection()
    store.client().delete(config.COLLECTION, points_selector=models.FilterSelector(filter=models.Filter(must=[
        models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])))
    for v in d["versions"]:
        (config.ROOT / v["file"]).unlink(missing_ok=True)
    inv["documents"].remove(d)
    fetch.save_inventory(inv)
    retrieve.reset_cache()
    step("removed from the index")
    conflicts.refresh_review_queue()
