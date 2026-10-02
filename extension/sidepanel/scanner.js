// Collects AURA evidence from the CURRENT tab, in the user's own browser session, and sends it to the
// local AURA engine. Nothing is collected until the user clicks "Scan current page".
//
// Collected (all bounded): DOM structure/geometry/computed styles via the engine's own extraction script
// (form-field values excluded), axe-core results (no HTML snippets), runtime errors raised during the scan,
// failed resource loads (Resource Timing API), optional safe interactions, one viewport screenshot.
// Never collected: cookies, storage, passwords or typed field values, browsing history, other tabs.
import { api } from "./api.js";
import {
  installRuntimeProbe, readRuntimeProbe, removeRuntimeProbe,
  extractDom, agentPageInfo, agentFacts, agentClick, agentRunAxe, clearPageOverlays,
  pageScrollMetrics, pageScrollTo, pageHoldSticky, pageBoxesFor, pageMainContentBottom,
} from "./page_functions.js";

export const COLLECTOR_VERSION = "aura-extension/0.5.0";

export class ScanError extends Error {
  constructor(message, code = "SCAN_FAILED") { super(message); this.code = code; }
}

export async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) throw new ScanError("No active tab found.", "NO_TAB");
  return tab;
}

function explainAccessError(e) {
  const msg = String(e && e.message || e);
  if (/chrome:\/\/|chrome-extension:\/\/|extensions gallery|webstore|edge:\/\//i.test(msg)) {
    return new ScanError("Browser-internal pages (chrome://, the Web Store, other extensions) cannot be scanned.", "RESTRICTED_PAGE");
  }
  if (/file:\/\//i.test(msg)) {
    return new ScanError("Local files need 'Allow access to file URLs' enabled for AURA in chrome://extensions.", "RESTRICTED_PAGE");
  }
  if (/Cannot access|permission|host/i.test(msg)) {
    return new ScanError("AURA has no access to this tab yet. Click the AURA toolbar icon while this tab is open to grant access to this page, then scan again.", "NO_ACCESS");
  }
  return new ScanError(`Could not run in this page: ${msg.slice(0, 200)}`, "INJECTION_FAILED");
}

async function exec(tabId, opts) {
  try {
    const [res] = await chrome.scripting.executeScript({ target: { tabId, frameIds: [0] }, ...opts });
    return res ? res.result : undefined;
  } catch (e) {
    throw explainAccessError(e);
  }
}

export async function ensureAgent(tabId) {
  await exec(tabId, { files: ["content/page_agent.js"] });
}

