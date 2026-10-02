# Prompt: AURA Chrome Extension + "Ask AURA" Website Chatbot

Copy everything below the line into your coding agent.

---

You are working on **AURA (Autonomous UI/UX Runtime Assurance)**, a final-year research project at `C:\Users\somanathan\Desktop\Final_year`. Today it is a Python 3.12 app (venv: `.venv`) with a Streamlit UI (`app.py`). It audits a URL with Playwright, sends the evidence to Gemini for candidate findings, verifies those candidates against browser evidence, then aggregates and scores them. It also has a ground-truth benchmark (`test_lab/`, served at `127.0.0.1:8999` by `test_lab/launcher.py`).

**Goal:** turn AURA into a **Chrome extension** that a website owner installs to audit the page open in their own tab. That includes logged-in pages, localhost and staging. The extension also gets a built-in chatbot, **"Ask AURA"**, which answers questions about the user's own website using the audit evidence. It can show a live preview of how the page would look after the UI/UX fixes it suggests.

**Architecture decision (already made, do not revisit):** keep the Python engine and replace only the edges.

- **New:** `extension/`, a Manifest V3 Chrome extension in plain JavaScript with ES modules and no build step. It collects the evidence and shows the UI.
- **Changed:** the Python engine is exposed through a local **FastAPI** server (`aura/api/`). The Streamlit app and Playwright mode stay working as the "headless / benchmark mode".
- **Reused, not rewritten:** `aura/verification/`, `aura/findings/`, `aura/scoring/`, `aura/agent/`, `aura/evaluation/`, `test_lab/`.

## Hard rules (non-negotiable)

1. **Inspect before changing.** Read the relevant modules first. Make minimal, targeted changes. Do not rewrite modules on the reuse list; only add adapters around them.
2. **Ground truth isolation.** Ground truth (the `aura-ground-truth` script tags and any evaluation data derived from it) must never reach AI prompts, the verifier, or the chatbot context. Add a test that proves this for the chat context.
3. **No fabrication.** If the AI provider fails or runs out of quota, return an explicit `NOT_EVALUABLE` or error state. Never invent findings, counts, scores or chat answers.
4. **Do not downgrade the Gemini model** (`gemini-3.6-flash`) to dodge errors.
5. **Keep semantics distinct:** AI candidate ≠ verified finding ≠ canonical finding ≠ benchmark TP. The UI and the chatbot must never present an unverified candidate as a confirmed bug.
6. **Quota awareness.** Gemini free tier is 20 requests/day. Use the mock provider for all automated tests and development. Each audit costs 1 request and each chat message costs 1 request; show this in the UI. Do not make live Gemini calls unless I explicitly ask.
7. **Git.** The git repo root is my HOME directory, not the project. Do not commit, init or push anything without asking me.
8. **Work in phases.** After each phase, stop and report: files changed, tests run with results, what is not done, and any decision you need from me. Do not start the next phase until I say so.

## Phase 0: Fix verifier integrity (before any new UI shows "verified" results)

Confirm each issue still exists, fix it minimally, and add a regression test for each:

- `aura/verification/rules.py` / `evidence.py`: INTERACTION/NAVIGATION claims are CONFIRMED merely because the target exists in the DOM. They must require interaction evidence for that specific element, such as a click result, a navigation response, or an error after the click.
- The "interaction" evidence flag is set if ANY element was interacted with. It must be per-element.
- Responsive claims are CONFIRMED whenever the document overflows at all. Tie confirmation to the claimed element or region overflowing.
- The generic absence rule REJECTS claims that contain the word "hidden" (e.g. "visually hidden behind") when the element is visible. Fix the keyword matching.
- `browser_agent.execute_controlled_interactions` spends its 5-action budget hovering header/nav. Prioritise elements referenced by AI candidates and primary buttons.
- **Do not fix, ask me:** GT-MIX-007 expects `application_runtime_exception`, but the suite 05 fixture only emits `console.error`. I decide whether the fixture or the GT changes.

Run the full pytest suite and the Test Lab with the mock provider. Report benchmark numbers before and after. A lower, accurate number is acceptable.

## Phase 1: Engine API (FastAPI)

