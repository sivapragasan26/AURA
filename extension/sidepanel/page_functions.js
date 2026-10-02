// Functions executed IN the scanned page via chrome.scripting.executeScript({ func }).
// Each must be self-contained: Chrome serializes the function source, so no closures over module scope.

// ---- MAIN world: runtime probe -------------------------------------------------------------------
// Console errors and uncaught exceptions are only observable from the page's own JS world. The probe is
// installed when a scan starts and removed when it ends (console methods are restored), so AURA does not
// keep watching the page. Errors raised before the scan started cannot be recovered this way.
export function installRuntimeProbe() {
  const existing = window.__AURA_RT__;
  if (existing) { existing.events.length = 0; return true; }
  const rt = { events: [], origError: console.error, origWarn: console.warn };
  const fmt = (a) => {
    if (a instanceof Error) return `${a.name}: ${a.message}`;
    if (typeof a === "string") return a;
    try { return JSON.stringify(a).slice(0, 200); } catch (_) { return String(a); }
  };
  const push = (type, text, location) => {
    if (rt.events.length < 200) rt.events.push({ type, text: String(text).slice(0, 500), location: location || null });
  };
  rt.onError = (e) => {
    if (!(e instanceof ErrorEvent)) return; // resource load errors are taken from the Resource Timing API
    const text = e.error ? `${e.error.name || "Error"}: ${e.error.message}` : e.message;
    push("exception", text, e.filename ? `${e.filename}:${e.lineno}` : null);
  };
  rt.onRejection = (e) => {
    const r = e.reason;
    push("exception", `Uncaught (in promise) ${r && r.message ? `${r.name || "Error"}: ${r.message}` : String(r)}`, null);
  };
  window.addEventListener("error", rt.onError, true);
  window.addEventListener("unhandledrejection", rt.onRejection);
  console.error = function (...args) { push("error", args.map(fmt).join(" "), null); return rt.origError.apply(this, args); };
  console.warn = function (...args) { push("warning", args.map(fmt).join(" "), null); return rt.origWarn.apply(this, args); };
  window.__AURA_RT__ = rt;
  return true;
}

export function readRuntimeProbe(since) {
  const rt = window.__AURA_RT__;
  if (!rt) return { events: [], count: 0 };
  return { events: rt.events.slice(since || 0), count: rt.events.length };
}

export function removeRuntimeProbe() {
  const rt = window.__AURA_RT__;
  if (!rt) return false;
  window.removeEventListener("error", rt.onError, true);
  window.removeEventListener("unhandledrejection", rt.onRejection);
  console.error = rt.origError;
  console.warn = rt.origWarn;
  delete window.__AURA_RT__;
  return true;
}

// ---- ISOLATED world: wrappers around content/page_agent.js and content/dom_extraction.js ---------
export function extractDom() {
  return globalThis.__AURA_DOM_EXTRACT({ collectFieldValues: false });
}
export function agentPageInfo() { return globalThis.__AURA_AGENT__.pageInfo(); }
export function agentFacts(selectors) { return globalThis.__AURA_AGENT__.interactionFacts(selectors); }
export function agentClick(item) { return globalThis.__AURA_AGENT__.click(item); }
export function agentRunAxe() { return globalThis.__AURA_AGENT__.runAxe(); }
export function agentHighlight(args) { return globalThis.__AURA_AGENT__.highlight(args); }
export function agentClearHighlight() { globalThis.__AURA_AGENT__.clearHighlight(); return true; }

// ---- full-page capture helpers ---------------------------------------------------------------------
// A screenshot can only cover what is on screen, so a full-page capture is taken by scrolling in steps
// and stitching the slices. These run in the page and leave it exactly as they found it.
export function pageScrollMetrics() {
  const d = document.documentElement;
  const b = document.body;
  return {
    scrollHeight: Math.max(d ? d.scrollHeight : 0, b ? b.scrollHeight : 0),
    innerHeight: window.innerHeight,
    innerWidth: window.innerWidth,
    scrollY: window.scrollY,
  };
}

// How far down the page the MAIN CONTENT reaches, in page coordinates.
//
// Feeds like YouTube have no bottom: scrolling loads more, so "capture the whole page" never finishes.
// The capture stops at the end of the main content instead. The main region is taken from the page's own
// markup where it says so, and otherwise from the largest block of content that starts near the top.
export function pageMainContentBottom() {
  const sy = window.scrollY;
  const named = document.querySelector("main, [role='main'], #main, #content, #primary, #main-content");
  if (named) {
    const r = named.getBoundingClientRect();
    if (r.height > 0) return Math.round(r.bottom + sy);
  }
  // No named main region: take the widest, tallest block that begins in the top third of the page.
  let best = null;
  const limit = window.innerHeight;
  for (const el of document.querySelectorAll("body > *, body > * > *")) {
    const r = el.getBoundingClientRect();
    const top = r.top + sy;
    if (r.width < window.innerWidth * 0.5 || r.height < limit * 0.5 || top > limit) continue;
    if (!best || r.width * r.height > best.area) best = { area: r.width * r.height, bottom: r.bottom + sy };
  }
  return best ? Math.round(best.bottom) : 0;
}

export function pageScrollTo(y) {
  window.scrollTo(0, y);
  return window.scrollY;
}

// Where each of these selectors sits on the page, in page coordinates (not viewport ones) so they line up
// with a full-page capture. Used for the selectors axe reports, which are its own CSS paths and never match
// the ones the DOM extractor generates — without this, accessibility findings had no region to show.
export function pageBoxesFor(selectors) {
  const out = {};
  const sx = window.scrollX, sy = window.scrollY;
  for (const sel of selectors) {
    let el = null;
    try { el = document.querySelector(sel); } catch (_) { continue; }
    if (!el) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    out[sel] = { x: Math.round(r.left + sx), y: Math.round(r.top + sy),
                 width: Math.round(r.width), height: Math.round(r.height) };
  }
  return out;
}

// Headers and bars that stay put would otherwise appear once per slice. They are hidden while the lower
// slices are taken, then restored.
export function pageHoldSticky(hide) {
  const MARK = "data-aura-sticky";
  const STYLE_ID = "__aura_sticky_hold";
  if (!hide) {
    document.querySelectorAll(`[${MARK}]`).forEach((el) => el.removeAttribute(MARK));
    const style = document.getElementById(STYLE_ID);
    if (style) style.remove();
    return 0;
  }
  let marked = 0;
  for (const el of document.querySelectorAll("body *")) {
    const pos = getComputedStyle(el).position;
    if (pos === "fixed" || pos === "sticky") { el.setAttribute(MARK, ""); marked += 1; }
    if (marked > 400) break;
  }
  if (marked && !document.getElementById(STYLE_ID)) {
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `[${MARK}]{visibility:hidden !important}`;
    document.documentElement.appendChild(style);
  }
  return marked;
}

export function clearPageOverlays() {
  if (globalThis.__AURA_AGENT__) globalThis.__AURA_AGENT__.clearAll();
  return true;
}