function stripUrl(u) {
  if (typeof u !== "string") return u;
  const t = u.trim();
  if (t === "" || t === "#" || t.toLowerCase().startsWith("javascript:")) return t.toLowerCase().startsWith("javascript:") ? "javascript:" : t;
  if (t.startsWith("#")) return "#";
  try { const x = new URL(t, "http://relative.invalid"); return x.origin === "http://relative.invalid" ? x.pathname : x.origin + x.pathname; }
  catch (_) { return t.split(/[?#]/)[0]; }
}

// Viewport screenshot, downscaled to CSS pixels so element boxes and screenshot coordinates agree
// (the engine's Playwright collector also captures at device scale factor 1).
async function captureViewport(windowId, viewport) {
  const dataUrl = await chrome.tabs.captureVisibleTab(windowId, { format: "png" });
  const blob = await (await fetch(dataUrl)).blob();
  const bmp = await createImageBitmap(blob);
  let out = blob;
  if (bmp.width !== viewport.width) {
    const canvas = new OffscreenCanvas(viewport.width, Math.round(bmp.height * viewport.width / bmp.width));
    canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
    out = await canvas.convertToBlob({ type: "image/png" });
  }
  const buf = new Uint8Array(await out.arrayBuffer());
  let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return btoa(bin);
}

// Full-page capture for the panel's per-finding screenshots. A screenshot only covers what is on screen,
// which left every finding below the fold with nothing to show. The page is scrolled in viewport-sized
// steps, each slice is captured and the slices are stitched into one tall image, then scaled so its width
// matches CSS pixels (element boxes are in CSS pixels, so the two agree).
// The result is used ONLY for the panel. The AI still receives the single viewport capture, so the size of
// what is sent to the provider does not change.
const SHOT_MAX_SLICES = 12;
const SHOT_MAX_CSS_HEIGHT = 9000;
const SHOT_MAX_CSS_WIDTH = 900;
const SHOT_CAPTURE_GAP_MS = 600;   // captureVisibleTab is rate limited; stay under it
const SHOT_SETTLE_MS = 260;        // let sticky bars and lazy content settle after scrolling
const SHOT_TIME_BUDGET_MS = 9000;  // a scan must not stall on a page that grows as you scroll

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function captureFullPage(tabId, windowId, viewport, onNote) {
  const started = Date.now();
  const metrics = await exec(tabId, { func: pageScrollMetrics });
  const startHeight = Math.max(metrics.scrollHeight, metrics.innerHeight);

  // How far to go. A feed has no bottom — scrolling loads more — so the main content decides the limit,
  // not the document height.
  let mainBottom = 0;
  try { mainBottom = await exec(tabId, { func: pageMainContentBottom }); } catch (_) { mainBottom = 0; }
  const contentLimit = mainBottom > metrics.innerHeight ? Math.min(mainBottom, startHeight) : startHeight;
  const cssHeight = Math.min(contentLimit, SHOT_MAX_SLICES * metrics.innerHeight, SHOT_MAX_CSS_HEIGHT);
  if (cssHeight <= metrics.innerHeight * 1.15) return null;   // one screen covers it already

  const scale = Math.min(1, SHOT_MAX_CSS_WIDTH / viewport.width);
  const canvas = new OffscreenCanvas(Math.round(viewport.width * scale), Math.round(cssHeight * scale));
  const ctx = canvas.getContext("2d");
  let captured = 0;
  let stopped = "reached the end of the main content";

  await exec(tabId, { func: pageHoldSticky, args: [true] }).catch(() => {});
  try {
    for (let i = 0; i < SHOT_MAX_SLICES; i++) {
      const y = i * metrics.innerHeight;
      if (y >= cssHeight) break;
      if (Date.now() - started > SHOT_TIME_BUDGET_MS) { stopped = "time limit for capturing reached"; break; }

      await exec(tabId, { func: pageScrollTo, args: [y] });
      await sleep(i === 0 ? SHOT_SETTLE_MS : SHOT_CAPTURE_GAP_MS);

      let bmp;
      try {
        const dataUrl = await chrome.tabs.captureVisibleTab(windowId, { format: "png" });
        bmp = await createImageBitmap(await (await fetch(dataUrl)).blob());
      } catch (_) {
        stopped = "the browser stopped allowing captures";
        break;
      }
      // The capture is in device pixels; draw it at CSS scale into its slice of the tall canvas.
      const drawH = (bmp.height * viewport.width / bmp.width) * scale;
      ctx.drawImage(bmp, 0, 0, bmp.width, bmp.height, 0, Math.round(y * scale), canvas.width, Math.round(drawH));
      bmp.close();
      captured += 1;

      // Did scrolling make the page longer? Then it loads as you go and there is no bottom to reach.
      // Stop here rather than chasing it: what matters is the content, not the endless feed below it.
      const now = await exec(tabId, { func: pageScrollMetrics }).catch(() => null);
      if (now && now.scrollHeight > startHeight + metrics.innerHeight) {
        stopped = "the page keeps loading more as you scroll, so AURA stopped at the content it had";
        break;
      }
    }
  } finally {
    await exec(tabId, { func: pageHoldSticky, args: [false] }).catch(() => {});
    await exec(tabId, { func: pageScrollTo, args: [metrics.scrollY] }).catch(() => {});
  }
  if (captured < 2) return null;

  // Only keep the part actually captured, so a feed that stopped early does not leave a blank tail.
  const filled = Math.min(canvas.height, Math.round(captured * metrics.innerHeight * scale));
  let out = canvas;
  if (filled < canvas.height) {
    out = new OffscreenCanvas(canvas.width, filled);
    out.getContext("2d").drawImage(canvas, 0, 0, canvas.width, filled, 0, 0, canvas.width, filled);
  }
  if (onNote) onNote(`${captured} screens · ${out.width}×${out.height} · ${stopped}`);
  return await blobToBase64(await out.convertToBlob({ type: "image/png" }));
}

async function blobToBase64(blob) {
  const buf = new Uint8Array(await blob.arrayBuffer());
  let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return btoa(bin);
}

const INTERACTIVE = new Set(["button", "a", "input"]);

/**
 * @param {{useAI: boolean, interactions: boolean, onStep: (label: string, state: string, detail?: string) => void}} opts
 */
export async function scanCurrentPage({ useAI, interactions, onStep }) {
  const step = onStep || (() => {});
  const tab = await getActiveTab();
  const tabId = tab.id;

  step("Preparing page", "running");
  await exec(tabId, { func: clearPageOverlays }).catch(() => {});
  await ensureAgent(tabId);
  await exec(tabId, { world: "MAIN", func: installRuntimeProbe });
  let probeInstalled = true;
  try {
    const info = await exec(tabId, { func: agentPageInfo });
    step("Preparing page", "done", new URL(info.url).host);

    step("Reading page structure", "running");
    await exec(tabId, { files: ["content/dom_extraction.js"] });
    const dom = await exec(tabId, { func: extractDom });
    for (const e of dom.elements) { if (e.href) e.href = stripUrl(e.href); if (e.src) e.src = stripUrl(e.src); }
    step("Reading page structure", "done", `${dom.elements.length} elements`);

    step("Capturing screenshot", "running");
    let screenshot = null;
    let fullPage = null;
    try {
      screenshot = await captureViewport(tab.windowId, info.viewport);
      step("Capturing screenshot", "done");
    } catch (e) {
      step("Capturing screenshot", "warn", "not available");
    }

    step("Accessibility scan (axe-core)", "running");
    await exec(tabId, { files: ["vendor/axe.min.js"] });
    const axe = await exec(tabId, { func: agentRunAxe });

    // Where the reported elements sit on the page, so the panel can crop the screenshot to a finding.
    // axe reports its own CSS paths, which never match the selectors the DOM extractor produces, so they
    // are resolved here while the page is still exactly as it was captured.
    let targetBoxes = {};
    try {
      const axeSelectors = [];
      for (const v of (axe && axe.violations) || []) {
        for (const n of v.nodes || []) {
          for (const t of n.target || []) if (typeof t === "string") axeSelectors.push(t);
        }
      }
      const wanted = [...new Set(axeSelectors)].slice(0, 400);
      if (wanted.length) targetBoxes = await exec(tabId, { func: pageBoxesFor, args: [wanted] });
    } catch (_) {
      targetBoxes = {};   // no regions simply means no screenshots offered for those findings
    }
    step("Accessibility scan (axe-core)", axe.available ? "done" : "warn",
      axe.available ? `${axe.violations.length} rule violations` : "axe-core could not run");

    // The full-page capture goes LAST. It scrolls the page, and on a feed that loads as you scroll that
    // changes the document; doing it earlier meant axe examined a bigger page than the structure scan did.
    // Everything else has been collected by now, so scrolling can no longer affect any of it.
    if (screenshot) {
      step("Capturing the whole page", "running");
      try {
        fullPage = await captureFullPage(tabId, tab.windowId, info.viewport,
                                         (note) => step("Capturing the whole page", "done", note));
        if (!fullPage) step("Capturing the whole page", "done", "one screen covers the main content");
      } catch (e) {
        fullPage = null;
        step("Capturing the whole page", "warn", "not available");
      }
    }

    const interactionLog = [];
    if (interactions) {
      step("Safe interaction test", "running");
      const selectors = dom.elements
        .filter((e) => e.visible && e.selector && (INTERACTIVE.has(e.tag) || e.role === "button"))
        .map((e) => e.selector);
      const facts = await exec(tabId, { func: agentFacts, args: [selectors] });
      const plan = await api.interactionPlan(stripUrl(info.url), facts);
      for (const item of plan.plan) {
        const before = await exec(tabId, { world: "MAIN", func: readRuntimeProbe, args: [0] });
        const entry = await exec(tabId, { func: agentClick, args: [item] });
        const after = await exec(tabId, { world: "MAIN", func: readRuntimeProbe, args: [before.count] });
        entry.errors_after_action = after.events.filter((ev) => ev.type !== "warning").map((ev) => ev.text).slice(0, 3);
        entry.triggered_errors = after.events.filter((ev) => ev.type !== "warning");
        interactionLog.push(entry);
        if (entry.url_changed) break; // the page changed route: stop, do not act on a different page
      }
      const executed = interactionLog.filter((e) => e.status === "executed").length;
      step("Safe interaction test", "done", `${executed} clicked · ${plan.blocked.length} unsafe controls skipped`);
    }

    step("Collecting runtime signals", "running");
    const rt = await exec(tabId, { world: "MAIN", func: readRuntimeProbe, args: [0] });
    // Attribute each error to the control whose click raised it (same as the Playwright collector)
    const raisedBy = new Map();
    for (const entry of interactionLog) {
      for (const ev of entry.triggered_errors || []) raisedBy.set(`${ev.type}|${ev.text}`, entry.element_selector);
      delete entry.triggered_errors;
    }
    const console_ = rt.events.map((ev) => {
      const by = raisedBy.get(`${ev.type}|${ev.text}`);
      const match = by ? { element_selector: by } : null;
      return { type: ev.type, text: ev.text, location: ev.location ? stripUrl(ev.location.replace(/:\d+$/, "")) + (ev.location.match(/:\d+$/) || [""])[0] : null,
               triggered_by: match ? match.element_selector : null };
    });
    step("Collecting runtime signals", "done", `${console_.filter((c) => c.type !== "warning").length} errors · ${info.network_failures.length} failed requests`);

    const bundle = {
      source: "extension",
      collector_version: COLLECTOR_VERSION,
      url: stripUrl(info.url),
      title: info.title,
      viewport: info.viewport,
      dom,
      axe,
      telemetry: {
        capture_scope: "post_load",
        page_load_time_ms: info.load_time_ms,
        console: console_,
        network: info.network_failures.map((n) => ({ url: stripUrl(n.url), status: n.status, status_text: "", method: n.method })),
      },
      interactions: interactionLog,
      screenshot_png_base64: screenshot,
      screenshot_fullpage_png_base64: fullPage,
      target_boxes: targetBoxes,
      captured_at: new Date().toISOString(),
    };

    await exec(tabId, { world: "MAIN", func: removeRuntimeProbe }).catch(() => {});
    probeInstalled = false;

    step(useAI ? "AURA analysis (deterministic + AI + verification)" : "AURA analysis (deterministic only)", "running");
    const view = await api.createAudit(bundle, { ai: useAI });
    step(useAI ? "AURA analysis (deterministic + AI + verification)" : "AURA analysis (deterministic only)", "done",
      `${view.findings.length} findings`);
    return { view, tabId, windowId: tab.windowId };
  } finally {
    if (probeInstalled) await exec(tabId, { world: "MAIN", func: removeRuntimeProbe }).catch(() => {});
  }
}
