// AURA side panel controller.
// All text coming from pages or AI output is rendered with textContent (never innerHTML).
import { api, ApiError, getAiChoice, setAiChoice, getProviderKey, setProviderKey, getSettings } from "./api.js";
import { PROVIDERS, callsProviderInBrowser, checkProviderKey } from "./providers.js";
import { cropFinding, NoShot } from "./shot.js";
import { scanCurrentPage, getActiveTab, ensureAgent, ScanError } from "./scanner.js";
import { agentHighlight, agentClearHighlight, clearPageOverlays } from "./page_functions.js";

const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ panel <-> service worker port
// The port's only job: when this panel closes, the service worker removes AURA's page marks (highlight) from the tabs this panel drew on. Chrome terminates an idle MV3 service worker after ~30 s,
// which disconnects the port. A disconnected Port must never be used again ("Attempting to use a
// disconnected port object"), so the reference is dropped on disconnect and a new port is opened when needed.
const findingChatLogs = new Map(); // isolated chat history keyed by audit_id:finding_id
const touchedTabs = new Set(); // tabs that may currently show AURA marks
let port = null;

function connectPort() {
  const p = chrome.runtime.connect({ name: "aura-panel" });
  p.onDisconnect.addListener(() => {
    void chrome.runtime.lastError; // disconnect is expected (service worker stopped); nothing to report
    if (port === p) port = null;
    // Marks may still be on screen: reconnect right away so the restarted service worker can still clean
    // them up when the panel closes.
    if (touchedTabs.size) ensurePort();
  });
  port = p;
  for (const tabId of touchedTabs) p.postMessage({ type: "touched-tab", tabId }); // re-announce after reconnect
}

function ensurePort() {
  if (!port) connectPort();
  return port;
}

function markTouched(tabId) {
  const known = touchedTabs.has(tabId);
  touchedTabs.add(tabId);
  if (!port) { connectPort(); return; } // connectPort announces every touched tab
  if (known) return;
  try {
    port.postMessage({ type: "touched-tab", tabId });
  } catch (_) {
    port = null; // disconnected between the check and the call: never reuse it
    connectPort();
  }
}

function untouch(tabId) {
  touchedTabs.delete(tabId);
}

// Friendly message for failures to reach the page; technical details stay in the DevTools console.
function pageUnavailable(action, e) {
  console.warn(`AURA ${action} failed:`, e);
  const reason = e instanceof ScanError && e.code === "OTHER_TAB"
    ? "Switch back to the tab that was scanned, then try again."
    : e instanceof ScanError && e.code === "RESTRICTED_PAGE"
      ? "This browser does not allow extensions on this page."
      : "AURA can no longer reach this page. It may have reloaded, moved to another site or closed. Click the AURA icon on the page and scan again.";
  return reason;
}

connectPort();

const state = { view: null, tabId: null, filter: null, selected: null, stale: false, health: null, scanning: false,
                access: { tabId: null, state: "PENDING" },
                // The scan's capture, held in memory for this panel only: it is never uploaded and never
                // written anywhere. Closing the panel or scanning again replaces it.
                capture: null,
                // Which AI provider and model this browser will call, and whether a key is saved for it.
                ai: { provider: "mock", model: "", hasKey: false } };

// ------------------------------------------------------------------ audit ownership (tab + document)
// An audit belongs to the tab it was scanned in AND to the document that tab showed. Chrome gives every
// loaded document a unique documentId: a reload or a navigation creates a new one, a switch between tabs
// does not. Before results are shown, the tab's current document is compared with the audited one, so the
// panel never shows one tab's results for another tab, and never keeps a stale "another tab" message.
// Only references are stored (audit id, document id, page origin+path), in chrome.storage.session: they
// survive panel close/reopen and service-worker restarts, and are cleared when the extension reloads.
// The findings themselves are re-fetched from the AURA service.
const AUDITS_KEY = "aura.panelAudits";
const audits = new Map(); // tabId -> { auditId, documentId, pageKey, view }

async function saveAuditRef(tabId, rec) {
  const data = (await chrome.storage.session.get(AUDITS_KEY))[AUDITS_KEY] || {};
  if (rec) data[tabId] = { auditId: rec.auditId, documentId: rec.documentId, pageKey: rec.pageKey };
  else delete data[tabId];
  await chrome.storage.session.set({ [AUDITS_KEY]: data });
}

async function restoreAuditRefs() {
  try {
    const data = (await chrome.storage.session.get(AUDITS_KEY))[AUDITS_KEY] || {};
    for (const [tabId, ref] of Object.entries(data)) {
      if (!audits.has(Number(tabId))) audits.set(Number(tabId), { ...ref, view: null });
    }
  } catch (_) { /* no stored audits */ }
}

function forgetAudit(tabId) {
  audits.delete(tabId);
  saveAuditRef(tabId, null).catch(() => {});
}

// The document a tab currently shows: Chrome's documentId plus origin+path (no query or fragment).
async function pageIdentity(tabId) {
  try {
    const [res] = await chrome.scripting.executeScript({ target: { tabId, frameIds: [0] }, func: () => location.origin + location.pathname });
    return res && res.documentId ? { documentId: res.documentId, pageKey: res.result } : null;
  } catch (_) {
    return null; // not reachable (access ended, tab closed, browser page)
  }
}

const SEVERITIES = ["critical", "high", "medium", "low"];
const SCORE_KEYS = [["aura", "AURA"], ["ui", "UI"], ["ux", "UX"], ["accessibility", "Accessibility"], ["runtime", "Runtime"]];
const CATEGORY_LABEL = { UI: "UI", UX: "UX", ACCESSIBILITY: "Accessibility", RESPONSIVENESS: "Responsive", NAVIGATION: "Navigation",
  FORM: "Form", CONTENT: "Content", RUNTIME: "Runtime", INTERACTION: "Interaction" };
const CONTRIBUTION_LABEL = { NOVEL_AI_INSIGHT: "Novel AI insight", COMPLEMENTARY_INTERPRETATION: "Complementary interpretation",
  DETERMINISTIC_DUPLICATE: "Deterministic duplicate" };

// ------------------------------------------------------------------ DOM helper
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const show = (id, on = true) => $(id).classList.toggle("hidden", !on);

// ------------------------------------------------------------------ server / page status
// Which AI this browser will use for the next scan. The choice and the key live in this extension; the
// AURA service is never told either, so this is read from storage and not from the server.
async function refreshAiChoice() {
  const choice = await getAiChoice();
  const inBrowser = callsProviderInBrowser(choice.provider);
  state.ai = {
    provider: choice.provider,
    model: choice.model,
    label: inBrowser ? PROVIDERS[choice.provider].label : "Mock AI · Demo",
    isMock: !inBrowser,
    hasKey: inBrowser ? !!(await getProviderKey(choice.provider)) : true,
  };
  return state.ai;
}

