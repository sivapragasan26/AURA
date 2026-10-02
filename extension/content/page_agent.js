// AURA in-page agent (isolated content-script world). Injected by the side panel ONLY when the user acts
// (scan / highlight), never automatically on page load.
//
// Everything AURA draws lives in one closed Shadow DOM host marked [data-aura-overlay], so the site's CSS
// cannot restyle it and AURA's DOM evidence extraction ignores it. Highlight overlays are removed on demand,
// when the side panel closes, or when the page reloads. Nothing is ever sent to the site's server.
(() => {
  if (globalThis.__AURA_AGENT__) return;

  const OVERLAY_ATTR = "data-aura-overlay";
  const state = { host: null, root: null, boxes: [], raf: 0 };

  // ------------------------------------------------------------------ overlay
  function ensureOverlay() {
    if (state.host && state.host.isConnected) return state.root;
    const host = document.createElement("div");
    host.setAttribute(OVERLAY_ATTR, "");
    host.style.cssText = "all: initial; position: fixed; inset: 0; pointer-events: none; z-index: 2147483647;";
    const root = host.attachShadow({ mode: "closed" });
    root.innerHTML = `<style>
      .box { position: fixed; border: 2px solid #7c3aed; border-radius: 4px; background: rgba(124,58,237,.10);
             box-shadow: 0 0 0 4px rgba(124,58,237,.25); transition: all .12s ease-out; }
      .tag { position: absolute; left: -2px; top: -24px; font: 600 11px/18px system-ui, sans-serif; color: #fff;
             background: #7c3aed; padding: 2px 6px; border-radius: 4px 4px 4px 0; white-space: nowrap;
             max-width: 320px; overflow: hidden; text-overflow: ellipsis; }
      .tag.below { top: auto; bottom: -24px; border-radius: 0 4px 4px 4px; }
    </style>`;
    document.documentElement.appendChild(host);
    state.host = host;
    state.root = root;
    const reposition = () => {
      cancelAnimationFrame(state.raf);
      state.raf = requestAnimationFrame(positionBoxes);
    };
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    state.reposition = reposition;
    return root;
  }

  function positionBoxes() {
    for (const b of state.boxes) {
      const r = b.el.getBoundingClientRect();
      b.node.style.left = `${r.left - 3}px`;
      b.node.style.top = `${r.top - 3}px`;
      b.node.style.width = `${Math.max(r.width, 4) + 6}px`;
      b.node.style.height = `${Math.max(r.height, 4) + 6}px`;
      b.tag.classList.toggle("below", r.top < 30);
    }
  }

  function clearHighlight() {
    for (const b of state.boxes) b.node.remove();
    state.boxes = [];
    maybeRemoveHost();
  }

  function maybeRemoveHost() {
    if (state.boxes.length || !state.host) return;
    window.removeEventListener("scroll", state.reposition, true);
    window.removeEventListener("resize", state.reposition);
    state.host.remove();
    state.host = state.root = null;
  }

  // ------------------------------------------------------------------ target resolution
  const norm = (t) => (t || "").replace(/\s+/g, " ").trim().toLowerCase();
  const pagePath = (u) => { try { const x = new URL(u); return x.origin + x.pathname; } catch (_) { return ""; } };

  function visible(el) {
    if (!el || el.nodeType !== 1) return false;
    if (el.closest(`[${OVERLAY_ATTR}]`)) return false;
    return el.getClientRects().length > 0;
  }

  function accessibleNameOf(el) {
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const parts = labelledBy.split(/\s+/).map((id) => {
        const n = document.getElementById(id);
        return n ? n.innerText || "" : "";
      });
      if (parts.join(" ").trim()) return parts.join(" ");
    }
    return el.getAttribute("aria-label") || el.getAttribute("title") || el.getAttribute("alt")
      || el.getAttribute("placeholder") || el.innerText || el.value || "";
  }

  function roleOf(el) {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit.toLowerCase();
    const tag = el.tagName.toLowerCase();
    if (tag === "a") return el.hasAttribute("href") ? "link" : "";
    if (tag === "button") return "button";
    if (tag === "input") {
      const t = (el.getAttribute("type") || "text").toLowerCase();
      if (t === "search") return "searchbox";
      if (["button", "submit", "reset"].includes(t)) return "button";
      if (t === "checkbox" || t === "radio") return t;
      return "textbox";
    }
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    if (/^h[1-6]$/.test(tag)) return "heading";
    if (tag === "img") return "img";
    return "";
  }

  function resolveUnique(selector) {
    let nodes;
    try {
      nodes = Array.from(document.querySelectorAll(selector)).filter((n) => !n.closest(`[${OVERLAY_ATTR}]`));
    } catch (_) {
      return { status: "invalid_selector", count: 0 };
    }
    if (nodes.length === 0) return { status: "not_found", count: 0 };
    if (nodes.length > 1) return { status: "ambiguous", count: nodes.length, nodes };
    return { status: "unique", count: 1, el: nodes[0], nodes };
  }

  // ---- confidence-ranked fallback resolution -------------------------------------------------------
  // Real sites rebuild the DOM constantly: generated class names, React ids, lazy loading, rerenders. A
  // finding's recorded CSS selector is therefore the FIRST strategy, not the only one. Each strategy below
  // is tried in order and only accepted when it lands on exactly one element, so AURA never guesses and
  // never highlights a container it merely happens to find.
  function candidatesByRole(role, tag) {
    const sel = [];
    if (role) sel.push(`[role="${role}"]`);
    if (tag) sel.push(tag);
    if (role === "button") sel.push("button", 'input[type="button"]', 'input[type="submit"]');
    if (role === "link") sel.push("a[href]");
    if (role === "searchbox") sel.push('input[type="search"]');
    if (role === "textbox") sel.push("input", "textarea");
    if (role === "heading") sel.push("h1", "h2", "h3", "h4", "h5", "h6");
    if (role === "img") sel.push("img", "svg");
    if (!sel.length) sel.push("a, button, input, select, textarea, [role]");
    let nodes = [];
    try {
      nodes = Array.from(document.querySelectorAll([...new Set(sel)].join(",")));
    } catch (_) {
      return [];
    }
    return nodes.filter(visible);
  }

  function uniqueBy(nodes, predicate) {
    const hits = nodes.filter(predicate);
    if (hits.length === 1) return hits[0];
    return null;
  }

  function stableAttributeSelectors(selector) {
    // Pull the parts of a recorded selector that survive a rerender: ids, test ids, names, aria labels.
    const out = [];
    const id = /#([A-Za-z0-9_\-]+)/.exec(selector || "");
    if (id) out.push(`#${CSS.escape(id[1])}`, `[id="${id[1]}"]`);
    const attr = /\[(data-testid|data-test|data-qa|name|aria-label)=["']?([^"'\]]+)["']?\]/.exec(selector || "");
    if (attr) out.push(`[${attr[1]}="${attr[2]}"]`);
    return out;
  }

  function resolveTarget({ selectors, text, accessibleName, role, tag }) {
    const tried = [];
    const wanted = norm(text);
    const wantedName = norm(accessibleName);

    // 1. The exact selector recorded during the scan.
    for (const sel of (selectors || []).slice(0, 20)) {
      const r = resolveUnique(sel);
      tried.push({ strategy: "EXACT_SELECTOR", selector: sel, status: r.status, count: r.count });
      if (r.status === "unique") return { el: r.el, strategy: "EXACT_SELECTOR", selector: sel, tried };
    }

    // 2. The selector still matches, but several elements: the recorded text picks the right one.
    if (wanted) {
      for (const sel of (selectors || []).slice(0, 20)) {
        const r = resolveUnique(sel);
        if (r.status !== "ambiguous") continue;
        const hit = uniqueBy(r.nodes.filter(visible), (n) => norm(n.innerText || n.value) === wanted);
        if (hit) {
          tried.push({ strategy: "SELECTOR_PLUS_TEXT", selector: sel, status: "unique", count: 1 });
          return { el: hit, strategy: "SELECTOR_PLUS_TEXT", selector: sel, tried };
        }
      }
    }

    // 3. Visible text together with the element's role.
    if (wanted) {
      const pool = candidatesByRole(role, tag);
      let hit = uniqueBy(pool, (n) => norm(n.innerText || n.value) === wanted);
      if (!hit) hit = uniqueBy(pool, (n) => norm(n.innerText || n.value).startsWith(wanted) && wanted.length >= 3);
      tried.push({ strategy: "VISIBLE_TEXT_AND_ROLE", status: hit ? "unique" : "no_unique_match", count: pool.length });
      if (hit) return { el: hit, strategy: "VISIBLE_TEXT_AND_ROLE", tried };
    }

    // 4. The accessible name together with the element's role.
    if (wantedName) {
      const pool = candidatesByRole(role, tag);
      const hit = uniqueBy(pool, (n) => norm(accessibleNameOf(n)) === wantedName);
      tried.push({ strategy: "ACCESSIBLE_NAME_AND_ROLE", status: hit ? "unique" : "no_unique_match", count: pool.length });
      if (hit) return { el: hit, strategy: "ACCESSIBLE_NAME_AND_ROLE", tried };
    }

    // 5. Attributes that tend to survive a rebuild: id, test id, name.
    for (const sel of (selectors || []).slice(0, 20)) {
      for (const stable of stableAttributeSelectors(sel)) {
        const r = resolveUnique(stable);
        tried.push({ strategy: "STABLE_ATTRIBUTE", selector: stable, status: r.status, count: r.count });
        if (r.status === "unique") return { el: r.el, strategy: "STABLE_ATTRIBUTE", selector: stable, tried };
      }
    }

    // 6. The semantic element type plus its text, as a last resort.
    if (wanted && tag) {
      let pool = [];
      try {
        pool = Array.from(document.querySelectorAll(tag)).filter(visible);
      } catch (_) { /* invalid tag */ }
      const hit = uniqueBy(pool, (n) => norm(n.innerText || n.value).includes(wanted) && wanted.length >= 4);
      tried.push({ strategy: "SEMANTIC_TAG_AND_TEXT", status: hit ? "unique" : "no_unique_match", count: pool.length });
      if (hit) return { el: hit, strategy: "SEMANTIC_TAG_AND_TEXT", tried };
    }

    return { el: null, strategy: null, tried };
  }

  const FALLBACK_LABEL = {
    SELECTOR_PLUS_TEXT: "its recorded text",
    VISIBLE_TEXT_AND_ROLE: "its visible text and the kind of control it is",
    ACCESSIBLE_NAME_AND_ROLE: "its accessible name and the kind of control it is",
    STABLE_ATTRIBUTE: "a stable attribute recorded during the scan",
    SEMANTIC_TAG_AND_TEXT: "the element type and its text",
  };

  // Highlights the recorded target, falling back through the ladder above. Never guesses: an ambiguous or
  // missing target is reported with the reason it failed, and nothing is drawn.
  function highlight({ selectors, label, expectedText, accessibleName, role, tag, auditUrl, auditPageKey }) {
    clearHighlight();
    const currentKey = pagePath(location.href);
    const recordedKey = auditPageKey || (auditUrl ? pagePath(auditUrl) : "");
    if (recordedKey && recordedKey !== currentKey) {
      return {
        status: "page_changed",
        message: "This finding belongs to a different page than the one open here. Scan this page again before highlighting.",
      };
    }

    const results = [];
    const hits = [];
    let anyAmbiguous = 0;
    let anyInvalid = false;

    if ((selectors || []).length > 1) {
      // A grouped finding: highlight every recorded target that resolves uniquely on its own.
      for (const sel of selectors.slice(0, 20)) {
        const r = resolveUnique(sel);
        results.push({ selector: sel, status: r.status, count: r.count, strategy: "EXACT_SELECTOR" });
        if (r.status === "unique") hits.push({ el: r.el, sel, strategy: "EXACT_SELECTOR" });
        else if (r.status === "ambiguous") anyAmbiguous += 1;
        else if (r.status === "invalid_selector") anyInvalid = true;
      }
    }

    let strategy = hits.length ? "EXACT_SELECTOR" : null;
    if (!hits.length) {
      const resolved = resolveTarget({ selectors, text: expectedText, accessibleName, role, tag });
      results.push(...resolved.tried);
      anyAmbiguous += resolved.tried.filter((t) => t.status === "ambiguous").length;
      anyInvalid = anyInvalid || resolved.tried.some((t) => t.status === "invalid_selector");
      if (resolved.el) {
        hits.push({ el: resolved.el, sel: resolved.selector || "", strategy: resolved.strategy });
        strategy = resolved.strategy;
      }
    }

    if (!hits.length) {
      // Every failure gets its own reason. There is deliberately no single catch-all message.
      if (anyAmbiguous) {
        return {
          status: "ambiguous", results, strategy: null,
          message: "Several elements match this finding, so AURA did not highlight one automatically.",
        };
      }
      if (anyInvalid) {
        return {
          status: "invalid_selector", results, strategy: null,
          message: "The target AURA recorded cannot be looked up in this page any more.",
        };
      }
      return {
        status: "element_gone", results, strategy: null,
        message: "The element AURA identified is no longer on the page.",
      };
    }
    const root = ensureOverlay();
    hits.forEach((h, i) => {
      const node = document.createElement("div");
      node.className = "box";
      const tag = document.createElement("div");
      tag.className = "tag";
      tag.textContent = hits.length > 1 ? `${label} (${i + 1}/${hits.length})` : label;
      node.appendChild(tag);
      root.appendChild(node);
      state.boxes.push({ el: h.el, node, tag });
    });
    positionBoxes();
    hits[0].el.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
    setTimeout(positionBoxes, 450);
    let textMismatch = false;
    if (expectedText && hits.length === 1) {
      const own = norm(hits[0].el.innerText || hits[0].el.value || hits[0].el.getAttribute("aria-label"));
      textMismatch = !!own && !own.includes(norm(expectedText).slice(0, 40)) && !norm(expectedText).includes(own.slice(0, 40));
    }
    const skippedSelectors = results.filter((r) => r.strategy === "EXACT_SELECTOR" && r.status !== "unique").length;
    const usedFallback = strategy && strategy !== "EXACT_SELECTOR";
    let message = "";
    if (skippedSelectors && hits.length > 1) {
      message = `${hits.length} of the recorded elements were highlighted; ${skippedSelectors} could not be identified uniquely on the page as it is now.`;
    } else if (usedFallback) {
      message = `The recorded target no longer matches, so AURA located the element by ${FALLBACK_LABEL[strategy] || "a fallback match"}.`;
    } else if (textMismatch) {
      message = "Highlighted, but this element's text differs from the scan: the page may have changed.";
    }
    return {
      status: skippedSelectors && hits.length > 1 ? "partial" : "highlighted",
      highlighted: hits.length, results, strategy, text_mismatch: textMismatch, message,
    };
  }

  // ------------------------------------------------------------------ page facts / interactions
  function pageInfo() {
    const nav = performance.getEntriesByType("navigation")[0];
    const failures = [];
    const add = (e, initiator) => {
      if (e.responseStatus && e.responseStatus >= 400) failures.push({ url: e.name, status: e.responseStatus, method: "GET", initiator });
    };
    if (nav) add(nav, "document");
    for (const e of performance.getEntriesByType("resource")) add(e, e.initiatorType);
    return {
      url: location.href,
      title: document.title || "",
      viewport: { width: Math.round(window.innerWidth), height: Math.round(window.innerHeight) },
      dpr: window.devicePixelRatio || 1,
      load_time_ms: nav ? Math.round(nav.domContentLoadedEventEnd || nav.duration || 0) : 0,
      network_failures: failures.slice(0, 200),
    };
  }

  const CLIENT_BLOCK_WORDS = /\b(delete|remove|destroy|erase|purge|pay|buy|checkout|purchase|order|subscribe|unsubscribe|billing|password|credit|card|bank|account|transfer|withdraw|deposit|logout|log ?out|sign ?out|send|submit|confirm|save|post|publish|approve|reject|archive|cancel|upload|reset|clear|invite|share|deploy|execute|run)\b/i;

  // Facts the backend policy needs, computed from the live element (e.g. whether a button would submit a form)
  function interactionFacts(selectors) {
    const out = [];
    for (const sel of selectors.slice(0, 400)) {
      const r = resolveUnique(sel);
      if (r.status !== "unique") continue;
      const el = r.el;
      const tag = el.tagName.toLowerCase();
      out.push({
        selector: sel, tag, type: el.getAttribute("type"), role: el.getAttribute("role"),
        href: tag === "a" ? el.getAttribute("href") : null,
        text: (el.innerText || "").trim().slice(0, 100), aria_label: el.getAttribute("aria-label"),
        class: typeof el.className === "string" ? el.className : null,
        visible: el.getClientRects().length > 0, in_form: !!el.closest("form"),
        effective_type: tag === "button" ? (el.type || "submit") : (el.getAttribute("type") || null),
        id_chain: (() => { const ids = []; for (let p = el; p && p.nodeType === 1; p = p.parentElement) if (p.id) ids.push(p.id); return ids; })(),
      });
    }
    return out;
  }

  // Defense in depth: even a backend-approved click is refused here if the live element looks unsafe.
  function clientSafe(el) {
    const tag = el.tagName.toLowerCase();
    const label = `${el.innerText || ""} ${el.getAttribute("aria-label") || ""} ${el.getAttribute("title") || ""}`;
    if (el.isContentEditable || ["input", "textarea", "select", "option", "form"].includes(tag)) return "form field";
    if (tag === "button" && el.type !== "button" && el.closest("form")) return "could submit a form";
    if (tag === "a") {
      const h = (el.getAttribute("href") || "").trim().toLowerCase();
      if (!(h === "" || h === "#" || h.startsWith("javascript:") || (h.startsWith("#") && h.length > 1))) return "link navigation";
      if (el.hasAttribute("download")) return "download link";
    }
    if (CLIENT_BLOCK_WORDS.test(label)) return "state-changing label";
    return null;
  }

  const signature = () => { const t = document.body ? document.body.innerText : ""; return `${t.length}:${t.slice(0, 2000)}`; };

  async function click(item) {
    const entry = {
      hypothesis: `Testing whether '${item.text || item.selector}' produces a visible, error-free result when clicked.`,
      action: "click", target: item.selector, element_selector: item.selector, element_id_chain: [],
      target_text: item.text || "", trigger: "planned", status: "executed",
      reason: "Permitted under the AURA live-session policy.", timestamp: new Date().toISOString().slice(11, 19),
    };
    const r = resolveUnique(item.selector);
    if (r.status !== "unique") return { ...entry, status: "skipped", reason: `Target ${r.status} at click time.` };
    const why = clientSafe(r.el);
    if (why) return { ...entry, status: "blocked", reason: `Blocked in page (${why}).` };
    const ids = []; for (let p = r.el; p && p.nodeType === 1; p = p.parentElement) if (p.id) ids.push(p.id);
    entry.element_id_chain = ids;
    const urlBefore = location.href;
    const sigBefore = signature();
    try {
      r.el.click();
    } catch (e) {
      return { ...entry, status: "failed", reason: `Click raised: ${String(e).slice(0, 160)}` };
    }
    await new Promise((res) => setTimeout(res, 500));
    entry.url_changed = location.href.split("#")[0] !== urlBefore.split("#")[0];
    entry.dom_changed = entry.url_changed || signature() !== sigBefore;
    return entry;
  }

  async function runAxe() {
    if (typeof axe === "undefined") return { available: false, error: "axe-core not loaded" };
    try {
      const res = await axe.run(document, { resultTypes: ["violations"] });
      return {
        available: true, version: axe.version,
        violations: res.violations.map((v) => ({
          id: v.id, impact: v.impact, description: v.description, helpUrl: v.helpUrl,
          nodes: v.nodes.slice(0, 50).map((n) => ({ target: n.target })),  // no HTML snippets (privacy)
        })),
      };
    } catch (e) {
      return { available: false, error: String(e).slice(0, 200) };
    }
  }

  function clearAll() {
    clearHighlight();
    return true;
  }

  globalThis.__AURA_AGENT__ = { highlight, clearHighlight, clearAll, pageInfo, interactionFacts, click, runAxe };
})();