- Split the orchestrator into **collect** and **analyze** steps. Define one Pydantic `EvidenceBundle` model that both the Playwright collector and the extension produce. It contains: `source` (`extension` | `playwright`), `collector_version`, `url`, `title`, `viewport`, `dom_summary` (same shape `dom_analyzer.py` produces today), `axe_results`, `telemetry` (console messages, runtime exceptions, failed/4xx/5xx network requests), `responsive_checks`, `interaction_log`, `screenshot_png_base64`, and `captured_at`.
- Add `orchestrator.analyze_evidence(bundle) -> AuditResult`. The existing `run_audit(url)` becomes "collect with Playwright → `analyze_evidence`". All existing tests must still pass.
- Endpoints in `aura/api/server.py`:
  - `GET /api/health`: engine version, provider name, remaining daily quota if known.
  - `POST /api/audits`: accepts an `EvidenceBundle` and returns an `AuditResult` (verified findings with IDs, rejected candidates labelled as such, scores including NOT EVALUATED states, evidence coverage).
  - `GET /api/audits/{audit_id}`: stored result, persisted under `runs/` like today.
  - `POST /api/audits/{audit_id}/chat`: Phase 6.
  - `POST /api/audits/{audit_id}/remeasure`: Phase 6.
- **Security:**
  - Bind to `127.0.0.1` only.
  - Allow CORS only for `chrome-extension://<id>`, configurable in `.env`.
  - Require a pairing token: generated on first start, printed in the console, and pasted once into the extension options page.
  - Enforce request size limits.
  - The API key stays on the server and never goes to the extension.
- Add a run command, update `.claude/launch.json` and the README, and add pytest tests using FastAPI's TestClient with the mock provider.

## Phase 2: Extension skeleton + DOM/accessibility evidence

- `extension/manifest.json` (MV3). Permissions: `activeTab`, `scripting`, `sidePanel`, `storage`, `debugger`. Request host access only through `activeTab`/optional permissions; do not request `<all_urls>` up front.
- **Side panel UI:**
  - "Audit this page" button with a progress display.
  - Findings list grouped by category (UI, UX, Accessibility, Runtime, Responsive, Interaction), showing severity, verification status and evidence.
  - Score card showing NOT EVALUATED where it applies.
  - Options page for the backend URL and pairing token.
- **Content script** that ports the `dom_analyzer.py` logic to JS so it produces the **same `dom_summary` shape**. It must generate a stable CSS selector for each referenced element.
- **Bundle axe-core locally** in `extension/vendor/`. MV3 forbids remotely hosted code.
- **Privacy:**
  - Never collect input values, password fields, or cookies/localStorage.
  - Strip query strings from collected URLs unless I enable it.
  - Show a one-line notice in the panel that evidence and a screenshot are sent to the local AURA engine and then to the AI provider.

## Phase 3: Runtime and responsive evidence via `chrome.debugger` (CDP)

- Attach `chrome.debugger` to the active tab and enable the `Runtime`, `Log` and `Network` domains. Collect:
  - `Runtime.consoleAPICalled` (errors/warnings)
  - `Runtime.exceptionThrown`
  - `Log.entryAdded`
  - `Network.loadingFailed`
  - responses with status ≥ 400
- Load-time errors are only captured if the debugger is attached before load. Offer an **"Audit with reload"** option that attaches the debugger, then reloads the page, then collects. Explain the trade-off in the UI.
- **Responsive check:** use `Emulation.setDeviceMetricsOverride` at 390×844. Measure horizontal overflow and record which elements cause it, then **always restore** the original metrics.
- Take the screenshot with `Page.captureScreenshot`.
- **Always detach the debugger**, including on errors. Chrome shows a "being debugged" banner; mention this in the UI.
- Telemetry classification (APPLICATION / THIRD_PARTY / ENVIRONMENT / BROWSER) stays in the Python `runtime_analyzer.py`.
- **Parity check:** for each `test_lab` suite, compare the evidence from the extension path with the Playwright path. Report the differences. Do not tune the verifier to hide them.

## Phase 4: On-page overlay

- Clicking a finding scrolls to its element and outlines it on the page, with a small label showing the finding ID and title.
- A "Show all" toggle outlines every verified finding.
- The overlay lives in a Shadow DOM so it cannot break or be styled by the site. It is removed completely when the panel closes.

## Phase 5: Safe controlled interactions (opt-in)

- Port `aura/browser/interaction_policy.py` to the extension and make it **stricter**, because this runs on the user's real site with their real session:
  - never submit forms
  - never click elements whose text or attributes suggest delete, remove, pay, buy, checkout, logout, unsubscribe, send, or confirm
  - never type into inputs
  - never follow links to other origins
