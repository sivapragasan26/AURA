# AURA — Autonomous UI/UX Runtime Assurance (V0.4)

AURA is an agentic AI platform that analyzes running web applications at runtime to identify UI, UX, accessibility, responsiveness, interaction, and runtime performance issues.

## 🚀 What is AURA?

AURA operates on the core principle:
> **AI Proposes. Evidence Supports. Verification DecDecides.**

Unlike platforms that blindly trust LLM design opinions, AURA treats AI output as **Candidate Findings** and independently verifies them using physical browser evidence (DOM element existence, bounding box geometry, visibility status, axe-core WCAG violations, and classified console/network telemetry).

---

## 🧩 Chrome Extension (primary product, V0.5)

AURA runs as a Chrome side panel that scans **the page you are on**, including localhost, staging and pages
you are signed in to. You don't need to paste a URL. See [docs/architecture.md](docs/architecture.md).

This branch is the **hosted** build: the extension talks to an AURA service rather than only to a server on
your own machine, and **the AI call happens in your browser with your own API key**. The service verifies
findings against the evidence and holds no credential of yours. What goes where is set out in
[PRIVACY.md](PRIVACY.md) and enforced by `tests/test_log_privacy.py`, `tests/test_audit_isolation.py` and
`tests/test_hosted_deployment.py`.

1. In Chrome, open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked** and select the
   `extension/` folder. (Icons are generated, not committed: run
   `python -m aura.tools.sync_extension_assets` first, or `python -m aura.tools.package_extension` to build
   a zip that is ready to load or submit.)
2. Click the AURA toolbar icon **on the tab you want to scan**. This opens the side panel and gives AURA
   access to that tab only, until it closes or moves to another site. Each tab needs its own click. There
   is no pairing step: the extension registers itself with the service on first use.
3. Open the **AI provider** panel, choose a provider and model, and paste your own API key. It is saved in
   this extension's storage and sent only to that provider. Or leave **Mock AI · Demo** selected, which
   makes no AI request at all.
4. Click **Scan current page**. Then select a finding to use **Highlight**, **Screenshot**, **Explain** or
   **Ask AURA**.

To run the whole thing on your own machine instead, start the server with `python -m aura.api` (it binds
127.0.0.1 and prints a token) and point the backend at `http://127.0.0.1:8765` in ⚙ Settings, pasting that
token. Nothing then leaves the machine except your browser's call to your AI provider.

After changing `aura/analyzers/js/dom_extraction.js` or `aura/vendor/axe.min.js`, run
`python -m aura.tools.sync_extension_assets`.

Extension end-to-end checks (the real, unmodified extension in Chromium, with real toolbar clicks):
`python tests/extension_e2e.py`, `python tests/extension_activation_e2e.py`,
`python tests/extension_highlight_e2e.py`, `python tests/extension_infinite_scroll_e2e.py`, and
`python tests/extension_browser_ai_e2e.py` — the last one drives a whole scan with the AI call made in the
browser, against a stand-in for the provider, so it costs no API credit.

Deploying it: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Submitting it to the Chrome Web Store:
[docs/STORE-LISTING.md](docs/STORE-LISTING.md).

---

## ⚡ V0.4 Core Capabilities & Benchmark Features

- **Consolidated 5 Test Lab Benchmark Suites (`test_lab/`)**:
  - `01_accessibility_suite`: missing alt text, accessible button names, low contrast, broken links, missing main landmark, missing form labels.
  - `02_ui_ux_suite`: broken visual hierarchy, confusing form structure, high cognitive density, weak CTA emphasis, inconsistent button styles, ambiguous error messages.
  - `03_navigation_interaction_suite`: broken navigation link, interaction/click failure, broken dropdown menu, dead button, misleading CTA, failed form submit.
  - `04_responsive_runtime_suite`: horizontal overflow, broken mobile layout, clipped text content, console error, uncaught runtime exception, network request failure.
  - `05_mixed_realistic_suite`: realistic SaaS dashboard integrating defects across all 5 categories.

- **Strict Ground Truth Isolation**:
  - Machine-readable `<script type="application/json" id="aura-ground-truth">` tags embedded inside benchmark pages.
  - Automatically stripped during DOM extraction so ground truth is **NEVER** exposed to AI prompts or verifier logic.
  - Evaluated **ONLY post-audit** by `EvaluationEngine` to calculate Precision, Recall, F1, True Positives, False Positives, and False Negatives.

- **Multi-Class Runtime Telemetry Classification (`aura/analyzers/runtime_analyzer.py`)**:
  - Categorizes console & network events into `APPLICATION`, `THIRD_PARTY`, `ENVIRONMENT`, and `BROWSER`.
  - Penalizes **only `APPLICATION` errors** in the Runtime score, avoiding false scoring penalties from third-party scripts or local environment noise.

- **Transparent Sub-Category Scoring (`aura/scoring/scorer.py`)**:
  - Itemized sub-scores across 6 dimensions: **UI (20%)**, **UX (20%)**, **Accessibility (20%)**, **Runtime (15%)**, **Responsiveness (15%)**, and **Interaction (10%)**.
  - Displays `"NOT EVALUATED"` or `"INSUFFICIENT EVIDENCE"` when evidence is absent, preventing default false 100/100 scores.