async function refreshHealth() {
  const pill = $("conn");
  const ai = await refreshAiChoice();
  const { backendUrl } = await getSettings();
  const local = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\])/i.test(backendUrl);
  try {
    const hl = await api.health();
    state.health = hl;
    if (!hl.paired) {
      pill.className = "pill pill-warn"; pill.textContent = "Not paired";
      pill.title = local ? "Open Settings and paste the pairing token printed by the AURA server."
                         : "AURA could not register this install. Try again in a moment.";
    } else if (!ai.hasKey) {
      pill.className = "pill pill-warn";
      pill.textContent = `${ai.label} · no key`;
      pill.title = `Add your ${ai.label} API key in the AI provider panel. It stays in this browser and is `
        + "sent only to that provider.";
    } else {
      pill.className = "pill pill-ok"; pill.textContent = `Connected · ${ai.label}`;
      pill.title = ai.isMock
        ? "Mock AI is built in: scripted findings for demos and tests, not real model analysis."
        : `Each AI scan makes one request to ${ai.label}${ai.model ? " / " + ai.model : ""}, from this `
          + "browser, with your key.";
    }
    $("ai-provider").textContent = ai.isMock ? ai.label : `${ai.label}${ai.model ? " · " + ai.model : ""}`;
    $("ai-provider").title = ai.hasKey ? "" : "No API key saved for this provider.";
    $("privacy").textContent = privacyLine(ai, backendUrl, local);
    $("ask-cost").textContent = ai.isMock ? "needs a real AI provider" : "1 AI request per question";
  } catch (e) {
    state.health = null;
    // A hosted service that has gone to sleep is not a service that is down, and saying so would be
    // both wrong and alarming. It wakes on the first request; the scan after this one will work.
    const waking = !local && e.code === "TIMEOUT";
    pill.className = waking ? "pill pill-warn" : "pill pill-err";
    pill.textContent = waking ? "Service waking…" : (local ? "Server offline" : "AURA service unreachable");
    pill.title = e.message;
    $("ai-provider").textContent = ai.isMock ? ai.label : `${ai.label}${ai.model ? " · " + ai.model : ""}`;
    $("privacy").textContent = privacyLine(ai, backendUrl, local);
  }
}

// Exactly where each piece of a scan goes. Said plainly, because a person deserves to know before they
// press Scan, and because every word of it has to stay true.
function privacyLine(ai, backendUrl, local) {
  const server = local ? `the AURA server on this machine (${backendUrl})` : `the AURA service (${backendUrl})`;
  const where = `This page's structure, its accessibility results, its errors, its address and its title go to ${server}, which checks every claim against them. `
    + "Screenshots stay in this browser.";
  if (ai.isMock) {
    return `${where} Mock AI is built in and makes no AI request at all.`;
  }
  return `${where} With AI on, your browser sends the evidence summary and one screenshot straight to `
    + `${ai.label} using your own API key. AURA never receives that key.`;
}

// ------------------------------------------------------------------ tab access (activeTab lifecycle)
// The background service worker owns activation: the user clicks the AURA toolbar icon on a tab, which
// grants activeTab for it. The panel always resolves the CURRENT active tab (never a remembered id) and
// asks the background whether that tab is activated and still accessible.
const ACCESS_UI = {
  PENDING: ["access-pending", "Checking access to this tab…"],
  ACTIVATED: ["access-ok", "AURA can scan this tab. Access lasts until the tab closes or moves to another site."],
  NOT_ACTIVATED: ["access-needed", "Click the AURA icon in your browser's toolbar while this tab is open to let AURA read this page. AURA has no access to any page until you do."],
  ACCESS_LOST: ["access-needed", "Access to this tab ended (it moved to another site). Click the AURA icon in the toolbar again to re-activate it."],
  RESTRICTED: ["access-blocked", "This browser does not allow extensions on this page (browser pages, the extension store, other extensions)."],
  NO_TAB: ["access-blocked", "No active tab in this window."],
};

let accessSeq = 0;

async function refreshTabState() {
  const seq = ++accessSeq; // ignore answers that arrive after a newer check started (tab switched meanwhile)
  let tab = null;
  try { tab = await getActiveTab(); } catch (_) { /* no tab */ }
  let result = { state: "NO_TAB" };
  if (tab) {
    try {
      result = await chrome.runtime.sendMessage({ type: "GET_TAB_STATE", tabId: tab.id }) || { state: "NOT_ACTIVATED" };
    } catch (_) {
      result = { state: "NOT_ACTIVATED" };
    }
  }
  if (seq !== accessSeq) return;
  state.access = { tabId: tab ? tab.id : null, state: result.state };

  let host = "Current tab";
  if (tab && tab.url) { try { const u = new URL(tab.url); host = u.host || u.protocol; } catch (_) { /* ignore */ } }
  else if (result.origin) { try { host = new URL(result.origin).host; } catch (_) { /* ignore */ } }
  $("page-host").textContent = host;

  const [cls, text] = ACCESS_UI[result.state] || ACCESS_UI.NOT_ACTIVATED;
  const el = $("access");
  el.className = `access ${cls}`;
  el.textContent = text;
  $("scan").disabled = state.scanning || result.state !== "ACTIVATED";
  $("scan").title = result.state === "ACTIVATED" ? "" : "Activate this tab first: click the AURA toolbar icon.";

  if (!state.scanning) await syncAuditForTab(tab, result.state, seq);
}

// Shows the audit that belongs to the current tab's current document, or explains why there is none.
async function syncAuditForTab(tab, accessState, seq) {
  const rec = tab ? audits.get(tab.id) : null;
  if (!rec) {
    const others = [...audits.keys()].filter((id) => !tab || id !== tab.id);
    showNoAudit(others.length
      ? "This tab hasn't been scanned. Your other results belong to another tab: switch back to it, or scan this tab."
      : accessState === "ACTIVATED"
        ? "No results for this page yet. Run a scan to check it."
        : "No results for this page yet.");
    return;
  }

  let check = "valid";
  if (accessState === "ACCESS_LOST") {
    check = "navigated";
  } else if (accessState === "ACTIVATED") {
    const now = await pageIdentity(tab.id);
    if (!now) check = "unverified";
    else if (now.pageKey !== rec.pageKey) check = "navigated";
    else if (now.documentId !== rec.documentId) check = "reloaded";
  } else {
    check = "unverified";
  }
  if (seq !== accessSeq) return; // a newer tab state is being resolved

  if (check === "navigated") {
    forgetAudit(tab.id);
    if (state.tabId === tab.id) state.stale = "navigated";
    showNoAudit("This tab moved to another page after it was scanned, so those findings no longer apply. Scan this page to get new results.", true);
    return;
  }

  if (!rec.view) {
    try {
      rec.view = await api.getAudit(rec.auditId);
    } catch (_) {
      if (seq !== accessSeq) return;
      showNoAudit("The results for this tab could not be loaded from the AURA server. Scan this page again.", true);
      return;
    }
    if (seq !== accessSeq) return;
  }

  const stale = check === "reloaded"
    ? "This page was reloaded after the scan. Findings may no longer match what is on screen: scan again to refresh them."
    : check === "unverified"
      ? "AURA could not confirm that this page is unchanged since the scan: scan again if it changed."
      : null;
  showAudit(tab.id, rec, stale);
}

