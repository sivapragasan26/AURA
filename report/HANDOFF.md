# AURA — project and report handoff

Written 5 October 2026. Everything here is either checked against the repository or measured; where a
number came from a run, the run is named.

---

## 1. What exists and where

Two copies of the project. `C:\Users\somanathan\Desktop\Final_year` is the original and has not been
modified. All work is in `C:\Users\somanathan\Desktop\AURA-hosted` on branch `deploy/hosted`.

**Deployed.** The analysis service is live on Render at `https://aura-api-vs7e.onrender.com` (free tier,
so it cold-starts; the extension allows a 60 s wake). The extension went to the **Microsoft Edge**
Add-ons store — Edge rather than Chrome because Chrome's developer registration costs $5. The privacy
policy is published at `https://sivapragasan26.github.io/AURA/privacy.html`.

**Correction to earlier advice:** an earlier version of this document said to set
`AURA_ALLOWED_ORIGINS` to the Edge extension id once the listing was live. Do not. That variable
replaces the default rather than adding to it, so naming one id refuses every other install - it took
the Chrome copy offline with `ORIGIN_NOT_ALLOWED` until it was removed again. Leave it unset: the
default already accepts extension origins and refuses web pages.

**Not committed yet.** `git status` on `deploy/hosted` shows the three benchmark fixes (section 3) and
the whole `report/` directory as uncommitted. The fixes change no API shape, but the browser end-to-end
suites should be re-run before anything is redeployed to the live service.

---

## 2. Report files

In `AURA-hosted/report/`:

| File | What it is |
| --- | --- |
| `AURA_Report_Manuscript.md` | **The complete report text** — front matter, all six chapters, references, appendices. ~10,400 words. This is the file to hand to another tool to produce the .docx. |
| `APPENDIX1_CODE.txt` | Appendix 1's source listings, 711 lines, pulled from the repository. |
| `figures/*.png` | The seven diagrams and charts, referenced by `[FIGURE n.n]` markers in the manuscript. |
| `content_part1.py`, `content_part2.py` | The report content as data — edit here, not in the generated files. |
| `make_figures.py` | Draws the figures; the two benchmark charts read `benchmark_result.json`, so re-measuring redraws them. |
| `make_manuscript.py` | Regenerates the manuscript and the appendix code file from the content modules. |
| `export_content.py`, `build_docx.js`, `paginate.ps1` | The local .docx pipeline (section 5). |
| `benchmark_result.json` | The measured benchmark, 5 Oct 2026. |
| `build/AURA_Project_Report.docx` | A built .docx, complete in content, **with blank page-number columns** in the contents and the two lists. |

---

## 3. The three defects found while measuring, and fixed

Re-measuring the benchmark for Chapter 5 exposed three real bugs that 571 passing tests had not caught.
All three are fixed and covered by tests.

1. **`aura/agent/groq_provider.py`** — the retry that lowers the output budget when a request exceeds a
   per-minute limit was guarded by a floor of 1024 tokens, while Groq's free tier states a limit of
   1000. The retry could therefore never fire for the accounts that needed it, and two of five suites
   lost their AI analysis entirely. The floor is now `MIN_OUTPUT_BUDGET = 512`.
2. **`aura/agents/browser_agent.py`** — the page-state signature was `document.body.innerText` alone, so
   a control that toggled a class or an `aria-expanded` attribute was recorded identically to a dead one.
   It now covers element count, the attributes that carry interface state, and the address — deliberately
   not focus, which every click changes.
3. **`aura/findings/aggregation.py`** — AURA collected proof of dead controls and then discarded it: the
   interaction records reaching the model were indistinguishable lines, and three prompt variants failed
   to make the model use them. A control that was clicked and did nothing is *measured*, like an axe
   violation, so `convert_interaction_outcomes` now reports it deterministically as LIKELY (not
   CONFIRMED — a click can legitimately do something unobservable).

Prompt tuning was stopped after three variants, because going further would have been fitting the
benchmark rather than fixing the system.

---

## 4. The measurement (Chapter 5)

Measured 5 October 2026, Groq `qwen/qwen3.8-27b`, against the 31 deliberately seeded defects of the five
Test Lab suites.

| Suite | TP | FP | FN | Precision | Recall |
| --- | --- | --- | --- | --- | --- |
| 01 Accessibility | 3 | 4 | 3 | 42.9% | 50.0% |
| 02 UI/UX | 3 | 3 | 3 | 50.0% | 50.0% |
| 03 Navigation and interaction | 1 | 5 | 5 | 16.7% | 16.7% |
| 04 Responsive and runtime | 4 | 4 | 2 | 50.0% | 66.7% |
| 05 Mixed realistic | 4 | 6 | 3 | 40.0% | 57.1% |
| **Aggregate** | **15** | **22** | **16** | **40.5%** | **48.4%** |

