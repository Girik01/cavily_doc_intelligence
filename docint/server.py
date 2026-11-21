"""Web interface for the C16QS documentation-intelligence pipeline. Start it with `uv run main.py` (http://127.0.0.1:8002).
It is a thin layer over the same modules the CLI uses: fetch (ingest), index, retrieve/answer, revision, conflicts, eval."""
import json
import re
import threading
import time
import traceback
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from docint import answer, config, conflicts, fetch, index, retrieve, revision

app = FastAPI(title="Cavli C16QS documentation intelligence")
STATIC = Path(__file__).resolve().parent / "static"
LOG = config.DATA / "revision_log.json"
GEN = config.DATA / "eval_generated.json"

# ---- one background job at a time (process, re-index, evaluation); the page polls /api/job ----
JOB = dict(name=None, state="idle", steps=[], error=None, started=None, finished=None)
_lock = threading.Lock()


def _start(name, fn):
    with _lock:
        if JOB["state"] == "running":
            raise HTTPException(409, f"'{JOB['name']}' is still running")
        JOB.update(name=name, state="running", steps=[], error=None, started=time.time(), finished=None)

    def step(msg):
        JOB["steps"].append(msg)

    def run():
        try:
            fn(step)
            JOB["state"] = "done"
        except Exception as e:
            traceback.print_exc()
            JOB.update(state="failed", error=str(e))
        JOB["finished"] = time.time()

    threading.Thread(target=run, daemon=True).start()
    return JOB


def _fresh_index(step):
    step("embedding every stored version into Qdrant")
    n = index.index_all()
    retrieve.reset_cache()
    step(f"indexed {n} passages")
    return n


def _log(kind, text):
    rows = json.loads(LOG.read_text()) if LOG.exists() else []
    rows.append(dict(at=fetch.now(), kind=kind, text=text))
    LOG.write_text(json.dumps(rows[-40:], indent=1, ensure_ascii=False))


@app.get("/api/job")
def job():
    return dict(JOB, seconds=round((JOB["finished"] or time.time()) - JOB["started"]) if JOB["started"] else 0)


# ---- 1. sources ----
def _counts():
    try:
        docs, _ = retrieve._load()
    except Exception:
        return {}
    c = {}
    for d in docs:
        c[(d["doc_id"], d["version"])] = c.get((d["doc_id"], d["version"]), 0) + 1
    return c


@app.get("/api/state")
def state():
    inv = fetch.load_inventory() if config.INVENTORY.exists() else dict(documents=[], not_accessible=[])
    counts = _counts()
    docs = []
    for d in inv["documents"]:
        vs = [dict(version=v["version"], status=v["status"], label=v.get("label"), revision=v.get("revision"), published=v.get("published"),
                   date_note=v.get("date_note"), host=v.get("host"), source_url=v.get("source_url"), sha256=v["sha256"][:12],
                   fetched_at=v["fetched_at"], pages=(v.get("pdf") or {}).get("pages"), passages=counts.get((d["doc_id"], v["version"]), 0),
                   provenance=v.get("provenance")) for v in d["versions"]]
        docs.append(dict(doc_id=d["doc_id"], title=d["title"], doc_type=d["doc_type"], kind=d.get("kind"), url=d["url"], notes=d.get("notes"), watch=bool(d.get("watch_url")), versions=vs))
    return dict(documents=docs, not_accessible=inv.get("not_accessible", []), indexed=sum(counts.values()) if docs else 0,
                models=dict(chat=config.CHAT_MODEL, embeddings=config.EMBED_MODEL))


@app.post("/api/ingest")
def ingest():
    """Repeat the pipeline for what is loaded: fetch every link again, version by content hash, embed everything, refresh the review queue."""
    def go(step):
        step("fetching every link again and comparing content hashes")
        for sid, status in fetch.ingest_inventory():
            step(f"{sid}: {status}")
        _fresh_index(step)
        step("checking the documents against each other")
        n = len(conflicts.refresh_review_queue(step))
        step(f"{n} item(s) in the expert review queue")
    return _start("Fetch again and re-index", go)