function showNoAudit(message, warn = false) {
  show("results", false);
  show("detail", false);
  const box = $("no-audit");
  box.classList.toggle("warn", !!warn);
  $("no-audit-msg").textContent = message || "";
  show("no-audit", !!message);
}

async function showAudit(tabId, rec, staleMessage) {
  show("no-audit", false);
  if (state.tabId !== tabId || state.view !== rec.view) {
    // Another tab's audit was on screen: remove its page marks, then render this tab's audit
    if (state.tabId !== null && state.tabId !== tabId && touchedTabs.has(state.tabId)) {
      const prev = state.tabId;
      chrome.scripting.executeScript({ target: { tabId: prev }, func: clearPageOverlays }).catch(() => {});
      untouch(prev);
    }
    state.view = rec.view; state.tabId = tabId; state.filter = null; state.selected = null;
    state.stale = staleMessage;
    renderResults(rec.view);
    return;
  }
  state.stale = staleMessage;
  renderBanner(state.view);
  if (state.selected) { show("results", false); show("detail", true); } else { show("detail", false); show("results", true); }
}

chrome.tabs.onActivated.addListener(() => { refreshTabState(); });
chrome.windows.onFocusChanged.addListener(() => { refreshTabState(); });
chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (tabId === state.tabId && info.status === "loading" && state.view) {
    // Reload/navigation discards the page's DOM, and with it any highlight: drop its controls.
    // Whether the audit is still valid is decided by syncAuditForTab (document identity), not here.
    $("act-out").classList.add("hidden");
    untouch(tabId);
  }
  if (info.status === "complete" || info.status === "loading" || info.url) refreshTabState();
});
chrome.tabs.onRemoved.addListener((tabId) => {
  forgetAudit(tabId);
  untouch(tabId);
});
// The background announces activations made by a toolbar click (possibly while this panel is already open).
chrome.runtime.onMessage.addListener((msg, sender) => {
  if (sender.id !== chrome.runtime.id || !msg) return;
  if (msg.type === "TAB_ACTIVATED" || msg.type === "TAB_STATE_CHANGED") refreshTabState();
});

// ------------------------------------------------------------------ scanning
function renderStep(label, status, detail) {
  const list = $("steps");
  let li = Array.from(list.children).find((n) => n.dataset.label === label);
  if (!li) { li = h("li", { "data-label": label }); list.append(li); }
  li.className = status === "running" ? "running" : status;
  li.replaceChildren(h("span", {}, label), detail ? h("span", { class: "detail" }, detail) : "");
}

async function runScan() {
  if (state.scanning) return;
  state.scanning = true;
  $("scan").disabled = true;
  $("scan").textContent = "Scanning…";
  show("error", false); show("results", false); show("detail", false); show("progress", true);
  $("progress-title").textContent = "Scanning current page…";
  $("steps").replaceChildren();
  show("no-audit", false);
  try {
    const scanned = await getActiveTab().catch(() => null);
    const identity = scanned ? await pageIdentity(scanned.id) : null;
    const { view, tabId, capture } = await scanCurrentPage({
      useAI: $("opt-ai").checked,
      interactions: $("opt-interact").checked,
      onStep: renderStep,
    });
    state.view = view; state.tabId = tabId; state.stale = false; state.filter = null; state.selected = null;
    state.capture = capture || null;   // kept in memory only, for the per-finding screenshots
    if (identity && scanned.id === tabId) {
      const rec = { auditId: view.audit_id, documentId: identity.documentId, pageKey: identity.pageKey, view };
      audits.set(tabId, rec);
      saveAuditRef(tabId, rec).catch(() => {});
    }
    show("progress", false);
    renderResults(view);
  } catch (e) {
    show("progress", false);
    const title = e instanceof ScanError && ["NO_ACCESS", "RESTRICTED_PAGE"].includes(e.code) ? "Cannot scan this page"
      : e instanceof ApiError && e.code === "UNAUTHORIZED" ? "Not paired with the AURA server"
      : e instanceof ApiError && ["UNREACHABLE", "TIMEOUT"].includes(e.code) ? "AURA server unavailable"
      : "Scan failed";
    $("error-title").textContent = title;
    $("error-msg").textContent = e.message + (e.detail && typeof e.detail === "string" ? ` (${e.detail})` : "");
    show("error", true);
  } finally {
    state.scanning = false;
    $("scan").textContent = "Scan current page";
    refreshHealth();
    refreshTabState(); // re-enables Scan only if the current tab is (still) activated
  }
}

// ------------------------------------------------------------------ results
const RESULT_STATE = {
  COMPLETE: ["ok", "Scan complete"],
  DETERMINISTIC_ONLY: ["warn", "Deterministic-only result"],
  PARTIAL: ["warn", "Partial result"],
};

const SCORE_HELP = [
  ["AURA score", "A combined quality score based on verified usability, accessibility, and visual issues identified on this page."],
  ["UI", "Evaluates visual clarity, button prominence, layout hierarchy, and spacing."],
  ["UX", "Evaluates navigation clarity, action labels, forms, and interactive feedback."],
  ["Accessibility", "Your accessibility score is based on accessibility issues AURA detected and verified on this page."],
  ["Runtime", "Evaluates smooth page operation without unhandled script crashes or network failures."],
];

