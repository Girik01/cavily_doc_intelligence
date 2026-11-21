"""Download public sources, keep every fetched version, and keep the inventory (title, URL, type, revision, hash)."""
import datetime, hashlib, json, re
from pathlib import Path

import requests
from pypdf import PdfReader

from docint import config

UA = {"User-Agent": "Mozilla/5.0 (compatible; cavli-doc-intelligence-poc/0.1)"}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def load_inventory():
    return json.loads(config.INVENTORY.read_text()) if config.INVENTORY.exists() else {"documents": [], "not_accessible": []}


def save_inventory(inv):
    config.INVENTORY.parent.mkdir(parents=True, exist_ok=True)
    config.INVENTORY.write_text(json.dumps(inv, indent=1, ensure_ascii=False))


def pdf_facts(path: Path):
    """Facts a PDF itself states: embedded metadata and (from the text) hardware/software version and date of issue."""
    r = PdfReader(str(path))
    meta = {k.lstrip("/"): str(v) for k, v in (r.metadata or {}).items()}
    text = "\n".join(p.extract_text() or "" for p in r.pages)
    hw = re.search(r"Hardware version:\s*(\S+)", text)
    sw = re.search(r"Software version:\s*(\S+)", text)
    date = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    return dict(pages=len(r.pages), pdf_metadata=meta, hardware_version=hw and hw.group(1), software_version=sw and sw.group(1),
                date_of_issue=date and date.group(1))


def content_hash(content: bytes, kind: str) -> str:
    """Hash of what a reader sees. Raw HTML changes on every request (build ids, tokens), so HTML is hashed on its
    visible text; a PDF is hashed on its bytes."""
    if kind == "pdf":
        return hashlib.sha256(content).hexdigest()
    from bs4 import BeautifulSoup
    s = BeautifulSoup(content, "html.parser")
    for t in s(["script", "style", "noscript", "svg"]):
        t.decompose()
    text = re.sub(r"\s+", " ", s.get_text(" ", strip=True))
    return hashlib.sha256(text.encode()).hexdigest()


def _iso(pdf_date):
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})", pdf_date or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _lm_date(h):
    import email.utils
    try:
        return email.utils.parsedate_to_datetime(h).date().isoformat() if h else None
    except Exception:
        return None


def ingest_inventory():
    """Fetch every document that was added by link again. A version is added only when its content hash is new; the previous
    current version becomes superseded (kept for audit). Uploaded files have no link and are not re-fetched."""
    inv = load_inventory()
    changes = []
    for d in inv["documents"]:
        if not d.get("watch_url"):
            continue
        try:
            content, headers = download(d["watch_url"])
        except Exception as e:
            changes.append((d["doc_id"], f"could not be fetched: {e}"))
            continue
        sha = content_hash(content, d["kind"])
        if any(v["sha256"] == sha for v in d["versions"]):
            changes.append((d["doc_id"], "unchanged"))
            continue
        n = max(v["version"] for v in d["versions"]) + 1
        rec = new_record(content, d["kind"], d["watch_url"], d["doc_id"], n, None, "added by the user by link", headers)
        for v in d["versions"]:
            if v["status"] == "current":
                v["status"], v["superseded_by"] = "superseded", n
        d["versions"].append(rec)
        changes.append((d["doc_id"], f"new version v{n}"))
    inv["generated_at"] = now()
    save_inventory(inv)
    return changes


def config_module():
    return "documents"


def download(url):
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    return r.content, dict(r.headers)


def sniff_kind(content):
    """pdf or html, decided from the bytes (never from the URL). Anything else is refused."""
    if content.startswith(b"%PDF"):
        return "pdf"
    if re.search(rb"<(html|body|head|!doctype html)", content[:5000], re.I):
        return "html"
    raise ValueError("this link is neither a PDF nor a web page")


def page_title(content):
    from bs4 import BeautifulSoup
    t = BeautifulSoup(content, "html.parser").find("title")
    return re.sub(r"\s+", " ", t.get_text()).strip() if t else ""


def new_record(content, kind, url, doc_id, n, label, provenance, headers, host=None, filename=None):
    """Store the file under data/versions and build the version record (title, URL, type, revision, dates, hash)."""
    ext = "pdf" if kind == "pdf" else "html"
    path = config.VERSIONS / f"{doc_id}.v{n}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    rec = dict(version=n, sha256=content_hash(content, kind), fetched_at=now(), file=str(path.relative_to(config.ROOT)), status="current",
               http_last_modified=headers.get("Last-Modified"), bytes=len(content), source_url=url,
               host=host or re.sub(r"^https?://([^/]+).*", r"\1", url), label=label, provenance=provenance)
    lm = _lm_date(headers.get("Last-Modified"))
    if kind == "pdf":
        pf = pdf_facts(path)
        rec["pdf"] = pf
        created = _iso(pf["pdf_metadata"].get("CreationDate"))
        if pf["hardware_version"]:
            rec["revision"] = f"hardware {pf['hardware_version']} / software {pf['software_version']}"
        elif label:
            rec["revision"] = f"{label} (label typed by the user; the PDF does not state a version)"
        else:
            rec["revision"] = None
        rec["published"] = pf["date_of_issue"]
        bits = ([f"PDF created {created}"] if created else []) + ([f"hosted copy last modified {lm}"] if lm else [])
        rec["date_note"] = "; ".join(bits) or None
    else:
        rec["revision"] = f"{label} (label typed by the user)" if label else None
        rec["published"] = None
        rec["date_note"] = f"web server says last modified {lm}" if lm else None
    return rec


def pdf_facts_title(data):
    import io
    try:
        return (PdfReader(io.BytesIO(data)).metadata or {}).get("/Title") or ""
    except Exception:
        return ""