@app.post("/api/sources/process")
async def process(files: list[UploadFile] = File(default=[]), links: str = Form(""), label: str = Form("")):
    """The start of the flow: the links and PDFs the user supplies are fetched, versioned, chunked and indexed, then compared."""
    urls = [l.strip() for l in links.splitlines() if l.strip()]
    blobs = [(f.filename or "upload.pdf", await f.read()) for f in files]
    if not urls and not blobs:
        raise HTTPException(400, "add at least one link or one PDF")
    bad = [u for u in urls if not re.match(r"https?://", u)] + [n for n, d in blobs if not d.startswith(b"%PDF")]
    if bad:
        raise HTTPException(400, "links must start with http:// or https://, and files must be PDFs: " + ", ".join(bad[:3]))

    def go(step):
        added = 0
        for u in urls:
            step(f"link: {u[:90]}")
            try:
                r = revision.add_link(u, label=label, step=lambda m: step("  " + m) if m.startswith("same title") else None, refresh=False)
                step(f"  indexed {r['passages']} passages")
                added += 1
            except Exception as e:
                step(f"  skipped: {e}")
        for name, data in blobs:
            step(f"file: {name}")
            try:
                r = revision.add_upload(data, name, None, "", "", label, step=lambda m: step("  " + m) if m.startswith("same title") else None, refresh=False)
                step(f"  indexed {r['passages']} passages")
                added += 1
            except Exception as e:
                step(f"  skipped: {e}")
        if added:
            step("checking the documents against each other (conflicts, changes)")
            n = len(conflicts.refresh_review_queue(step))
            step(f"{n} item(s) in the expert review queue")
            _log("process", f"Processed {added} source(s): {len(urls)} link(s), {len(blobs)} file(s).")
        else:
            raise RuntimeError("nothing could be added (see the steps above)")
    return _start("Process the sources", go)


class NA(BaseModel):
    items: list[dict]


@app.post("/api/not-accessible")
def not_accessible(n: NA):
    """Optional: documents the user knows exist but cannot access. They are named in 'not verified' answers."""
    inv = fetch.load_inventory()
    inv["not_accessible"] = [dict(title=str(i.get("title", "")).strip(), reason=str(i.get("reason", "")).strip()) for i in n.items if str(i.get("title", "")).strip()]
    fetch.save_inventory(inv)
    return inv["not_accessible"]


# ---- 2. ask ----
class Ask(BaseModel):
    question: str
    mode: str = "hybrid"
    include_superseded: bool = False


@app.post("/api/ask")
def ask(a: Ask):
    q = a.question.strip()
    if not q:
        raise HTTPException(400, "type a question")
    if len(q) > 500:
        raise HTTPException(400, "question is limited to 500 characters")
    if a.mode not in ("dense", "keyword", "hybrid"):
        raise HTTPException(400, "unknown retrieval mode")
    if not fetch.load_inventory()["documents"]:
        raise HTTPException(400, "Add sources first (Sources tab), then ask.")
    try:
        inc = ("current", "superseded") if a.include_superseded else ("current",)
        r = answer.ask(q, mode=a.mode, include=inc)
        conflicts.mark_asked(r.get("review_items") or [], q)
        return r
    except Exception as e:
        raise HTTPException(500, f"could not answer: {e}")


