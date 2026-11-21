"""uv run python -m docint.cli <command>
   add <link|file.pdf> [...]   add documents (links are re-fetched by `ingest`), index them and refresh the review queue
   ingest             fetch every added link again (new version only if the content changed)
   index              embed all stored versions into Qdrant
   inventory          print the source inventory
   ask "question"     cited answer   [--mode dense|keyword|hybrid] [--include-superseded] [--show-passages]
   review             print the review queue (conflicts, outdated sources, document problems)"""
import json, sys

from docint import config, fetch


def show_inventory():
    inv = fetch.load_inventory()
    for d in inv["documents"]:
        print(f"\n{d['doc_id']}  |  {d['title']}\n  type: {d['doc_type']}  |  url: {d['url']}")
        for v in d["versions"]:
            print(f"  v{v['version']} [{v['status']}]  fetched {v['fetched_at']}  sha256 {v['sha256'][:12]}  "
                  f"revision: {v.get('revision') or 'none stated'}  published: {v.get('published') or 'none stated'}")
    print("\nNOT ACCESSIBLE (listed, not used):")
    for n in inv["not_accessible"]:
        print(f"  - {n['title']} ({n['doc_type']}): {n['reason']}")


def show_answer(r, passages=False):
    print(f"\nQ: {r['question']}\nmode={r['mode']}  best cosine={r['best_cosine']}  type={r['kind']}  {r.get('latency_ms', '')} ms")
    if passages:
        print("\nRetrieved passages:")
        for i, p in enumerate(r["retrieved"], 1):
            print(f"  {i}. [{p['status']}] {p['title']} | {p['location']} | dense#{p['dense_rank']} kw#{p['keyword_rank']} score {p['score']}")
    print("\nANSWER:\n" + r["answer"])
    if r.get("clarifying_question"):
        print("\nAsk back:", r["clarifying_question"])
    if r.get("missing"):
        print("Not verified:", ", ".join(r["missing"]))
    for c in r["citations"]:
        loc = f"page {c['page']}" if c.get("page") else c["location"]
        print(f"  [{c['n']}] {c['title']} - {loc}" + (f" - revision {c['revision']}" if c.get("revision") else "")
              + (f" - published {c['published']}" if c.get("published") else (f" - {c['date_note']}" if c.get("date_note") else "")) + (f"\n      {c['url']}" if c.get("url") else ""))
    ev = [c for c in r["citations"] if c.get("text")]
    if ev:
        print("\nEVIDENCE (the retrieved passages the answer is based on):")
        for c in ev:
            loc = f"page {c['page']}" if c.get("page") else c["location"]
            body = c["text"] if len(c["text"]) <= 700 else c["text"][:700] + " ..."
            print(f"  [{c['n']}] {loc}\n" + "\n".join("      " + l for l in body.split("\n")))
    for f in r["flags"]:
        print("  flag:", f)


def main(argv):
    cmd = argv[0] if argv else "help"
    if cmd == "add":
        from pathlib import Path
        from docint import revision
        for a in argv[1:]:
            r = revision.add_link(a, refresh=False) if a.startswith("http") else revision.add_upload(Path(a).read_bytes(), Path(a).name, None, Path(a).stem, "", "", refresh=False)
            print(a, "->", r)
        from docint import conflicts
        print("review items:", len(conflicts.refresh_review_queue(print)))
    elif cmd == "ingest":
        for doc_id, status in fetch.ingest_inventory():
            print(f"{doc_id}: {status}")
    elif cmd == "index":
        from docint import index
        print("indexed passages:", index.index_all())
    elif cmd == "inventory":
        show_inventory()
    elif cmd == "ask":
        from docint import answer
        q = " ".join(a for a in argv[1:] if not a.startswith("--") and a not in ("dense", "keyword", "hybrid"))
        mode = next((a for a in argv if a in ("dense", "keyword", "hybrid")), "hybrid")
        inc = ("current", "superseded") if "--include-superseded" in argv else ("current",)
        show_answer(answer.ask(q, mode=mode, include=inc), passages="--show-passages" in argv)
    elif cmd == "review":
        from docint import conflicts
        for r in conflicts.refresh_review_queue():
            print(f"\n{r['id']}  [{r['severity']}] {r['type']}  - {r['status']}\n  {r['summary']}")
            for e in r["evidence"]:
                print(f"    * {e['doc_title']} ({e['location']}): {e['quote'][:150]}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
