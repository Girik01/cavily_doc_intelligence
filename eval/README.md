# eval/

`questions.json`, `results.json`, `results.md` and `failure_report.md` are an **earlier, author-written** 25-question evaluation (22/25) that was run
on the original Cavli C16QS source set (product page, EU Declaration, category page, technical specification V2.0 and V2.9). They are kept as evidence
and are not used by the application any more.

The application now **generates its evaluation from whichever documents are loaded** (`eval/generate.py`, Evaluation tab), so it keeps working when
the sources change. `run_eval.py` still provides the grading rules (`grade`, citation validity) that the generated evaluation uses.