function renderBanner(view) {
  const [cls, title] = RESULT_STATE[view.result_state] || ["warn", view.result_state];
  const b = $("state-banner");
  b.className = `banner ${cls}`;
  let host = view.page_url;
  try { const u = new URL(view.page_url); host = u.host + u.pathname; } catch (_) { /* keep */ }
  const lines = [h("strong", {}, `${title} · ${view.findings.length} finding${view.findings.length === 1 ? "" : "s"}`),
                 h("p", {}, host)];
  if (view.ai.state !== "AI_OK") {
    lines.push(h("p", {}, view.ai.message));
    // "AI analysis unavailable" on its own leaves the person with nowhere to go. The provider said why
    // it refused - a rejected key, a page too large for its limit - and that is the actionable part.
    if (view.ai.reason) lines.push(h("p", { class: "fine" }, view.ai.reason));
  }
  if (typeof state.stale === "string" && state.stale !== "navigated") lines.push(h("p", { class: "stale" }, state.stale));
  b.replaceChildren(...lines);
}

function scoreClass(v) { return typeof v !== "number" ? "na" : v >= 90 ? "good" : v >= 70 ? "mid" : "bad"; }

function renderScores(view) {
  const aura = view.scores.aura;
  const main = $("score-aura");
  main.className = `score-value ${scoreClass(aura)}`;
  main.textContent = typeof aura === "number" ? aura : "N/A";
  $("scores").replaceChildren(...SCORE_KEYS.filter(([k]) => k !== "aura").map(([k, label]) => {
    const v = view.scores[k];
    const na = typeof v !== "number";
    return h("div", { class: "srow" }, h("span", { class: "k" }, label),
      h("span", { class: `v ${scoreClass(v)}`, title: na ? "Not evaluated in this scan" : "" }, na ? "Not evaluated" : v));
  }));
  $("score-note").textContent = view.scores.basis ? `Scored on: ${view.scores.basis}.` : "";
  $("score-help").replaceChildren(...SCORE_HELP.flatMap(([k, text]) => [h("h4", {}, k), h("p", {}, text)]));
}

function renderResults(view) {
  renderBanner(view);
  renderScores(view);

  const counts = view.severity_counts || {};
  const total = view.findings.length;
  $("sev-row").replaceChildren(
    h("button", { class: "sev", "aria-pressed": state.filter ? "false" : "true",
                  onclick: () => { state.filter = null; renderResults(view); } },
      h("span", { class: "n" }, total), "All"),
    ...SEVERITIES.map((sev) => {
      const n = counts[sev] || 0;
      return h("button", { class: `sev ${sev}${n ? "" : " zero"}`, "aria-pressed": state.filter === sev ? "true" : "false",
                           onclick: () => { state.filter = state.filter === sev ? null : sev; renderResults(view); } },
        h("span", { class: "n" }, n), sev[0].toUpperCase() + sev.slice(1));
    }));

  const list = view.findings.filter((f) => !state.filter || f.severity === state.filter);
  $("list-filter").textContent = state.filter ? `${state.filter} only` : "";
  $("findings").replaceChildren(...(list.length ? list.map(findingRow) : [h("li", { class: "empty" },
    total ? "No findings with this severity." :
    view.ai.state === "AI_OK" ? "Nothing to report: the evidence collected shows no problems on this page." :
    "No problems found in the deterministic checks. AI analysis did not run, so UI and UX were not reviewed.")]));

  $("rejected-count").textContent = `(${view.rejected_ai_candidates.length})`;
  $("rejected").replaceChildren(...(view.rejected_ai_candidates.length ? view.rejected_ai_candidates.map((r) =>
    h("li", {}, h("b", {}, r.title), h("br"), r.reason || "Contradicted by browser evidence.")) :
    [h("li", {}, "None.")]));

  const cov = view.evidence_coverage || {};
  $("coverage-pct").textContent = cov.percentage !== undefined ? `(${cov.percentage}%)` : "";
  $("coverage").replaceChildren(
    ...Object.entries(cov.checklist || {}).map(([k, v]) => h("li", { class: v ? "yes" : "no" }, k)),
    ...((cov.notes || []).map((n) => h("li", { class: "note" }, n))));

  const ac = view.ai_candidates;
  $("scan-meta").replaceChildren(
    h("li", {}, `Audit ${view.audit_id} · ${view.timestamp} · ${view.duration_seconds}s`),
    h("li", {}, `Viewport ${view.viewport.width}×${view.viewport.height}`),
    h("li", {}, `AI: ${view.ai.label || view.ai.provider || "—"}${view.ai.model && !view.ai.is_mock ? " · " + view.ai.model : ""} · ${view.ai.provider_status || view.ai.state}`),
    view.ai.state === "AI_OK"
      ? h("li", {}, `AI suggestions: ${ac.proposed} proposed · ${ac.verified_confirmed} confirmed · ${ac.verified_likely} likely · ${ac.uncertain} uncertain · ${ac.rejected} rejected · ${ac.suppressed_as_deterministic_duplicates} duplicates of deterministic findings`)
      : h("li", {}, `AI suggestions: Unavailable (${view.ai.message || "AI analysis unavailable"})`),
    (view.technical_only_findings || []).length
      ? h("li", {}, `${view.technical_only_findings.length} finding(s) kept as technical records only: AURA could not describe them specifically enough to show as findings.`)
      : null,
    ...view.steps.map((s) => h("li", {}, `${s.title}${s.detail ? " — " + s.detail : ""}`)),
  );
  show("detail", false);
  show("results", true);
}

// One line under the headline: human-friendly verification status and confidence.
function statusLine(f) {
  const h = f.human || {};
  const status = h.status_label || f.status_label || f.status || f.verification_status;
  const conf = (h.confidence_label || f.confidence_label) ? ` · ${h.confidence_label || f.confidence_label} confidence` : "";
  return `${status}${conf}`;
}

function findingRow(f) {
  const human = f.human || {};
  const plain = f.plain || {};
  const title = human.title || f.title || plain.headline;
  const summary = human.summary || f.summary || f.description || plain.headline || f.title;
  const why = human.why_it_matters || f.why_it_matters || plain.why;
  const whereDesc = human.location || f.location_description || (f.target && f.target.description) || "Page element";
  return h("li", {}, h("button", { class: `finding ${f.severity}`, "data-rule": f.rule || "", "data-id": f.id,
                                   onclick: () => openDetail(f) },
    h("div", { class: "sev-line" },
      f.severity.toUpperCase(), " · ",
      CATEGORY_LABEL[f.category] || f.category,
      f.affected_count > 1 ? h("span", { class: "badge-count" }, ` (${f.affected_count} elements)`) : null),
    h("div", { class: "headline" }, title),
    h("div", { class: "summary-line" }, summary),
    h("div", { class: "status" }, statusLine(f),
      h("span", { class: "where" }, ` · Where: ${whereDesc}`)),
    why ? h("div", { class: "why" }, `Why it matters: ${why}`) : null,
    h("span", { class: "more-link" }, "View details →")));
}