- **Streamlit V0.4 Unified Benchmark Dashboard (`app.py`)**:
  - One-click **🚀 Run Full Test Lab (All 5)** suite runner for batch execution.
  - Aggregate metrics display: Overall F1 Score, Precision, Recall, and per-category F1 breakdowns.
  - AI Coverage Warning alerts if candidate generator produces zero findings when defects exist.
  - Diagnostic expanders for False Negatives (Missed Defects) and False Positives (Rejected Predictions).
  - External Website Mode gracefully displays `Precision: N/A`, `Recall: N/A`, `F1: N/A`, `Ground Truth: Not Available`.

---

## 🛠️ Technology Stack

- **Frontend / Dashboard**: Streamlit
- **Backend / Core**: Python 3.12
- **Browser Automation**: Playwright (Chromium)
- **Accessibility Engine**: axe-core
- **AI Multimodal Providers**: Google Gemini (`gemini-2.0-flash`), OpenAI (`gpt-4o`), Anthropic (`claude-3.5-sonnet`), and offline `MockAIProvider`
- **Data Models**: Pydantic v2
- **Testing & Benchmark**: pytest, `scratch/run_benchmark.py`

---

## 💻 Installation & Setup

1. **Navigate to workspace**:
   ```bash
   cd c:\Users\somanathan\Desktop\Final_year
   ```

2. **Activate Virtual Environment**:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

3. **Install Dependencies & Playwright Browsers**:
   ```bash
   python -m pip install -r requirements.txt
   python -m playwright install
   ```

4. **Environment Variables**:
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Configure `AI_PROVIDER=gemini`, `openai`, `anthropic`, or `mock`. If no key is set, AURA seamlessly uses `MockAIProvider` or prompts for a session API key in the Streamlit sidebar.

---

## 🚀 Running AURA & Test Lab

### 1. Launch Streamlit Dashboard
```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

### 2. Run Local Test Lab Analysis
1. Select **🧪 LOCAL TEST LAB** mode in sidebar.
2. Click **🚀 Start Local Test Lab Server** (launches `http://127.0.0.1:8999`).
3. Pick a benchmark suite (e.g. `01_accessibility_suite` or `05_mixed_realistic_suite`).
4. Click **🚀 Run AURA Audit** or **🚀 Run Full Test Lab (All 5)**.
5. View verified findings, classified runtime telemetry, itemized scoring, and Ground Truth Evaluation Scorecard!

---

## 🧪 Running Automated Tests & Benchmarks

Run the complete test suite:
```bash
pytest tests/
```

Run the full 5-suite benchmark evaluation script:
```bash
python scratch/run_benchmark.py
```

---

## 📁 Project Structure

```text
aura/
├── agents/                     # V0.4 Agentic Subagents
│   ├── orchestrator.py         # Central AURAOrchestrator & audit run logger
│   ├── browser_agent.py        # Playwright Chromium & interaction agent
│   ├── ux_ui_agent.py          # Multimodal AI candidate finding generator
│   ├── accessibility_agent.py  # axe-core WCAG compliance scanner
│   ├── runtime_agent.py        # Console & network telemetry classifier
│   └── verification_agent.py   # Independent evidence verification agent
│
├── analyzers/                  # Specialized analyzers
│   ├── dom_analyzer.py        # Layout geometry, overflow & DOM extraction
│   └── runtime_agent.py       # Multi-class runtime telemetry classifier
│
├── browser/
│   ├── browser_manager.py      # Playwright browser manager
│   ├── interaction_policy.py   # Level-B Safety Policy (Safe vs Blocked actions)
│   └── runtime_collector.py   # Console error and network telemetry collector
│
├── evaluation/
│   └── evaluator.py            # Ground truth Precision, Recall, F1 evaluation engine
│
├── evidence/
│   └── correlator.py           # Multi-source evidence bundling & deduplication
│
├── findings/
│   ├── models.py              # Unified AURAFinding, Source, Severity, Category, Status
│   └── aggregation.py         # FindingsAggregator single source of truth
│
├── verifier/
│   ├── verifier.py            # Independent evidence verification engine
│   ├── evidence.py            # Evidence matcher & selector parser
│   └── rules.py               # Verification confidence heuristics & rejection rules
│
├── scoring/
│   ├── scorer.py              # Transparent sub-category AURA Scorer (6 dimensions)
│   ├── accessibility_scorer.py# Impact-weighted accessibility scoring engine
│   └── runtime_scorer.py      # Application error runtime scoring engine
│
├── security/
│   └── credentials.py         # Session credentials manager & error sanitizer
│
├── config/
│   ├── models.py              # Provider model registry
│   └── settings.py            # Settings, paths, permitted local hosts
│
app.py                          # Streamlit V0.4 Unified Benchmark Dashboard
test_lab/                       # Local AURA Test Lab (5 consolidated suites + ground truth)
├── launcher.py                 # HTTP Server launcher (127.0.0.1:8999)
└── 01_accessibility_suite... 05_mixed_realistic_suite/
runs/                           # Local audit run persistence (runs/<audit_id>/audit.json)
tests/                          # Automated unit and acceptance test suite
```

---

## 🔒 Security Notice

AURA enforces Level-B Safety Policy (`aura/browser/interaction_policy.py`) to prevent destructive operations (purchases, password changes, deletions). Session API keys are kept strictly in memory (`st.session_state`) and never saved to disk.

