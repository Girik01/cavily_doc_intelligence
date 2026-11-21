"""Evaluation generated on the spot from whatever sources are loaded now (so changing the sources cannot break it).
For a sample of passages of the current documents the model writes one question and the fact that answers it; code checks that the
fact really is in the passage. Those questions, plus two fixed unanswerable ones, run through the same code the chatbot uses and are
graded with the same rules as the author-written set (eval/run_eval.py)."""
import json, random, re

from docint import answer, config, fetch, index, store
from eval import run_eval

OUT = config.DATA / "eval_generated.json"
UNANSWERABLE = ["What is the price of this product and how many units are in stock?",
                "Which firmware release fixes the eDRX wake-up bug?"]
PROMPT = """Write ONE question that can be answered ONLY from the passage below, and the exact short fact that answers it.
Rules: the question must be self-contained (name the product or document, never say "this passage"); it asks for one specific value,
name or number; "fact" must be copied EXACTLY (same characters) from the passage and be short (1-6 words).
Reply with JSON only: {"question": "...", "fact": "..."}

Passage:
"""


def _pick(per_doc):
    """Spread the choice over the documents; prefer passages with enough text and at least one number."""
    rnd = random.Random(7)
    chosen = []
    pools = {k: [p for p in v if len(p["text"]) > 200] for k, v in per_doc.items()}
    for k in pools:
        pools[k].sort(key=lambda p: (not re.search(r"\d", p["text"]), p["passage_id"]))
    while len(chosen) < 10 and any(pools.values()):
        for k in list(pools):
            if pools[k] and len(chosen) < 10:
                chosen.append(pools[k].pop(rnd.randrange(min(3, len(pools[k])))))
    return chosen


def build_questions(step):
    inv = fetch.load_inventory()
    per_doc = {}
    for p in index.all_passages(inv):
        if p["status"] == "current":
            per_doc.setdefault(p["doc_id"], []).append(p)
    qs = []
    for p in _pick(per_doc):
        step(f"writing a question for {p['title'][:50]} / {p['location']}")
        try:
            raw = store.chat_llm(timeout=60).invoke([("human", PROMPT + p["text"][:1800])]).content
            j = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        except Exception:
            continue
        fact = (j.get("fact") or "").strip()
        if not fact or run_eval._norm(fact) not in run_eval._norm(p["text"]) or not j.get("question"):
            continue          # the fact must really be in the passage
        qs.append(dict(id=f"G{len(qs) + 1}", type="answerable", q=j["question"].strip(), expect_contains=[fact],
                       expect_sources=[(p["doc_id"], None)], where=f"{p['title']} / {p['location']}"))
    for i, t in enumerate(UNANSWERABLE, 1):
        qs.append(dict(id=f"G-U{i}", type="unanswerable", q=t, expect_kind="not_verified"))
    return qs


def _still_missing(q, r):
    """A fact counts as present when every word and number of it is in the answer ("3xUART" is met by "3 UART interfaces")."""
    toks = lambda t: re.findall(r"[a-z]+|\d+(?:\.\d+)?", re.sub(r"(?<=\d)x(?=[a-z])", " ", t.lower()))
    have = set(toks(r["answer"]))
    return [f for f in q.get("expect_contains", []) if not all(t in have for t in toks(f))]


def run(step):
    qs = build_questions(step)
    answerable = sum(q["type"] == "answerable" for q in qs)
    if answerable < 6:
        raise RuntimeError(f"only {answerable} usable questions could be generated from the current sources (need more or longer documents)")
    inv = fetch.load_inventory()
    res = []
    for q in qs:
        r = answer.ask(q["q"])
        g = run_eval.grade(dict(q, expect_contains=_still_missing(q, r)), r, inv)
        res.append(dict(id=q["id"], type=q["type"], question=q["q"], expected=q.get("expect_contains") or "not_verified",
                        expected_sources=[q["where"]] if q.get("where") else [], observed_kind=r["kind"], observed=r["answer"],
                        cited=[f"{c['title']} - {c['location']}" for c in r["citations"]], latency_ms=r.get("latency_ms"), **g))
        step(f"{len(res)}/{len(qs)} {q['id']} {g['result']}")
    step("writing the failure report and documentation recommendations")
    OUT.write_text(json.dumps(dict(results=res, model=config.CHAT_MODEL, run_at=fetch.now(), report=report(res, inv),
                                   sources=[d["title"] for d in inv["documents"]]), indent=1, ensure_ascii=False))
    return res


RECS = """You review technical documentation. Below are problems found automatically while testing a question-answering system on these
documents: failed test questions and issues flagged between documents. Write 3 to 8 concrete recommended documentation
improvements for the documentation owner. Each one: a short bold title, then one or two sentences naming the evidence (document
and value) it is based on. Use only the evidence below; do not invent problems. A failed test question can be caused by the test or the system (for example a badly
chosen expected fact) and not by the documentation: recommend a documentation change only where the evidence shows a documentation problem
(a conflict between documents, a missing or unclear value, a missing date or version). Markdown bullet list only.

FAILED TEST QUESTIONS:
%s

ISSUES FLAGGED BETWEEN DOCUMENTS:
%s"""


def report(res, inv):
    """Failure report from this run: counts, each failure with its category, and documentation improvements written from the evidence."""
    fails = [r for r in res if r["result"] == "FAIL"]
    L = [f"Run on {len(inv['documents'])} documents: {len(res) - len(fails)} of {len(res)} questions passed, {len(fails)} failed.", ""]
    if fails:
        L += ["| ID | Question | What happened | Failure category |", "|---|---|---|---|"]
        for r in fails:
            L.append(f"| {r['id']} | {r['question']} | {r['observed'][:200].replace(chr(10), ' ').replace('|', '/')} | {r['failure_category']} |")
    else:
        L.append("No question failed in this run.")
    items = json.loads(config.REVIEW_QUEUE.read_text()) if config.REVIEW_QUEUE.exists() else []
    flagged = [f"- {i['type']}: {i['summary']}" for i in items if i["type"] != "revision_change"][:15]
    failed = [f"- {r['question']} -> {r['failure_category']}: {r['observed'][:160]}" for r in fails]
    L += ["", "### Recommended documentation improvements", ""]
    if not (failed or flagged):
        L.append("Nothing to recommend from this run.")
    else:
        try:
            L.append(store.chat_llm(timeout=90).invoke([("human", RECS % ("\n".join(failed) or "none", "\n".join(flagged) or "none"))]).content.strip())
        except Exception as e:
            L.append(f"(could not be written: {e})")
    return "\n".join(L)
