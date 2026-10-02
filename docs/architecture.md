# AURA architecture (V0.5: extension-first)

AURA is a hybrid runtime UI/UX assurance system. Deterministic evidence plus AI semantic reasoning plus
independent verification produce final findings. The **Chrome extension is the primary product**. The
Streamlit dashboard and the Test Lab are supporting and evaluation infrastructure. There is **one engine**.

```
 Chrome extension (side panel)          Streamlit dashboard (app.py)        Test Lab runner
  evidence from the user's own tab       Playwright collection               sequential Run All
            │  HTTP 127.0.0.1 + token             │                                  │
            ▼                                     ▼                                  ▼
       aura/api (Starlette)  ──────────►  AURAOrchestrator  ◄──────────────────────────
                                   analyze_evidence(bundle)   run_audit(url)
                                              └──────────┬───────────┘
                                                _analyze_collected  (single pipeline)
            runtime classification → AI candidates → verification → correlation → scoring → report
                                                          │
                                   Test Lab only: EvaluationEngine (ground truth read from disk)
```

## Module map

| Concern | Module | Notes |
|---|---|---|
| Orchestration | `aura/agents/orchestrator.py` | `run_audit` (Playwright collect) and `analyze_evidence` (extension bundle) both call `_analyze_collected` |
| Evidence bundle (extension) | `aura/evidence/bundle.py` | Pydantic model; strips query strings, redacts secrets, bounds sizes, rejects unknown fields |
| DOM evidence | `aura/analyzers/js/dom_extraction.js` + `dom_analyzer.py` | One script shared by Playwright and the extension (`summarize()` post-processing) |
| Accessibility | `aura/analyzers/accessibility_analyzer.py` + `aura/vendor/axe.min.js` | axe-core 4.8.2 vendored; the extension bundles the identical file |
| Runtime telemetry | `aura/browser/runtime_collector.py`, `aura/analyzers/runtime_analyzer.py` | Classification (APPLICATION / THIRD_PARTY / …) is server-side for both collectors |
| Interaction policy | `aura/browser/interaction_policy.py` | Level-B (Playwright) and the stricter live-session policy (extension: clicks only) |
| AI candidates | `aura/agent/*` | Providers: Mock, Gemini, OpenAI, Anthropic, Groq; focused evidence packet |
| Provider state / pacing | `aura/agent/provider_status.py`, `aura/agent/pacing.py` | Preflight never runs an inference; pacing uses provider-reported headers only |
| Verification | `aura/verification/*` | Independent of AI; target-specific interaction evidence. `materiality.py` decides whether a UI/UX claim is backed by measurements |
| Correlation | `aura/evidence/correlator.py`, `aura/findings/aggregation.py` | Canonical findings F-001… |
| Scoring | `aura/scoring/*` | When AI did not run, UI/UX are N/A and the overall uses accessibility + runtime only |
| Provider selection | `aura/api/provider_config.py` | Provider + model for the NEXT scan; API keys kept in the server process only, never returned, never logged |
| Plain wording | `aura/api/plain_language.py` | Human sentences per rule for the panel; rule ids stay in technical details |
| API | `aura/api/*` | Local-only, pairing token, origin + host checks, 12 MB limit, AI concurrency 1 |
| Assistant | `aura/assistant/explain.py`, `chat.py` | Explain = grounded, no AI request. Ask AURA = 1 request, GT-free context, citations validated |
| Test Lab | `test_lab/`, `aura/evaluation/*` | 5 suites; `ground_truth.json` read from disk only (the HTTP server refuses to serve it) |
| Extension | `extension/` | MV3, side panel, plain ES modules, no build step |

## Semantic model (unchanged)

AI candidate (hypothesis) ≠ deterministic finding (axe-core / telemetry / DOM measurement) ≠ verification result ≠
final (canonical) finding ≠ benchmark TP. The extension shows only final findings. Each one is labelled with its origin
(deterministic vs AI-detected), its verification status (confirmed / likely / uncertain) and its AI contribution type
and score. Rejected AI candidates are listed separately as "not problems".

## Extension security model

- Permissions: `sidePanel`, `activeTab`, `scripting`, `storage`. Host access only to the local AURA server.
  There is no `<all_urls>`, `tabs`, `debugger`, `cookies` or `history` permission and no automatic content scripts.
- Page access comes only from `activeTab`. Clicking the AURA toolbar icon on a tab is handled by
  `chrome.action.onClicked` in the service worker. The handler opens the side panel and records the tab as
  activated (`extension/activation.js`: tab id, origin and time only, in `chrome.storage.session`).
  `openPanelOnActionClick` is kept **false**. With `true`, Chrome opens the panel itself, never dispatches
  `onClicked` and does not grant `activeTab` (the V0.5.0 "no access" bug).
