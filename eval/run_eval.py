"""Evaluation: 25 questions (answerable, ambiguous, unanswerable, conflict, revision), observed results, citation validity,
failure category, and a dense / keyword / hybrid retrieval comparison.
  uv run python -m docint.cli eval            (baseline run, then a SIMULATED revision run, then the simulation is undone)"""
import json, re, sys
from pathlib import Path

from docint import answer, config, fetch, retrieve

HERE = Path(__file__).resolve().parent
CONFLICT_WORDS = re.compile(r"conflict|differ|disagree|inconsisten|flagged|not consistent|contradict", re.I)


def _norm(s):
    return re.sub(r"\s+", " ", s.lower())


def src_hit(passages, expect):
    return any(p["doc_id"] == d and (loc is None or loc.lower() in p["location"].lower()) for p in passages for d, loc in expect)


def cite_valid(r, inv):
    """Every citation must name a real document, a location that exists, and (for PDFs) a page within the PDF."""
    problems = []
    docs = {d["doc_id"]: d for d in inv["documents"]}
    for c in r["citations"]:
        if c.get("url") is None:       # a review item, not a document
            continue
        pid = c["passage_id"]
        doc_id, ver = pid.split("@v")[0], int(pid.split("@v")[1].split("#")[0])
        d = docs.get(doc_id)
        v = next((v for v in d["versions"] if v["version"] == ver), None) if d else None
        if not v:
            problems.append(f"{pid}: version not in inventory")
        elif c.get("page") and c["page"] > v.get("pdf", {}).get("pages", 0):
            problems.append(f"{pid}: page {c['page']} does not exist")
        if not any(p["passage_id"] == pid for p in r["retrieved"]):
            problems.append(f"{pid}: not among the retrieved passages")
    return (not problems, problems)


def grade(q, r, inv):
    out = dict(retrieval_hit=None, citation_valid=None, expected_source_cited=None, result="PASS", failure_category="-", notes=[])
    kind = r["kind"]
    ans = _norm(r["answer"])
    if q.get("expect_sources"):
        out["retrieval_hit"] = src_hit([dict(doc_id=p["passage_id"].split("@")[0], location=p["location"]) for p in r["retrieved"]], q["expect_sources"])
    ok, probs = cite_valid(r, inv)
    out["citation_valid"] = ok if r["citations"] else None
    if probs:
        out["notes"] += probs
    if r["citations"] and q.get("expect_sources"):
        cited = [dict(doc_id=c["passage_id"].split("@")[0], location=c["location"]) for c in r["citations"] if c.get("url")]
        out["expected_source_cited"] = src_hit(cited, q["expect_sources"])
    fail = None
    t = q["type"]
    if t == "unanswerable":
        if kind == "answer":
            fail = "unsupported_answer (answered an unanswerable question)"
        elif q.get("expect_gap") and r.get("gap_document") != q["expect_gap"]:
            fail = "missing_gap_hint (did not name the inaccessible document)"
    elif t in ("answerable", "revision"):
        if kind != "answer":
            fail = "false_refusal" if out["retrieval_hit"] else "retrieval_miss"
        else:
            missing = [s for s in q.get("expect_contains", []) if _norm(s) not in ans]
            if missing:
                fail = ("retrieval_miss" if out["retrieval_hit"] is False else "wrong_or_missing_fact") + f" (missing {missing})"
            elif out["expected_source_cited"] is False:
                fail = "citation_error (expected source not cited)"
            elif [s for s in q.get("expect_absent", []) if _norm(s) in ans]:
                fail = f"stale_version_used (answer contains {[s for s in q['expect_absent'] if _norm(s) in ans]})"
            elif ok is False:
                fail = "citation_error (invalid citation)"
    elif t == "conflict":
        if kind != "answer":
            fail = "false_refusal"
        elif not (CONFLICT_WORDS.search(r["answer"]) or r.get("review_items")):
            fail = "conflict_missed"
    elif t == "ambiguous":
        if kind != "answer":
            fail = "false_refusal"
        elif not (r.get("ambiguous") or r.get("clarifying_question")):
            fail = "ambiguity_not_flagged"
    if fail:
        out["result"], out["failure_category"] = "FAIL", fail
    return out


