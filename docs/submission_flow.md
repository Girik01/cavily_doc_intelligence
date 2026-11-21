# Assignment 2: the flow, and what is submitted

## A. The flow (what the system does)

```
 START EMPTY
     │  you give it: links (public PDFs / web pages) + PDF files, optional "not accessible" list
     ▼
 PROCESS    download ─► title, URL, type, host, revision, dates, SHA-256 ─► chunk (page / section / FAQ question)
            ─► embed into Qdrant (+ BM25) ─► compare the documents with each other
     │
     ├──► CHAT BUBBLE   hybrid retrieval ─► cited answer: title + page/section ─► checks: labels, numbers, "not verified"
     │                  ambiguous ─► one question back
     │
     ├──► NEWER VERSION upload a PDF or paste a link to it ─► new hash = new version ─► old = superseded ─► re-index
     │                  ─► "What changed" table (before / after, each value checked against the text)
     │
     ├──► EXPERT REVIEW conflicts (both sides quoted, quotes verified), outdated versions, undated or uploaded-only documents;
     │                  a named person decides; nothing is resolved by the AI
     │
     └──► EVALUATION    questions written from the loaded documents + 2 unanswerable ─► run ─► failure report
```
In the interface: three tabs, **Sources · Expert review · Evaluation**, and a floating chat bubble for questions. Start it with `uv run main.py`.
Nothing about the C16QS is built into the code; the C16QS is only the demonstration (`docs/demo_sources.md`).

## B. Where each requirement of the brief is met

| Requirement in the brief | Where it is met |
|---|---|
| One module with at least two public sources (or one document plus the product page, with the limitation disclosed) | Demo: C16QS product page, EU Declaration, category page, FAQ, technical specification V2.0 and V2.9 (`docs/demo_sources.md`). The limitation (distributor copies, brochure and manuals not public) is stated in the note and listed in the optional "not accessible" box. |
| Repeatable ingestion and indexing; keep title, URL, type, revision and publication data | Sources tab: "Process the sources" and "Fetch again and re-index" (`docint/fetch.py`, `docint/index.py`); metadata in `data/inventory.json`, sample in `docs/sample_run/` |
| Semantic, keyword or hybrid retrieval; show the retrieved passages | Chat bubble: Options (dense / keyword / hybrid), "How it was found" with dense and keyword ranks (`docint/retrieve.py`) |
| Cited answers with title and location; no invented page numbers | Chat bubble: citations with title, page (PDF) or section (web / FAQ question), revision, date and the supporting passage (`docint/answer.py`) |
| Re-indexing of revised documents; outdated and conflicting sources flagged for expert review | Sources tab, "Add a newer version of this document" on each document card (real files, no simulation) and Expert review tab (`docint/revision.py`, `docint/conflicts.py`) |
| Evaluation set of at least 8 questions: answerable, ambiguous, unanswerable; expected source, output, citation validity, failure category | Evaluation tab (generated from the loaded documents: about 10 answerable + 2 unanswerable); `docs/sample_run/eval_generated.json`; earlier hand-written 25 questions in `eval/` |
| Report of retrieval and answer failures with recommended documentation improvements | Evaluation tab, "Failure report" (generated from the run); sample in `docs/sample_run/`; earlier hand-written report `eval/failure_report.md` |
| Source inventory and metadata sample | `docs/source_inventory.md`, `docs/sample_run/inventory.json`, Sources tab |
| Architecture and validation note, at most 4 pages (source updates, security, accuracy controls, limits) | `docs/validation_note.pdf` (source `docs/validation_note.html`) |
| Source code, setup instructions, 5 to 10 minute demo | This repository, `README.md`; demo recorded by the author (shared Drive folder) |
| Assumptions, third-party services, models, costs and limits, simulated features | README ("Assumptions, services, costs") and note section 6 |
| No API keys; human approval for sensitive actions | Keys only in `.env` (git-ignored); the tool publishes and sends nothing; review decisions need a named person |

## C. What is submitted

- **Repository:** https://github.com/Girik01/cavily_doc_intelligence (code, setup steps, `docs/`, `eval/`, `docs/sample_run/`)
- **Documents:** `docs/validation_note.pdf`, `docs/source_inventory.md`, `docs/demo_sources.md`, `docs/sample_run/`
- **Demo recording:** in the shared Drive folder (recorded from the web interface)
- **Not included:** API keys, the downloaded PDFs and cached pages (`data/versions/`, they are Cavli's documents; the demo sources file lists where to get them)

## D. Points to state openly (they are also in the note and the demo)

1. The technical specification PDFs are third-party distributor copies; the labels V2.0 and V2.9 are typed by the uploader (taken from the file names).
2. The brochure is form-gated; the hardware and AT command manuals need a login. They are not used.
3. Nothing is simulated: the older and the newer version are real files that you give the system.
4. The evaluation is generated from the loaded documents; its questions are written by the model, so it is a sample, not proof of general accuracy. The earlier hand-written 25-question run (22 of 25) is kept in `eval/` as evidence.
5. The citation check covers numbers, not names, and is not per statement. The conflict check compares the 30 most similar passage pairs, so it can miss conflicts.
6. Cost per question was not converted to money (token counts are reported; prices were not checked).