F1 **44.1%**. 37 findings reported, 31 defects seeded. Pre-fix the figure was TP 15 / FP 20 / FN 16
(P 42.9%, R 48.4%, F1 45.5%) — **the fixes did not move the aggregate**, and Chapter 5 says so plainly.
They fixed real defects: two suites that previously returned no analysis now return it, and dead
controls are now named.

**Method matters.** Each suite must be audited **separately**, with `AI_MAX_OUTPUT_TOKENS=900` and ~65 s
between suites. Five back-to-back audits exhaust Groq's free-tier allowance of 1000 output tokens per
minute; the throttled suite then returns nothing and consecutive whole-benchmark runs disagree, so a
whole-run number is not a measurement.

**Four reasons the headline understates detection**, all in Chapter 5 §5.4:

- A "false positive" here means "not one of the 31 seeded defects", not "wrong". The suites contain real
  problems their authors did not seed, and correctly reporting one counts against the system.
- **Vocabulary mismatch.** AURA reports a control it operated to no effect as `non_responsive_control`.
  The evaluator's alias table (`aura/evaluation/evaluator.py`) relates that only to `dead_button` — not
  to `broken_menu` or `broken_form_submission`, which two of suite 03's seeded defects carry. A correct
  detection on the right element therefore scores as a false positive *and* leaves a false negative.
  This is documented as a limitation rather than fixed, because fixing it would raise the score.
- **One defect is unreachable by design.** GT-INT-001 is seeded on a button labelled "Execute Balance
  Transfer", and `aura/browser/interaction_policy.py:20` refuses to click anything matching "transfer".
  Correct safety behaviour producing a permanent false negative.
- Recall is bounded by what the model chooses to report; it favours visual observations over measured
  interaction failures, which is why defect 3 above was fixed by moving that class to deterministic
  reporting rather than by more prompting.

Other measured facts quoted in the report: a live scan through the public service took **7.0 s with
Groq** and **29.4 s with Gemini**; the test suite is **571 passed, 13 skipped**; the codebase is 15,180
lines of engine, 3,470 of extension and 11,942 of test code (recomputed by `export_content.py`, so it
cannot drift).

---

## 5. The local .docx pipeline, and the one thing left undone

`export_content.py` flattens the content to JSON → `build_docx.js` renders it with the `docx` npm
package → `paginate.ps1` drives Word to measure real page numbers → rebuild so those numbers land in
the contents table.

```bash
cd /c/Users/somanathan/Desktop/AURA-hosted && python report/export_content.py && NODE_PATH=report/build/node_modules node report/build_docx.js
```

**What is not finished:** the page-number columns in the table of contents and in the lists of figures
and tables are blank. They were deliberately not estimated. `paginate.ps1` was meant to fill them, but
it walks Word's paragraph collection over COM — about 1,100 paragraphs, 700 of them appendix code lines
— and that took over 25 minutes and was killed before writing anything. Narrowing which paragraphs get
queried did not help, because the cost is the per-paragraph COM round trip itself.

**The fix, if the local pipeline is continued:** have Word do one call only —
`$doc.ExportAsFixedFormat($pdf, 17)` — then locate every heading's page by reading that PDF with
`pymupdf`. The numbers are identical, because the PDF is the rendered document, and it takes seconds
rather than half an hour. Note that LibreOffice and `pdftoppm` are **not** installed on this machine, so
the usual `soffice --headless --convert-to pdf` route does not work here; Word COM and `pymupdf` (in the
session scratchpad virtualenv) are what is available. Kill any orphaned headless `WINWORD` process
before rebuilding or the write fails with `EBUSY`.

---

## 6. To generate the document elsewhere

Attach these to a new conversation:

1. `report/AURA_Report_Manuscript.md` — the content, with a formatting preamble at the top
2. `report/APPENDIX1_CODE.txt` — Appendix 1's listings
3. the seven PNGs from `report/figures/`

Then ask for a Word .docx built to the preamble's spec. The preamble covers page size and margins,
fonts, heading styles, caption placement, table shading, the roman-then-arabic page numbering with its
continuous count, the order of the ten front-matter pages, and the ~56-page target.

Two things to insist on: the contents and the lists of figures and tables must be **three-column tables
with real page numbers**, not a generated TOC field, because that is what the template does; and
**Chapter 5's numbers must not be changed** — they are measured, and a figure that cannot be reproduced
in front of an examiner is the one thing that can sink a viva.