def retrieval_table(qs):
    rows = {m: [0, 0] for m in ("dense", "keyword", "hybrid")}
    for q in qs:
        if not q.get("expect_sources"):
            continue
        for m in rows:
            ps, _ = retrieve.retrieve(q["q"], mode=m, k=config.TOP_K, include=("current", "superseded") if q.get("include_superseded") else ("current",))
            rows[m][1] += 1
            rows[m][0] += src_hit(ps, q["expect_sources"])
    return {m: f"{a}/{b}" for m, (a, b) in rows.items()}


def run_phase(qs, progress=None):
    inv = fetch.load_inventory()
    res = []
    for q in qs:
        inc = ("current", "superseded") if q.get("include_superseded") else ("current",)
        r = answer.ask(q["q"], include=inc)
        g = grade(q, r, inv)
        res.append(dict(id=q["id"], type=q["type"], question=q["q"], expected=q.get("expect_contains") or q.get("expect_behavior") or q.get("expect_kind") or ("conflict reported" if q.get("expect_conflict") else ""),
                        expected_sources=[f"{d} / {l}" for d, l in q.get("expect_sources", [])], observed_kind=r["kind"], observed=r["answer"],
                        cited=[f"{c['title']} - {c['location']}" for c in r["citations"]], ambiguous=r.get("ambiguous"), clarifying_question=r.get("clarifying_question"),
                        latency_ms=r.get("latency_ms"), **g))
        print(f"{q['id']:3} {g['result']:4} {g['failure_category']}")
        if progress:
            progress(f"{len(res)}/{len(qs)} {q['id']} {g['result']}")
    return res


def run(progress=None):
    qs = json.loads((HERE / "questions.json").read_text())
    results = run_phase(qs, progress)
    if progress:
        progress("comparing dense, keyword and hybrid retrieval")
    ret = retrieval_table(qs)
    (HERE / "results.json").write_text(json.dumps(dict(results=results, retrieval_hit_at_8=ret, model=config.CHAT_MODEL, run_at=fetch.now()), indent=1, ensure_ascii=False))
    write_markdown(results, ret)
    return results, ret


def main(argv):
    run()


def write_markdown(results, ret):
    n = len(results)
    ok = sum(r["result"] == "PASS" for r in results)
    L = [f"# Evaluation results ({n} questions)", "",
         "Produced by `uv run python -m docint.cli eval`. Model " + config.CHAT_MODEL + ", hybrid retrieval (dense + BM25), top 8 passages. "
         "Revision questions (R1-R3) use the two real revisions of the technical specification (V2.0 and V2.9); R2 and R3 ask for the superseded version on purpose.", "",
         f"**Overall: {ok}/{n} passed.**  Retrieval check (an expected source is in the top 8): " + ", ".join(f"{m} {v}" for m, v in ret.items()) + ".", "",
         "| ID | Type | Question | Expected | Expected source | Observed output | Citation valid | Result | Failure category |", "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        obs = r["observed"].replace("\n", " ").replace("|", "/")
        cv = {True: "yes", False: "NO", None: "n/a"}[r["citation_valid"]]
        exp = r["expected"] if isinstance(r["expected"], str) else ", ".join(r["expected"])
        L.append(f"| {r['id']} | {r['type']} | {r['question']} | {exp} | {'; '.join(r['expected_sources']) or '-'} | {obs[:420]} | {cv} | {r['result']} | {r['failure_category']} |")
    (HERE / "results.md").write_text("\n".join(L) + "\n")
    print(f"\n{ok}/{n} passed; wrote eval/results.md")