- The side panel asks the service worker `GET_TAB_STATE` for the current tab. The answer is verified with a
  no-op script injection, because `chrome.permissions` cannot see activeTab grants. Scan is enabled only for
  ACTIVATED tabs. The other states are NOT_ACTIVATED, ACCESS_LOST (the tab moved to another origin) and RESTRICTED.
  The grant survives same-origin reloads and ends on cross-origin navigation, tab close or extension reload.
  Real-browser test: `tests/extension_activation_e2e.py` (CDP `Extensions.triggerAction`, extension unmodified).
- Collected: DOM structure and geometry, visible text snippets (≤100 chars per element, redacted), axe results
  (no HTML snippets), runtime errors raised *during* the scan, failed resource loads (Resource Timing), and one
  viewport screenshot. Never collected: typed field values, passwords, cookies, storage or history.
- Provider API keys stay on the server. The extension stores only the server URL and the pairing token.
- Highlight draws in a closed Shadow DOM, changes inline styles only, and is removed on demand,
  when switching findings, and when the panel closes.

## Test Lab

Run All is sequential (suite N+1 starts only after suite N completes; AI concurrency 1) via
`aura/evaluation/test_lab_runner.py`, used by both dashboard buttons. Between suites it waits (bounded) for
provider-reported capacity: the Retry-After cooldown, and remaining tokens/min compared with the previous
request's reported usage. If the provider becomes unavailable mid-run, completed suites keep their results and
the rest are reported as NOT_EVALUABLE ("not run"), with no invented TP/FP/FN.

Groq 429/413 responses are classified from the provider's own message: `RATE_LIMITED_{RPM,TPM,OTPM}`,
`QUOTA_EXHAUSTED_{RPD,TPD}`, `REQUEST_TOO_LARGE_*`. An oversized request is never retried unchanged; an output
budget above a stated OTPM limit is retried once with a smaller `max_completion_tokens`.

## Finding quality (Phase 3)

An AI candidate is a hypothesis. `aura/verification/materiality.py` asks whether the collected evidence actually
shows the claimed condition, and the UI/UX branch of the rules engine acts on its verdict:

| Verdict | Meaning | Status |
|---|---|---|
| SUPPORTED | measurements show the condition (prominence comparison, density counts, geometry) | CONFIRMED |
| JUDGEMENT | the target is verified but the claim is a design opinion evidence cannot settle | LIKELY |
| WEAK | nothing in the evidence supports the claim | UNCERTAIN |
| NOT_A_DEFECT | evidence shows it is harmless, or a deterministic detector already reported it | REJECTED |

AI confidence is never evidence: the old rule confirmed any claim whose element existed and was visible. Blank
space, "unusual" layouts, hidden-but-duplicated responsive content and claims that restate an axe-core finding
on the same element are rejected unless a measured consequence (overlap, clipping, overflow, interaction error,
runtime error) is present. A navigation claim needs an obstruction, dead link, failed interaction or wrong
destination; an existing element is not enough.

Real-world comparison (identical AI response replayed through the old and the new rules):
`python tests/flipkart_quality_compare.py --provider gemini`.

## Side panel structure (Phase 3)

Product wording first, engineering detail behind disclosure: score card (AURA score plus four sub-scores and
"Why these scores?"), severity filter, finding cards (severity, category, plain headline, verification +
detector, short why, target), finding detail (what was detected / why it matters / what to do / where, actions,
then a collapsed "Technical details" with selector, rule, verification score, AI confidence, evidence sources
and audit id). Processing steps live under "Technical processing"; evidence coverage has a "What does this
mean?" explanation. Mock AI is always labelled "Mock AI · Demo".

## Known limitations

- **Load-time runtime errors:** the extension attaches after the page has loaded, so console errors and
  exceptions raised during page load are not captured (failed network loads are). The coverage notes say so.
  Future option: an opt-in "reload & capture" using `chrome.debugger`.
- **Targeted re-interaction:** after the AI step, the Playwright path re-clicks AI-referenced controls. The
  extension path does not, so interaction claims can stay UNCERTAIN.
- **Frames:** iframes and shadow-DOM axe targets are not scanned or highlighted.
- **Streamlit** remains the dashboard. A React dashboard on the same API is the next step (Phase D).
- **Event-driven monitoring** is not implemented. The extension architecture keeps it possible: page events
  → a debounced re-scan request through the same `/api/audits` endpoint.
