# Failure report and recommended documentation improvements

Evaluation: 25 questions (10 answerable, 3 ambiguous, 5 unanswerable, 4 conflict, 3 revision). **Latest run with gpt-5.5 (from the web interface): 22 passed, 3 failed (B3, R2, R3).** Four gpt-5.5 runs of the same 25 questions scored 23, 22, 21 and 22: B2 and B3 flip between runs, R2 and R3 fail every time (`eval/results.md` has every observed output). The same questions run earlier with gpt-5.4-mini scored 21 of 25 (B2, B3, R2, R3 failed); those rows are kept below as history because they show real weaknesses that a stronger model hides but does not remove.
Retrieval check (an expected source is in the top 8, 20 questions that have one): dense 17/20, keyword 16/20, hybrid 17/20. On this small set hybrid does not beat dense; it was kept for exact identifiers (standard names, SKUs), but that benefit is **not shown** by this evaluation.

## A. Failures of the system (B2 failed with gpt-5.4-mini only; B3 failed with gpt-5.4-mini and in the latest gpt-5.5 run, but passed in an earlier gpt-5.5 run; R2 and R3 fail with both)

| ID | What happened | Failure category | Root cause | Recommended fix |
|---|---|---|---|---|
| B2 "Is the C16QS certified?" | Answered "Yes" without asking which region or variant. It listed certifications (CE, FCC, ...) and cited the spec's **page 6 (Product Variants)**, but the certification list is on **page 4**. | ambiguity not flagged + citation error | The citation check verifies **numbers** only. Names such as FCC or CE are not checked against the cited passage, so a wrong page slipped through. Certification also depends on region and variant, which the model did not raise. | Extend the check to named entities (acronyms, SKUs, standard names). Check each sentence against the passages cited in that sentence, not the union. Stronger rule for "is it X?" questions. |
| B3 "What is the maximum current consumption?" | Latest gpt-5.5 run: answered from the revision-change review note (Tx peak 620 -> 650.88 mA) without asking which operating state is meant, so the ambiguity was not flagged. gpt-5.4-mini: refused ("no valid citation") although the spec has Tx peak, idle, sleep and GNSS currents. | false refusal (retrieval miss + empty citation) | "Maximum current consumption" does not appear in the document. The table uses "Tx Peak", "Sleep Mode". The right passage was not in the top 8, and the draft answer then had no valid label. | Add a small glossary or query expansion for electrical terms, or index a short normalised summary per spec section. |
| R2 "What temperature did the older V2.0 state?" | Correct fact (-30 °C to +85 °C) but cited only the review items, not the V2.0 page. | citation granularity | Review items carry quotes but no page number, so the answer is true but loses page-level traceability. | Store the source passage id (document, version, page) inside each review-item evidence and let the answer cite it. |
| R3 "What changed between V2.0 and V2.9?" | Correct list of changes (sleep current TBD to 11 µA, Tx peak 620 to 650.88 mA, pin count 102, temperature -30 to -40 °C, 7 regions, new certifications), cited only the review item. | citation granularity | Same as R2: the change list is derived by the pipeline and not tied to pages. | Same fix as R2. |

### A2. Citation errors found after the gpt-5.4-mini run (not in the 25-question score)
Found while testing the demo commands with gpt-5.4-mini. Re-tested with gpt-5.5: the sleep-current answer now cites only the right page (spec V2.9 page 4) and the old-version temperature question still cites the review items instead of the V2.0 page. They show that **passing the automatic checks does not guarantee the cited page is the right one**.

| Question | Observation | Why the check missed it |
|---|---|---|
| "What is the sleep mode current?" | Correct value (11 µA, spec V2.9 page 4), but the answer also said the *category page* shows "Sleep Mode (Hibernate) 11 µA" and cited its comparison table. That table has no sleep-mode row. | The figure 11 appears in another cited source, and the check compares figures with the **union** of all cited text, not with the passage cited for that statement. |
| "What operating temperature did the older V2.0 state?" (`--include-superseded`) | Correct value (-30 °C to +85 °C) but cited V2.0 **page 5**; the temperature is on page 3. | Same reason: figures are not tied to the specific cited passage. |

Fix (not done, deadline): verify every statement against **the passages it cites**, drop a citation whose passage does not contain the statement's figures or names, and re-attach the passage that does. Until then, the citation granularity is passage-level only when the answer cites a single source; treat multi-source citations as approximate.

Passed on purpose (the system behaves as designed; with gpt-5.5 also B2 (and B3 in one of two runs), which then ask which region/variant and which operating state): all 5 unanswerable questions got "Not verified" and, where relevant, the name of the inaccessible document (AT manual, hardware manual); all 4 conflict questions reported both sides and the review items; the stale-version checks (A8 sleep current must be 11 µA, not "TBD"; R1 must not say 5 variants) passed.

Bugs found and fixed while testing (before the final run): the figure check refused correct band answers because tables print `12/ 13/ 25` and answers print `12/13/25` (fixed by normalising slashes); a review item's own summary ("17 differences") was not counted as citable text (fixed); a footnote-icon filter hid the whole variants table on the last page of V2.9 (fixed: icons are 5 pt, the table uses 6 pt).

## B. Ill-defined question found by the test
R1 first asked "how many variants". The document answers "7 variants" (regions, page 2) and also lists **28 type designations** (page 6). The system answered 28; the test expected 7. The question was reworded to "regional variants". This is a documentation ambiguity, see C6.

## C. Recommended documentation improvements for Cavli
1. **State the version and date inside each PDF** and publish a revision history. The technical specification PDFs state no version (V2.0 and V2.9 exist only in file names); the product and category pages state no date. Today it cannot be proven which source is newest.
2. **Publish the technical specification on cavliwireless.com.** Only third-party distributor copies are public; the brochure link is behind a form and the hardware and AT manuals need a login. Users cannot verify authenticity.
3. **Reconcile the numbers that disagree** (see `data/review_queue.json`): North America bands (13 only in the PDFs; 25 added in V2.9; the product page omits 13), WW band 13, Latin America bands (category page vs product page), operating temperature (-30 °C in V2.0, -40 °C in V2.9, -45 °C on the category page), and "EA" meaning.
4. **Fix the EU Declaration of Conformity:** it names only the 4 WW type designations while 28 are listed in the specification and 14 on the product page; the embedded PDF title says "Declaration of Authorization"; the object statement says "Mobile Phone" while the product is an "LTE MODEM".
5. **Make the spec tables machine-readable.** Footnote icons (1 = Optional, 2 = Needs SDK, 3 = In Progress) are tiny digits that cannot be tied to a cell, V2.0 repeats every row in five regional columns, and certifications are not mapped to variants. Use text labels per cell and a tagged PDF.
6. **Define "variant" once** (regional variant vs orderable type designation) and use the same region codes everywhere ("South-East Asia" in the summary vs "Australia, New Zealand, Taiwan and South Korea" in the AN definition).
7. **Replace "TBD"** (sleep current, Tx values for AN, LA and WW in V2.0) with values or a date, and name electrical values with the terms engineers search for ("maximum current", "sleep current").

## D. Limits of this evaluation
25 questions written by the author from the indexed documents; one model per run (gpt-5.5 final, gpt-5.4-mini earlier), one run per question (wording can vary between runs); the retrieval comparison is small (20 questions) and shows no hybrid gain; no human judged answer quality beyond the automatic checks, and the citation check covers numbers, not names, and is not per statement (see B2 and A2).
