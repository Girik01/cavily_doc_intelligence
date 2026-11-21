"""Cross-document checks for ANY set of loaded documents. Nothing is resolved: every finding becomes a review item for an expert, with
the evidence of both sides. Conflicts are found by a model judging pairs of similar passages from different documents (the quotes it
returns must exist verbatim in the passages, otherwise the finding is dropped); changes between versions are derived from the stored
versions; verdicts are cached so repeating a run costs nothing."""
import datetime
import difflib, hashlib, json, re

import numpy as np

from docint import chunking, config, store
from docint.fetch import load_inventory, now

CACHE = config.DATA / "judge_cache.json"
SIM_MIN, MAX_PAIRS = 0.60, 30


def _current_passages(inv):
    out = {}
    for d in inv["documents"]:
        v = next((v for v in d["versions"] if v["status"] == "current"), None)
        if v:
            out[d["doc_id"]] = (d, v, chunking.passages_for(d, v, config.ROOT))
    return out


def _item(kind, severity, summary, evidence, doc_ids):
    key = hashlib.sha1((kind + summary).encode()).hexdigest()[:8]
    return dict(id=f"RV-{key}", type=kind, severity=severity, summary=summary, evidence=evidence, doc_ids=sorted(set(doc_ids)),
                status="open - needs expert review", detected_at=now())


def _ev(doc, passage, quote):
    return dict(doc_id=doc["doc_id"], doc_title=passage["title"], location=passage["location"], passage_id=passage["passage_id"], quote=quote)


def _norm(t):
    return re.sub(r"\s+", " ", t.lower()).strip()


def _cache():
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def _ask_json(prompt):
    raw = store.chat_llm(timeout=60).invoke([("human", prompt)]).content
    return json.loads(re.search(r"\{.*\}", raw, re.S).group(0))


JUDGE = """Two passages from two DIFFERENT documents. Decide whether they state DIFFERENT values for the SAME specific attribute
(a number, version, date, name or count of the same thing). It is NOT a conflict if one passage is just more detailed, if they
describe different products, regions, variants or states, or if only wording differs.
Reply with JSON only: {"conflict": true|false, "attribute": "short name", "value_a": "...", "quote_a": "...", "value_b": "...", "quote_b": "..."}
quote_a / quote_b must be copied EXACTLY from passage A / passage B (one short sentence or table row that holds the value).

Passage A (%s):
%s

Passage B (%s):
%s"""


def find_conflicts(cur, step=None):
    ps = [(d, p) for d, v, pp in cur.values() for p in pp if len(p["text"]) >= 80]
    if len({d["doc_id"] for d, _ in ps}) < 2:
        return []
    V = np.array(store.embeddings().embed_documents([p["embed_text"] for _, p in ps]))
    V = V / np.linalg.norm(V, axis=1, keepdims=True)
    sim = V @ V.T
    cand = sorted(((sim[i, j], i, j) for i in range(len(ps)) for j in range(i + 1, len(ps))
                   if ps[i][0]["doc_id"] != ps[j][0]["doc_id"] and sim[i, j] >= SIM_MIN), reverse=True)[:MAX_PAIRS]
    cache, items, dirty = _cache(), [], False
    for n, (_, i, j) in enumerate(cand, 1):
        (da, pa), (db, pb) = ps[i], ps[j]
        key = hashlib.sha1((config.CHAT_MODEL + pa["text"] + "||" + pb["text"]).encode()).hexdigest()
        if key not in cache:
            if step:
                step(f"comparing passages from different documents ({n}/{len(cand)})")
            try:
                cache[key] = _ask_json(JUDGE % (da["title"], pa["text"][:1500], db["title"], pb["text"][:1500]))
            except Exception:
                continue
            dirty = True
        r = cache[key]
        if not r.get("conflict") or _norm(r.get("quote_a", "")) not in _norm(pa["text"]) or _norm(r.get("quote_b", "")) not in _norm(pb["text"]):
            continue
        items.append(_item("conflict", "high",
                           f"{r.get('attribute', 'A value')}: {da['title']} says {r.get('value_a')}; {db['title']} says {r.get('value_b')}.",
                           [_ev(da, pa, r["quote_a"]), _ev(db, pb, r["quote_b"])], [da["doc_id"], db["doc_id"]]))
    if dirty:
        CACHE.write_text(json.dumps(cache))
    return items


CHANGES = """Two versions of the same document. REMOVED lines are only in the old version, ADDED lines only in the new one.
List the meaningful factual changes (a value, name, count, date or statement that changed, was added or was removed). Ignore layout,
formatting and re-ordering. At most 15. Reply with JSON only: {"changes": [{"fact": "what it is", "before": "...", "after": "..."}]}
"before" must be copied exactly from a REMOVED line and "after" exactly from an ADDED line (use "not stated" when absent).

REMOVED:
%s

ADDED:
%s"""


