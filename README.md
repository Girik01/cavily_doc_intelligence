# Documentation intelligence (Assignment 2)

A small workflow that ingests the technical documents you give it (public links and PDFs), finds the passages that answer a question,
and returns an answer with the document title and the **page (PDF) or section (web page)** it came from. It recognises document versions,
says when evidence is missing, and sends outdated or conflicting sources to an expert for review. Everything runs from a local web interface.

Nothing is hardcoded to one product. The system starts **empty**: you supply the source links and PDFs at the beginning, then it processes
them. The demonstration in this submission uses the Cavli **C16QS** module (see `docs/demo_sources.md`).

Stack: Python, FastAPI, Qdrant Cloud, OpenAI (`gpt-5.5`, `text-embedding-3-small`), BM25 (rank-bm25), PyMuPDF.

## Run it
```bash
cd assignment2_doc_intelligence
uv sync
cp .env.example .env       # add OPENAI_API_KEY, QDRANT_URL, QDRANT_API_KEY (never commit .env)
uv run main.py             # then open http://127.0.0.1:8002
```
`HOST` and `PORT` can be set as environment variables. The downloaded files are stored in `data/versions/` (not committed).

## The flow (what you do in the interface)
1. **Sources (first tab):** the page is empty. Paste links to public PDFs or web pages (one per line) and/or choose PDF files, optionally type a
   version name, and press **Process the sources**. Optional: list documents that exist but you cannot access (title and reason); they are named in "not verified" answers.
2. **Processing** (one background job with visible steps): each source is downloaded (or read from your upload), stored with title, URL, type, host,
   revision, dates and a SHA-256 hash, split into passages (PDF: real page and printed heading; web: section name; FAQ: one passage per question),
   embedded into Qdrant, and then **compared with the other documents** to find conflicts.
3. **Chat bubble (bottom right, on every tab, can be enlarged):** ask a question. The answer carries numbered citations with document title, page or
   section, revision and date; under them are the supporting text and the retrieved passages with dense and keyword ranks. Options: dense, keyword or hybrid retrieval; include older versions.
4. **Newer versions:** every document card has "Add a newer version of this document": upload a PDF or paste a link. A new file whose title matches a loaded document is refused, so versions are never guessed. It becomes
   the next version, the previous one is marked superseded (kept for audit, hidden from default answers), it is indexed, and **What changed** shows a table of facts before and after. "Fetch again and re-index" repeats the download for every link you added and creates a new version only when the content hash changed. Any document can be removed.
5. **Expert review:** conflicts between documents (quoted from both sides), outdated versions, documents without a date, uploaded files without a public origin. A person records a
   named decision or reopens an item. Nothing is resolved by the AI. "Raised by a question" shows the items a user's question ran into; "All open" shows everything found.
6. **Evaluation:** one button writes about 10 questions from passages of the documents that are loaded (code checks that each expected fact really is in its passage), adds 2 questions no
   document can answer, runs them through the same code the chat uses, and shows for each: expected source, observed output, citation validity, failure category. It then writes the failure report with recommended
   documentation improvements from the evidence. Because it is generated from the loaded documents, changing the sources never breaks it.

## How it works
1. **Ingest** (`docint/fetch.py`, `docint/revision.py`): downloads, sniffs PDF vs web page from the bytes, hashes (HTML on its visible text, because raw HTML changes on every request; PDFs on bytes), keeps every version.
2. **Chunk** (`docint/chunking.py`, `docint/pdf_tables.py`): a generic reader for web pages (heading sections, plus question/answer pairs that a page ships in its script data); plain page-based reading for short PDFs and a layout-aware reader for long
   technical PDFs whose tables plain extraction scrambles. Two Cavli page layouts have dedicated readers (`docint/cavli_html.py`).
3. **Index and retrieve** (`docint/index.py`, `docint/retrieve.py`): dense (Qdrant) plus keyword (BM25), fused by reciprocal rank. Superseded versions are hidden unless asked for.
4. **Answer** (`docint/answer.py`): the model answers only from numbered passages and cites labels; code turns labels into title + page/section and checks that cited passages were retrieved and that every number in the answer
   appears in the cited text. Otherwise "Not verified". Ambiguous questions get an answer per case and one clarifying question.
5. **Conflicts and changes** (`docint/conflicts.py`): the model judges pairs of similar passages from different documents; the quotes it returns must exist verbatim in the passages or the finding is dropped. Changes between versions are a line diff summarised by
   the model, each before/after value checked against the diff. Verdicts are cached in `data/judge_cache.json`.
6. **Web interface** (`docint/server.py`, `docint/static/index.html`): a thin layer over the modules above.

## Command line (same modules, no web interface)
```bash
uv run python -m docint.cli add https://example.com/page https://example.com/spec.pdf ./local.pdf
uv run python -m docint.cli ask "What is the sleep mode current?" --show-passages
uv run python -m docint.cli review
```

## Assumptions, services, costs
- **Third-party services:** OpenAI API (answers, embeddings, conflict judging, evaluation generation), Qdrant Cloud (vector store). Sources are fetched from whatever links you give.
- **Cost:** about 5,100 input and 220 output tokens per answer plus one embedding call (measured on 6 questions); conflict judging adds up to 30 short model calls per processing run (cached). Multiply by the current OpenAI price (not stated here).
- **Assumptions:** documents you give are genuine; a version label is what you typed (never guessed).
- **Simulated:** nothing. Versions are real files you supply.
- **Not built:** scheduled re-indexing (re-indexing runs when you press the button), per-statement citation checking, user accounts, uploads other than PDF (links may be PDF or web page), cross-document conflict checking beyond the 30 most similar passage pairs.
- **Human approval:** the tool publishes and sends nothing. Review items need a named expert decision; use of answers outside the team needs human approval.

## Earlier hand-written evaluation
`eval/questions.json`, `eval/results.md` and `eval/failure_report.md` hold an earlier author-written 25-question evaluation (22/25) for the original C16QS source set. It is kept as evidence; the interface now generates its evaluation from whatever is loaded.

## Submission documents
`docs/validation_note.pdf` (architecture and validation note), `docs/demo_sources.md` (what to load for the demo), `docs/submission_flow.md`, `docs/source_inventory.md` and `docs/sample_run/` (output of a demo run).