// ------------------------------------------------------------------ finding detail
function openDetail(f) {
  if (state.selected && state.selected.id !== f.id) clearPageMarks();
  state.selected = f;
  show("results", false);
  show("detail", true);
  $("act-out").classList.add("hidden");
  $("tech-details").open = false;
  const human = f.human || {};
  const technical = f.technical || f.technical_details || {};
  const status = human.status_label || f.status_label || f.status || f.verification_status;
  const confLabel = human.confidence_label || f.confidence_label;

  $("d-badges").replaceChildren(
    h("span", { class: `badge ${f.severity}` }, f.severity),
    h("span", { class: "badge" }, CATEGORY_LABEL[f.category] || f.category),
    h("span", { class: `badge v-${(f.verification_status || "").toLowerCase()}` }, status),
    confLabel ? h("span", { class: "badge badge-muted" }, `${confLabel} confidence`) : null
  );

  $("d-title").textContent = human.title || f.title || "";
  const statusMeaning = human.status_meaning || f.status_meaning || "";
  $("d-status").textContent = `${statusLine(f)}${statusMeaning ? " — " + statusMeaning : ""}`.trim();
  // The card states the problem in one short sentence. The full account is in Explain, and every
  // technical fact (location, detector, rule, verification) is in Technical details.
  $("d-desc").textContent = human.short_summary || f.short_summary || human.summary || f.summary
    || f.description || "";

  const loc = human.location || f.location_description || (f.target && f.target.description)
    || (f.target && f.target.label) || "One element on this page.";
  // Affected elements drawer (for grouped repetitive findings), now inside Technical details
  const affBox = $("d-affected-box");
  const affList = $("d-affected-list");
  const affToggle = $("d-affected-toggle");
  if (affBox && affList && affToggle) {
    if (f.affected_elements && f.affected_elements.length > 1) {
      affBox.classList.remove("hidden");
      affList.classList.add("hidden");
      affToggle.textContent = `View all ${f.affected_elements.length} affected elements ▼`;
      affList.replaceChildren(...f.affected_elements.map((item, idx) => {
        return h("li", { class: "affected-item" },
          h("span", { class: "aff-loc" }, `${idx + 1}. ${item.location || item.selector}`),
          h("button", {
            class: "link-btn small",
            onclick: () => doHighlight({ ...f, target: { ...(f.target || {}), kind: "element", highlightable: true,
                                                         selector: item.selector, selectors: [item.selector] } })
          }, "Highlight")
        );
      }));
      affToggle.onclick = () => {
        const isHidden = affList.classList.toggle("hidden");
        affToggle.textContent = isHidden
          ? `View all ${f.affected_elements.length} affected elements ▼`
          : `Hide affected elements ▲`;
      };
    } else {
      affBox.classList.add("hidden");
    }
  }

  // Evidence summary: "Why AURA reported this", now part of Technical details
  const evSum = human.why_aura_reported_this || f.why_aura_reported_this || {};
  const rep = f.reproduction || (evSum && evSum.reproduction) || {};
  const conc = f.conclusion || (evSum && evSum.conclusion) || {};

  const evBox = $("d-evidence-summary");
  if (evBox) {
    const obsEl = $("d-ev-observation");
    const repEl = $("d-ev-reproduction");
    const checkEl = $("d-ev-checklist");
    const concEl = $("d-ev-conclusion");

    if (obsEl) {
      obsEl.replaceChildren(
        h("div", { class: "ev-section" },
          h("strong", {}, "What AURA observed: "),
          evSum.observation || human.summary || f.summary || f.description || "Issue observed on page."
        )
      );
    }

    if (repEl) {
      const repState = rep.state || human.reproduction_state || "OBSERVED";
      const repAction = rep.action_attempted || rep.action || "Automated browser evaluation";
      const safety = rep.safety_boundary ? h("div", { class: "fine muted safety-note" }, `Safety note: ${rep.safety_boundary}`) : null;
      repEl.replaceChildren(
        h("div", { class: "ev-section" },
          h("strong", {}, "Reproduction / Verification: "),
          h("span", { class: `badge badge-rep badge-${repState.toLowerCase()}` }, repState),
          h("p", { class: "fine" }, repAction),
          safety
        )
      );
    }

    if (checkEl && Array.isArray(evSum.checklist)) {
      const activeItems = evSum.checklist.filter((item) => item && item.present);
      if (activeItems.length > 0) {
        checkEl.replaceChildren(
          h("div", { class: "ev-section" },
            h("strong", {}, "Evidence evaluated:"),
            h("ul", { class: "coverage-list" },
              ...activeItems.map((item) => h("li", { class: "yes" }, item.name))
            )
          )
        );
      } else {
        checkEl.replaceChildren();
      }
    }

    if (concEl) {
      const strength = conc.strength || human.status_label || f.status_label || "Confirmed problem";
      const fact = conc.known_fact || human.known_fact;
      const inference = conc.inferred_judgement; // null when it would repeat "Why it matters"
      concEl.replaceChildren(
        h("div", { class: "ev-section" },
          h("strong", {}, "Conclusion: "),
          h("span", { class: "badge" }, strength),
          fact ? h("p", { class: "fine" }, h("span", { class: "muted" }, "Known fact: "), fact) : null,
          inference ? h("p", { class: "fine" }, h("span", { class: "muted" }, "Inferred impact: "), inference) : null
        )
      );
    }
  }

  // Technical details: EVERYTHING technical is preserved here
  const tech = f.technical || f.technical_details || {};
  const facts = [];
  const add = (k, ...v) => facts.push(h("dt", {}, k), h("dd", {}, ...v));
  // Where the problem is, and how it was found: both are engineering facts, so both live here.
  add("Location", loc + (f.affected_count > 1 ? ` (${f.affected_count} elements in total)` : ""));
  add("Detector", tech.detector || f.detector || (f.origin === "DETERMINISTIC" ? `${f.source} (deterministic)` : "AI candidate, independently verified"));
  add("How it was detected", (f.reproduction && f.reproduction.action_attempted) || "Inspected during the scan.");
  add("Rule ID", h("code", {}, tech.rule_id || f.rule || "—"));
  if (tech.raw_rule_id && tech.raw_rule_id !== (tech.rule_id || f.rule)) {
    add("Raw Rule ID", h("code", {}, tech.raw_rule_id));
  }
  if (tech.normalized_rule && tech.normalized_rule !== (tech.rule_id || f.rule)) {
    add("Normalized Rule", h("code", {}, tech.normalized_rule));
  }
  if (f.target && f.target.kind === "element") {
    add("Selector", h("code", {}, tech.selector || (f.target && f.target.selector) || "—"), f.affected_count > 1 ? ` (+${f.affected_count - 1} more)` : "");
  } else {
    add("Selector", `Page-level (${(f.target && f.target.label) || "page"})`);
  }
  if (tech.wcag_criteria && tech.wcag_criteria.length) {
    add("WCAG Reference", tech.wcag_criteria.join(", "));
  }
  add("Verification", `${tech.verification_status || f.verification_status}${typeof (tech.verification_score ?? f.verification_score) === "number" ? ` · score ${(tech.verification_score ?? f.verification_score).toFixed(2)}` : ""}`,
    f.verification_note ? h("div", { class: "muted" }, f.verification_note) : "");
  if (rep.state) {
    add("Reproduction State", `${rep.state}${rep.action_attempted ? ` — ${rep.action_attempted}` : ""}`);
  }
  if (conc.strength) {
    add("Conclusion Strength", conc.strength);
  }
  add("Confidence", typeof (tech.confidence ?? f.confidence) === "number" ? `${(tech.confidence ?? f.confidence).toFixed(2)} (${human.confidence_label || f.confidence_label || "Score"})` : "—",
    h("span", { class: "muted" }, f.origin === "DETERMINISTIC" ? " (deterministic detector)" : " (AI-reported, before verification)"));
  if (typeof (tech.materiality_score ?? f.materiality_score) === "number") {
    add("Materiality Score", `${(tech.materiality_score ?? f.materiality_score).toFixed(2)}`);
  }
 const prov =
  tech.evidence_provenance ||
  (f.evidence && f.evidence.types) ||
  [];
  if (prov.length) {
    add("Evidence Provenance", h("div", {}, prov.map((p) => h("span", { class: "badge badge-muted", style: "margin-right:4px;" }, p))));
  }
  const ev = (tech.evidence_sources && tech.evidence_sources.length ? tech.evidence_sources : (f.evidence && f.evidence.sources)) || [];
  add("Evidence Sources", ev.length ? h("ul", {}, ...ev.map((x) => h("li", {}, x))) : "No evidence detail recorded.");
  if (f.origin !== "DETERMINISTIC") {
    add("AI contribution", `${CONTRIBUTION_LABEL[tech.ai_contribution_type || f.ai_contribution_type] || tech.ai_contribution_type || f.ai_contribution_type || "—"}` +
      (typeof (tech.ai_contribution_score ?? f.ai_contribution_score) === "number" ? ` · ${(tech.ai_contribution_score ?? f.ai_contribution_score).toFixed(2)}` : ""),
      f.why_ai_needed ? h("div", { class: "muted" }, f.why_ai_needed) : "");
  } else {
    add("AI contribution", "None — detected deterministically.");
  }
  add("Audit ID", state.view ? state.view.audit_id : "—");
  if (tech.raw_title && tech.raw_title !== (human.title || f.title)) {
    add("Raw Detector Title", tech.raw_title);
  }
  $("d-facts").replaceChildren(...facts);

  // Highlight is offered only when one real element stands behind the finding. An area finding says so
  // in words rather than lighting up the container the claim happened to land on.
  const target = f.target || {};
  const canHighlight = target.highlightable === undefined
    ? target.kind === "element" && Boolean(target.selector || (target.selectors || []).length)
    : Boolean(target.highlightable);
  $("act-highlight").classList.toggle("hidden", !canHighlight);
  $("act-highlight").disabled = !canHighlight;
  $("act-highlight").title = canHighlight ? "" : "This finding covers an area of the page, not one element.";

  // Screenshot is offered only when AURA recorded where this finding sits in the capture.
  const canShoot = Boolean(target.has_shot_region);
  $("act-shot").classList.toggle("hidden", !canShoot);
  $("act-shot").title = canShoot ? "Show this part of the page as it looked during the scan" : "";
  revokeShot();
  // Whenever Highlight is absent, the panel says why. A missing button with no explanation is the kind of
  // silent dead end this rectification set out to remove.
  const areaNote = $("d-area-note");
  if (areaNote) {
    const reason = canHighlight ? ""
      : target.kind === "unresolved"
        ? "AURA could not match this suggestion to one element on the scanned page, so there is nothing to highlight."
      : target.kind === "network"
        ? "This finding is about a request the page made, not about something on screen, so there is nothing to highlight."
      : target.kind === "page"
        ? "This finding applies to the page as a whole, so there is no single element to highlight."
      : target.kind === "group"
        ? "This finding covers several elements and AURA could not place any of them on the page as it is now."
        : "This finding applies to an area of the page rather than one specific element, so AURA does not highlight it.";
    areaNote.classList.toggle("hidden", !reason);
    areaNote.textContent = reason;
  }

  // Context-isolated Ask AURA conversation log per finding. Opening a different finding swaps the whole
  // conversation and the half-typed question, so nothing from the previous finding carries over.
  const chatKey = `${state.view ? state.view.audit_id : "audit"}:${f.id}`;
  const existingLog = findingChatLogs.get(chatKey) || [];
  $("ask-log").replaceChildren(...existingLog.map((node) => node.cloneNode(true)));
  $("ask-input").value = "";
  $("ask-scope").textContent = `Answers are about this finding only: ${human.title || f.title || f.id}`;
  window.scrollTo({ top: 0 });
}