# ---- 3. revisions (the V2.0 -> V2.9 revision is real; its arrival is simulated and labelled as such) ----
@app.get("/api/revision")
def revision_state():
    q = json.loads(config.REVIEW_QUEUE.read_text()) if config.REVIEW_QUEUE.exists() else []
    return dict(changes=[r for r in q if r["type"] == "revision_change"],
                log=json.loads(LOG.read_text()) if LOG.exists() else [])


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), doc_id: str = Form(""), title: str = Form(""), doc_type: str = Form(""), label: str = Form("")):
    """Add a document, or a new version of an existing one, and re-index."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    name = file.filename or "upload.pdf"
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "only PDF files can be uploaded")
    if doc_id and doc_id not in {d["doc_id"] for d in fetch.load_inventory()["documents"]}:
        raise HTTPException(400, "unknown document")

    def go(step):
        res = revision.add_upload(data, name, doc_id or None, title, doc_type, label, step)
        d = next(x for x in fetch.load_inventory()["documents"] if x["doc_id"] == res["doc_id"])
        lab = label.strip() or f"v{res['version']}"
        _log("upload", f"Uploaded {name} as version {res['version']} ({lab}) of \"{d['title']}\"" + (f"; version {res['replaced']} is now superseded" if res["replaced"] else "")
             + f". {res['passages']} passages indexed, {res['review_items']} change/conflict item(s) sent to expert review.")
        step("done: ask a question, or open Expert review")
    return _start("Upload and re-index", go)


class Link(BaseModel):
    url: str
    doc_id: str = ""
    title: str = ""
    doc_type: str = ""
    label: str = ""


@app.post("/api/source/link")
def add_link(l: Link):
    """Add a public link (PDF or web page), or a newer copy of an existing document, and re-index."""
    if l.doc_id and l.doc_id not in {d["doc_id"] for d in fetch.load_inventory()["documents"]}:
        raise HTTPException(400, "unknown document")

    def go(step):
        res = revision.add_link(l.url.strip(), l.doc_id or None, l.title, l.doc_type, l.label, step)
        d = next(x for x in fetch.load_inventory()["documents"] if x["doc_id"] == res["doc_id"])
        _log("upload", f"Added {l.url.strip()} as version {res['version']} of \"{d['title']}\"" + (f"; version {res['replaced']} is now superseded" if res["replaced"] else "")
             + f". {res['passages']} passages indexed, {res['review_items']} change/conflict item(s) sent to expert review.")
        step("done: ask a question, or open Expert review")
    return _start("Add a link and re-index", go)


@app.post("/api/reset")
def reset_all():
    """Start over: every document, the review queue, the evaluation, the history and the saved verdicts are removed."""
    def go(step):
        for d in list(fetch.load_inventory()["documents"]):
            step(f"removing {d['title'][:60]}")
            revision.remove_document(d["doc_id"], lambda m: None)
        for f in (config.REVIEW_QUEUE, GEN, LOG, conflicts.CACHE):
            f.unlink(missing_ok=True)
        inv = fetch.load_inventory()
        inv["not_accessible"] = []
        fetch.save_inventory(inv)
        retrieve.reset_cache()
        step("empty: add your sources")
    return _start("Start over", go)


@app.delete("/api/source/{doc_id}")
def remove_source(doc_id: str):
    if doc_id not in {d["doc_id"] for d in fetch.load_inventory()["documents"]}:
        raise HTTPException(404, "unknown document")

    def go(step):
        revision.remove_document(doc_id, step)
        _log("remove", f"Removed document {doc_id} from the system.")
    return _start("Remove a document", go)


# ---- 4. expert review queue ----
@app.get("/api/review")
def review_queue():
    return json.loads(config.REVIEW_QUEUE.read_text()) if config.REVIEW_QUEUE.exists() else []


class Decision(BaseModel):
    decision: str
    reviewer: str = ""
    note: str = ""


@app.post("/api/review/{item_id}")
def review_decide(item_id: str, d: Decision):
    try:
        return conflicts.decide(item_id, d.decision, d.reviewer, d.note)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/decisions")
def decisions():
    return list(conflicts.DECISIONS)


# ---- 5. evaluation (generated on the spot from the loaded documents) ----

@app.get("/api/eval")
def eval_results():
    return dict(generated=json.loads(GEN.read_text()) if GEN.exists() else None)


@app.post("/api/eval/generate")
def eval_generate():
    if not fetch.load_inventory()["documents"]:
        raise HTTPException(400, "Add sources first.")
    from eval import generate

    def go(step):
        res = generate.run(step)
        step(f"{sum(r['result'] == 'PASS' for r in res)}/{len(res)} passed")
    return _start("Generate the evaluation from the loaded documents", go)


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")