def line_changes(po, pn):
    lo = [l for p in po for l in p["text"].split("\n")]
    ln = [l for p in pn for l in p["text"].split("\n")]
    return [l[:260] for l in difflib.unified_diff(lo, ln, lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]


def version_changes(po, pn):
    """Facts that changed between two versions. The model only summarises the line diff; each before/after must be in it."""
    raw = line_changes(po, pn)
    rem, add = [l[1:].strip() for l in raw if l[0] == "-"], [l[1:].strip() for l in raw if l[0] == "+"]
    if not raw:
        return []
    key = hashlib.sha1((config.CHAT_MODEL + "\n".join(rem) + "||" + "\n".join(add)).encode()).hexdigest()
    cache = _cache()
    if key not in cache:
        try:
            cache[key] = _ask_json(CHANGES % ("\n".join(rem)[:9000], "\n".join(add)[:9000]))
            CACHE.write_text(json.dumps(cache))
        except Exception:
            return raw
    R, A = _norm("\n".join(rem)), _norm("\n".join(add))
    out = []
    for c in cache[key].get("changes", []):
        b, a = str(c.get("before", "")), str(c.get("after", ""))
        if (b == "not stated" or _norm(b) in R) and (a == "not stated" or _norm(a) in A) and c.get("fact"):
            out.append(f"{c['fact']}: {b}  ->  {a}")
    return out or raw


def detect(inv=None, step=None):
    inv = inv or load_inventory()
    cur = _current_passages(inv)
    items = find_conflicts(cur, step)

    undated = [(d["doc_id"], d["title"]) for d, v, _ in cur.values() if not v.get("revision") and not v.get("published") and not v.get("date_note")]
    if undated:
        items.append(_item("missing_revision_metadata", "low",
            f"{len(undated)} source(s) state no revision, version or publication date ({'; '.join(t for _, t in undated)}). When they disagree it cannot be established which one is newer; only the fetch date and a content hash are recorded.",
            [dict(doc_id=i, doc_title=t, location="document metadata", passage_id=None, quote="no revision or publication date stated") for i, t in undated], [i for i, _ in undated]))
    uploaded = [(d, v) for d, v, _ in cur.values() if v.get("host") == "uploaded by the user"]
    if uploaded:
        items.append(_item("provenance", "low",
            f"{len(uploaded)} document(s) were uploaded as files, so their origin and authenticity cannot be checked from a public link: {'; '.join(d['title'] for d, _ in uploaded)}.",
            [dict(doc_id=d["doc_id"], doc_title=d["title"], location="inventory", passage_id=None, quote=f"{v['source_url']} | {v.get('date_note') or 'no date'}") for d, v in uploaded],
            [d["doc_id"] for d, _ in uploaded]))

    for d in inv["documents"]:
        vs = sorted(d["versions"], key=lambda v: v["version"])
        for old, new in zip(vs, vs[1:]):
            po = chunking.passages_for(d, old, config.ROOT)
            pn = chunking.passages_for(d, new, config.ROOT)
            lab = lambda v: v.get("label") or f"v{v['version']}"
            changes = version_changes(po, pn)
            ev = [dict(doc_id=d["doc_id"], doc_title=d["title"], location=f"{lab(old)} -> {lab(new)}", passage_id=None, quote=c) for c in changes[:14]]
            items.append(_item("revision_change", "medium",
                f"{d['title']} changed from {lab(old)} to {lab(new)}: {len(changes)} difference(s) found. {lab(old)} is outdated; answers use {lab(new)}. The old version is kept for audit.",
                ev, [d["doc_id"]]))
    return items


def refresh_review_queue(step=None):
    items = detect(step=step)
    prev = {r["id"]: r for r in json.loads(config.REVIEW_QUEUE.read_text())} if config.REVIEW_QUEUE.exists() else {}
    for it in items:
        if it["id"] in prev:
            for k in ("status", "detected_at", "reviewer", "note", "decided_at", "asked"):
                if k in prev[it["id"]]:
                    it[k] = prev[it["id"]][k]
    config.REVIEW_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    config.REVIEW_QUEUE.write_text(json.dumps(items, indent=1, ensure_ascii=False))
    return items


def mark_asked(ids, question):
    """Remember that a user's question ran into these review items (shown in the Expert review tab)."""
    if not ids or not config.REVIEW_QUEUE.exists():
        return
    q = json.loads(config.REVIEW_QUEUE.read_text())
    for it in q:
        if it["id"] in ids:
            a = it.setdefault("asked", [])
            if question not in [x["question"] for x in a]:
                a.append(dict(question=question, at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")))
                del a[:-5]
    config.REVIEW_QUEUE.write_text(json.dumps(q, indent=1, ensure_ascii=False))


DECISIONS = ("confirmed: newer document is correct", "confirmed: product page is correct", "documentation fix requested", "dismissed: not a real problem")


def decide(item_id, decision, reviewer, note=""):
    """A human expert closes (or reopens) a review item. Only open items are shown to the answer model as unresolved issues."""
    q = json.loads(config.REVIEW_QUEUE.read_text())
    it = next((r for r in q if r["id"] == item_id), None)
    if it is None:
        raise ValueError("unknown review item")
    if decision == "reopen":
        it["status"] = "open - needs expert review"
        for k in ("reviewer", "note", "decided_at"):
            it.pop(k, None)
    else:
        if decision not in DECISIONS:
            raise ValueError("unknown decision")
        if not reviewer.strip():
            raise ValueError("reviewer name required (human approval)")
        it.update(status="reviewed - " + decision, reviewer=reviewer.strip(), note=note.strip(), decided_at=now())
    config.REVIEW_QUEUE.write_text(json.dumps(q, indent=1, ensure_ascii=False))
    return it