// Whatever an action produces appears here, with a Close control: a panel that cannot be dismissed ends
// up covering the finding it belongs to.
function actOut(children, warn = false) {
  const out = $("act-out");
  out.className = `act-out${warn ? " warn" : ""}`;
  out.replaceChildren(
    h("button", { class: "act-close", title: "Close", "aria-label": "Close", onclick: closeActOut }, "✕"),
    ...children);
}

function closeActOut() {
  revokeShot();
  const out = $("act-out");
  out.replaceChildren();
  out.classList.add("hidden");
}

async function inScannedTab() {
  const tab = await getActiveTab();
  if (tab.id !== state.tabId) throw new ScanError("Switch to the tab that was scanned first.", "OTHER_TAB");
  await ensureAgent(state.tabId);
  markTouched(state.tabId);
  return state.tabId;
}

async function execAgent(func, args) {
  const tabId = await inScannedTab();
  const [res] = await chrome.scripting.executeScript({ target: { tabId, frameIds: [0] }, func, args });
  return res && res.result;
}

// Why a highlight could not be drawn. Each cause gets its own sentence: a page that changed since the
// scan is a different problem from an element that disappeared, and from a target that matches several
// elements. There is no catch-all "not in content" message any more.
const HIGHLIGHT_FAILURE_TITLE = {
  page_changed: "This page is not the one that was scanned",
  stale_document: "This page has changed since the scan",
  element_gone: "That element is no longer on the page",
  ambiguous: "Several elements match this finding",
  invalid_selector: "AURA cannot look up that target on this page",
};