- Interactions are **off by default**. Before running, the panel lists exactly which elements will be clicked or hovered.
- Record per-element results (what was clicked, what changed, any errors or navigations) in `interaction_log`. Phase 0 depends on this data being per-element.

## Phase 6: "Ask AURA" chatbot + UI/UX change preview

A chat tab in the side panel lets the user ask about **their own website**, for example:

- "What errors does my site have and where?"
- "Why is my signup button failing?"
- "What's wrong on mobile?"
- "How would the page look if I fixed the contrast?"

### Grounded context (built server-side in `aura/chat/`)

- For the selected audit, the context contains:
  - page URL and title
  - verified findings with IDs, selectors, evidence and severity
  - rejected or unverified candidates, **clearly labelled as unverified**
  - scores and NOT EVALUATED states
  - evidence coverage (what was and was not collected)
  - a compact telemetry summary
- **Excluded:** ground truth and anything derived from it (benchmark TP/FP/FN, precision/recall), raw screenshots beyond the one the audit already used, and API keys.
- Keep the last N turns of chat history within a token budget. Put the context builder in its own module so it is unit-testable.

### Answer contract

The model must return JSON validated by a Pydantic schema:

```
{
  "answer_markdown": str,
  "cited_finding_ids": [str],
  "cited_selectors": [str],
  "suggested_changes": [
    { "finding_id": str, "selector": str, "css": str, "html_note": str, "rationale": str }
  ],
  "evidence_gaps": [str],
  "confidence": "high" | "medium" | "low"
}
```

### Grounding rules (system prompt + server-side enforcement)

- Only verified findings may be stated as facts. Unverified candidates must be described as "possible, not verified".
- If a question is about something AURA did not collect evidence for, say so and list it under `evidence_gaps`. Suggest re-auditing with the relevant option instead of guessing.
- The extension cannot see source code. **Never invent file names or line numbers.** Refer to elements by selector and visible text.
- Subjective design opinions must be labelled as opinions, not measurements.
- **Server-side validation:**
  - Drop any cited ID or selector that does not exist in the audit.
  - Reject CSS that contains `url(`, `@import`, `expression(`, or `javascript:`.
  - If the provider fails, return an error message. **Never a fabricated answer.**

### Chat UI

- Cited finding IDs render as chips. Clicking a chip highlights the element on the page using the Phase 4 overlay.
- Show a "1 AI request" cost note and the remaining daily quota near the input.

### "Preview this change" (how the site would look after the UI/UX fix)

- Each `suggested_change` gets a **Preview** button. It applies the CSS to the live tab with `chrome.scripting.insertCSS`, scoped to the selector. This change is temporary and only in this tab; it disappears on reload.
- Provide a **Before / After** toggle with a screenshot of each state side by side, a **Revert all** button, and **Copy CSS / Download patch** for the user to apply in their own code. AURA never modifies the user's site files.
- **Re-measure, don't predict.** After a preview, re-run only the deterministic checks locally: axe-core (contrast, target size, names), horizontal overflow, and whether the element is visible and within the viewport. These cost no AI request. Show measured deltas, e.g. "color-contrast violations: 5 → 1" and "mobile overflow: 42px → 0px".
- Label this **"Re-measured on preview (deterministic checks only)"**. Do not show an AI-predicted score. A full re-audit of the previewed state is an explicit button that costs 1 AI request.
- `POST /api/audits/{audit_id}/remeasure` stores the before/after measurements next to the original audit so the improvement is traceable.

### Tests (mock provider only)

- The context builder never includes ground-truth or evaluation fields; test this on a `test_lab` audit.
- Citations to non-existent finding IDs or selectors are dropped.
- Unsafe CSS is rejected.
- Provider failure returns an error, not an answer.
- Unverified candidates appear labelled as unverified in the context.
- The remeasure endpoint stores before/after correctly.

## Out of scope for now

Chrome Web Store publishing, cloud hosting of the engine, user accounts, and multi-page crawling.

## Deliverable at the end of each phase

- Summary of what changed
- Files changed
- Exact commands to run the engine, load the unpacked extension (`chrome://extensions` → Developer mode → Load unpacked → `extension/`), and run the tests
- pytest results
- Known limitations
- Decisions you need from me

Start with Phase 0: inspect the listed files, confirm each issue, and propose the fixes before editing.