async function doHighlight(f = state.selected) {
  const target = f.target || {};

  // An area finding has no single element behind it. Saying so is more honest than highlighting the
  // container the claim happened to land on.
  if (target.kind && target.kind !== "element" && !(target.selectors || []).length) {
    actOut([h("h3", {}, "No single element to highlight"),
      h("p", {}, "This finding applies to an area of the page rather than one specific element.")], true);
    return;
  }

  // The finding belongs to the document that was scanned. If this tab now shows a different document
  // (a reload or a navigation), say that instead of blaming the element.
  const rec = audits.get(state.tabId);
  if (rec) {
    const now = await pageIdentity(state.tabId);
    if (now && now.pageKey !== rec.pageKey) {
      actOut([h("h3", {}, HIGHLIGHT_FAILURE_TITLE.page_changed),
        h("p", {}, "Scan this page again before highlighting this finding.")], true);
      return;
    }
    if (now && now.documentId !== rec.documentId) {
      actOut([h("h3", {}, HIGHLIGHT_FAILURE_TITLE.stale_document),
        h("p", {}, "This finding belongs to an earlier version of this page. Scan again to highlight it.")], true);
      return;
    }
  }

  try {
    const r = await execAgent(agentHighlight, [{
      selectors: target.selectors || [],
      label: `${f.id} · ${f.severity}`,
      expectedText: target.text || null,
      accessibleName: target.accessible_name || null,
      role: target.role || null,
      tag: target.tag || null,
      auditUrl: state.view.page_url,
    }]);
    if (r.status === "highlighted" || r.status === "partial") {
      const warn = r.status === "partial" || r.text_mismatch || (r.strategy && r.strategy !== "EXACT_SELECTOR");
      actOut([
        h("p", {}, r.status === "partial" ? r.message : "Element highlighted on the page."),
        r.status !== "partial" && r.message ? h("p", { class: "muted" }, r.message) : "",
        h("div", { class: "row" }, h("button", { class: "btn", onclick: clearHighlight }, "Clear highlight")),
      ], warn);
    } else {
      actOut([h("h3", {}, HIGHLIGHT_FAILURE_TITLE[r.status] || "Not highlighted"), h("p", {}, r.message)], true);
    }
  } catch (e) {
    actOut([h("h3", {}, "Highlight isn't available on this page right now."), h("p", {}, pageUnavailable("highlight", e))], true);
  }
}

// Switching findings removes the previous finding's highlight so the page never shows a mark
// that belongs to a different finding.
async function clearPageMarks() {
  try {
    await execAgent(agentClearHighlight, []);
    untouch(state.tabId); // nothing of AURA's is left on the page
  } catch (_) { /* tab gone or unreachable: nothing to clean */ }
}

async function clearHighlight() {
  try { await execAgent(agentClearHighlight, []); } catch (_) { /* tab gone */ }
  $("act-out").classList.add("hidden");
}

// Shows the part of the scan's capture this finding is about, with the element boxed. The capture never
// left this browser: the crop is made here, from the image the scan is still holding in memory.
let shotUrl = null;

function revokeShot() {
  if (shotUrl) { URL.revokeObjectURL(shotUrl); shotUrl = null; }
}

async function doScreenshot() {
  const f = state.selected;
  actOut([h("p", { class: "muted" }, "Preparing the screenshot…")]);
  revokeShot();
  try {
    shotUrl = await cropFinding(state.capture, f, (state.view.viewport || {}).width);
    const frame = h("div", { class: "shot-frame" });
    const img = h("img", { class: "shot", src: shotUrl,
      alt: "The part of the page this finding is about, with the problem outlined.",
      title: "Click to zoom" });
    // Click to zoom: the crop is shown fit-to-width, and zooming shows it at full size inside a
    // scrollable frame so small text in the screenshot can still be read.
    img.addEventListener("click", () => {
      const zoomed = img.classList.toggle("zoomed");
      frame.classList.toggle("zoomed", zoomed);
      img.title = zoomed ? "Click to fit" : "Click to zoom";
      hint.textContent = zoomed ? "Zoomed in — click the image to fit it again. Drag to look around."
                                : "From the screenshot taken during the scan. The marked box is the problem. Click to zoom.";
    });
    const hint = h("p", { class: "fine muted" },
      "From the screenshot taken during the scan. The marked box is the problem. Click to zoom.");
    frame.append(img);
    actOut([hint, frame]);
  } catch (e) {
    const title = e instanceof NoShot ? "No screenshot for this one" : "The screenshot could not be prepared";
    actOut([h("h3", {}, title), h("p", {}, e.message)], true);
  }
}

async function doExplain() {
  const f = state.selected;
  actOut([h("p", { class: "muted" }, "Preparing explanation…")]);
  try {
    const ex = await api.explain(state.view.audit_id, f.id);
    actOut([
      h("h3", { class: "explain-title" }, ex.title || ""),
      ...ex.sections.map((s) => h("div", { class: "sec" }, h("h3", {}, s.heading),
        s.items ? h("ul", {}, ...s.items.map((i) => h("li", {}, i))) : h("p", {}, s.body))),
      h("p", { class: "fine" }, ex.grounding),
    ]);
  } catch (e) {
    actOut([h("h3", {}, "Explanation unavailable"), h("p", {}, e.message)], true);
  }
}


// ------------------------------------------------------------------ Ask AURA
async function doAsk(ev) {
  ev.preventDefault();
  const q = $("ask-input").value.trim();
  if (!q || !state.view) return;
  $("ask-input").value = "";
  const log = $("ask-log");
  log.append(h("div", { class: "msg user" }, q));
  const pending = h("div", { class: "msg aura" }, h("span", { class: "muted" }, "Thinking…"));
  log.append(pending);
  log.scrollTop = log.scrollHeight;
  // The finding is read at submit time and sent explicitly. Nothing about "the last question" or "the
  // last finding" exists on either side of this call.
  const askFindingId = state.selected ? state.selected.id : null;
  const currentKey = `${state.view ? state.view.audit_id : "audit"}:${askFindingId || "page"}`;
  try {
    const r = await api.ask(state.view.audit_id, q, askFindingId);
    if (r.state === "OK") {
      const cites = r.cited_finding_ids.map((id) => {
        const f = state.view.findings.find((x) => x.id === id);
        return h("button", { onclick: () => { if (f) { openDetail(f); if (f.target.kind === "element") doHighlight(f); } } }, id);
      });
      pending.replaceChildren(h("div", {}, r.answer),
        cites.length ? h("div", { class: "cite" }, ...cites) : "",
        r.evidence_gaps.length ? h("div", { class: "note" }, `Not covered by the evidence: ${r.evidence_gaps.join("; ")}`) : "",
        h("div", { class: "note" }, r.note));
    } else {
      pending.className = "msg aura unavailable";
      pending.replaceChildren(h("div", {}, r.message || "No answer available."));
    }
  } catch (e) {
    pending.className = "msg aura unavailable";
    pending.replaceChildren(h("div", {}, e.message));
  }
  // Store chat history for this specific finding
  const entries = Array.from(log.children).map((c) => c.cloneNode(true));
  findingChatLogs.set(currentKey, entries);
  log.scrollTop = log.scrollHeight;
}

// ------------------------------------------------------------------ AI provider
// The provider, the model and the key are this browser's own: they are saved in the extension's storage
// and the AURA service is never told any of them. The list of providers and models still comes from the
// service, which documents what each model can do (whether it can be shown a screenshot, for one).
let providerList = [];

function providerRow(p) {
  // The price is part of the choice: someone with no key should see which two cost nothing to try.
  return h("option", { value: p.provider }, p.pricing ? `${p.label} - ${p.pricing}` : p.label);
}

async function refreshProviders() {
  const choice = await getAiChoice();
  try {
    const data = await api.providers();
    providerList = data.providers || [];
  } catch (e) {
    $("provider-status").textContent = e.message;
    return;
  }
  const select = $("provider-select");
  select.replaceChildren(...providerList.map(providerRow));
  select.value = providerList.some((p) => p.provider === choice.provider) ? choice.provider : "mock";
  await applyProviderFields(select.value, choice.model);
}

async function applyProviderFields(providerKey, model) {
  const p = providerList.find((x) => x.provider === providerKey);
  const isMock = !p || p.is_mock;
  show("provider-model-field", !isMock);
  show("provider-key-field", !isMock);
  const saved = await getAiChoice();
  const chosenModel = (providerKey === saved.provider && (model || saved.model)) || (p ? p.default_model || "" : "");
  $("provider-model").value = chosenModel;
  $("provider-models").replaceChildren(...((p && p.models) || []).map((m) => h("option", { value: m })));
  const storedKey = isMock ? "" : await getProviderKey(providerKey);
  $("provider-key").value = "";
  $("provider-key").placeholder = storedKey
    ? "A key is saved in this browser. Type a new one to replace it, or save empty to remove it."
    : "Your key. Saved in this browser only, sent only to this provider.";
  const free = p && p.pricing === "free tier";
  $("provider-status").textContent = isMock
    ? "Mock AI returns scripted findings for demos and tests. It is not real model analysis."
    : (storedKey ? "" : (free ? `${p.label} has a free tier: get a key, paste it here, then test the connection.`
                              : `${p.label} needs a funded account. Groq and Gemini are free to try.`))
      + (p && p.model_capabilities && chosenModel && p.model_capabilities[chosenModel]
         && p.model_capabilities[chosenModel].image_input === false
         ? " This model cannot be shown images, so the scan will send text evidence only." : "");
}

async function saveProvider() {
  const provider = $("provider-select").value;
  const model = $("provider-model").value.trim();
  const typedKey = $("provider-key").value;
  $("provider-status").textContent = "Saving…";
  try {
    await setAiChoice(provider, model);
    // Only touched when something was typed, so saving a model does not wipe a key already stored.
    if (typedKey !== "") await setProviderKey(provider, typedKey);
    $("provider-key").value = "";
    const label = (providerList.find((p) => p.provider === provider) || {}).label || provider;
    await refreshHealth();
    await applyProviderFields(provider, model);
    const needsKey = callsProviderInBrowser(provider) && !(await getProviderKey(provider));
    $("provider-status").textContent = needsKey
      ? `Saved, but ${label} has no API key yet: the next scan cannot ask it for anything.`
      : `Saved in this browser. The next scan will ask ${label}${model ? " / " + model : ""} directly.`;
  } catch (e) {
    $("provider-status").textContent = e.message;
  }
}

// Checks the key against the provider without running the model: a person should never be charged for a
// request just to learn whether their key works.
async function testProvider() {
  const provider = $("provider-select").value;
  $("provider-status").textContent = "Testing…";
  try {
    if (!callsProviderInBrowser(provider)) {
      const r = await api.testProvider();
      $("provider-status").textContent = `${r.status === "READY" ? "READY" : r.status} — ${r.detail || ""}`;
    } else {
      const r = await checkProviderKey({
        provider, model: $("provider-model").value.trim(), apiKey: await getProviderKey(provider),
      });
      const label = { READY: "READY", NOT_CONFIGURED: "NO KEY SAVED", AUTH_INVALID: "KEY REJECTED",
                      MODEL_UNAVAILABLE: "MODEL UNAVAILABLE", RATE_LIMITED: "RATE LIMITED",
                      CONNECTION_FAILED: "CONNECTION FAILED" }[r.status] || r.status;
      $("provider-status").textContent = `${label} — ${r.detail || ""}`;
    }
  } catch (e) {
    $("provider-status").textContent = `CONNECTION FAILED — ${e.message}`;
  }
  refreshHealth();
}

// ------------------------------------------------------------------ wiring
$("scan").addEventListener("click", runScan);
$("provider-toggle").addEventListener("click", async () => {
  const opening = $("provider-card").classList.contains("hidden");
  show("provider-card", opening);
  if (opening) await refreshProviders();
});
$("provider-close").addEventListener("click", () => show("provider-card", false));
$("provider-select").addEventListener("change", (e) => { applyProviderFields(e.target.value, null); });
$("provider-save").addEventListener("click", saveProvider);
$("provider-test").addEventListener("click", testProvider);
$("score-why").addEventListener("click", () => $("score-help").classList.toggle("hidden"));
$("coverage-why").addEventListener("click", () => $("coverage-help").classList.toggle("hidden"));
$("settings").addEventListener("click", () => chrome.runtime.openOptionsPage());
$("back").addEventListener("click", () => { clearPageMarks(); state.selected = null; renderResults(state.view); });
$("act-highlight").addEventListener("click", () => doHighlight());
$("act-shot").addEventListener("click", doScreenshot);
$("act-explain").addEventListener("click", doExplain);
$("ask-form").addEventListener("submit", doAsk);
chrome.storage.onChanged.addListener(() => refreshHealth());

refreshHealth();
restoreAuditRefs().then(refreshTabState);
