// Client for the AURA API.
//
// What goes to the AURA service: the page's structure, its accessibility results, its runtime errors and
// its title and address. What never goes there: your AI provider key, and the screenshots. The key stays
// in this extension's own storage and is sent only to the provider you chose (see providers.js); the
// screenshots stay in the browser and are shown to you from here.
//
// The extension registers itself on first use and keeps the token it is given, so there is no pairing
// step. A self-hosted AURA server can still be paired by hand from the options page.

// The hosted service. Change it in Settings to run AURA on your own machine instead.
export const HOSTED_BACKEND = "https://aura-api-vs7e.onrender.com";
export const LOCAL_BACKEND = "http://127.0.0.1:8765";
export const DEFAULT_BACKEND = HOSTED_BACKEND;

const isLocal = (url) => /^http:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/i.test((url || "").replace(/\/+$/, ""));

export async function getSettings() {
  const s = await chrome.storage.local.get({ backendUrl: DEFAULT_BACKEND, token: "" });
  return { backendUrl: (s.backendUrl || DEFAULT_BACKEND).replace(/\/+$/, ""), token: s.token || "" };
}

// The user's AI provider key. Held in this extension's storage, never sent to the AURA service.
export async function getProviderKey(provider) {
  const s = await chrome.storage.local.get({ providerKeys: {} });
  return (s.providerKeys || {})[provider] || "";
}

export async function setProviderKey(provider, key) {
  const s = await chrome.storage.local.get({ providerKeys: {} });
  const keys = { ...(s.providerKeys || {}) };
  if (key && key.trim()) keys[provider] = key.trim();
  else delete keys[provider];
  await chrome.storage.local.set({ providerKeys: keys });
}

export async function hasProviderKey(provider) {
  return !!(await getProviderKey(provider));
}

// Which provider and model this browser will call. Kept here, not on the server: a hosted server is
// shared, and one person's choice must not become everyone's.
export async function getAiChoice() {
  const s = await chrome.storage.local.get({ aiProvider: "mock", aiModel: "" });
  return { provider: s.aiProvider || "mock", model: s.aiModel || "" };
}

export async function setAiChoice(provider, model) {
  await chrome.storage.local.set({ aiProvider: provider, aiModel: (model || "").trim() });
}

export class ApiError extends Error {
  constructor(message, { status = 0, code = "NETWORK", detail = null } = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function unreachable(backendUrl) {
  return isLocal(backendUrl)
    ? `Cannot reach the AURA server at ${backendUrl}. Start it with: python -m aura.api`
    : `Cannot reach the AURA service at ${backendUrl}. Check your connection, or point AURA at a server `
      + "on your own machine in Settings.";
}

// A hosted service may be asleep. A free instance stops after a quiet spell and takes the best part of a
// minute to come back, so the first request after that is slow rather than broken; a server on this
// machine that has not answered in fifteen seconds really is not there.
export const WAKE_TIMEOUT_MS = 60000;
const QUICK_TIMEOUT_MS = 15000;
const quickTimeout = (backendUrl) => (isLocal(backendUrl) ? QUICK_TIMEOUT_MS : WAKE_TIMEOUT_MS);

function timedOut(backendUrl, ms) {
  return isLocal(backendUrl)
    ? "The AURA server did not respond in time."
    : `The AURA service did not answer within ${Math.round(ms / 1000)}s. A free instance sleeps when it `
      + "is not in use and takes a moment to wake; try again shortly.";
}

// First use: ask the service for this install's own token. Nothing identifies you in the request.
async function register(backendUrl) {
  let res;
  // A bare fetch here would wait as long as the browser feels like, which on a sleeping service means a
  // panel that appears to hang on its very first use.
  const ctrl = new AbortController();
  const budget = quickTimeout(backendUrl);
  const timer = setTimeout(() => ctrl.abort(), budget);
  try {
    res = await fetch(`${backendUrl}/api/register`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}", signal: ctrl.signal,
    });
  } catch (e) {
    throw new ApiError(e.name === "AbortError" ? timedOut(backendUrl, budget) : unreachable(backendUrl),
      { code: e.name === "AbortError" ? "TIMEOUT" : "UNREACHABLE" });
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const err = (body && body.error) || {};
    throw new ApiError(err.message || `AURA could not register this install (HTTP ${res.status}).`,
      { status: res.status, code: err.code || "REGISTRATION_FAILED" });
  }
  const data = await res.json();
  if (!data.token) throw new ApiError("The AURA service did not issue a token.", { code: "REGISTRATION_FAILED" });
  await chrome.storage.local.set({ token: data.token });
  return data.token;
}

async function request(path, { method = "GET", body = undefined, timeoutMs = 180000, retryAuth = true } = {}) {
  const { backendUrl, token } = await getSettings();
  const authToken = token || await register(backendUrl);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(`${backendUrl}${path}`, {
      method,
      headers: { "Content-Type": "application/json", "X-AURA-Token": authToken },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctrl.signal,
    });
  } catch (e) {
    throw new ApiError(
      e.name === "AbortError" ? timedOut(backendUrl, timeoutMs) : unreachable(backendUrl),
      { code: e.name === "AbortError" ? "TIMEOUT" : "UNREACHABLE" });
  } finally {
    clearTimeout(timer);
  }
  // A token from a different deployment, or from before a restart, is simply replaced once. A token typed
  // in by hand for a local server is never thrown away: the person chose it.
  if (res.status === 401 && retryAuth && !isLocal(backendUrl)) {
    await chrome.storage.local.set({ token: "" });
    return request(path, { method, body, timeoutMs, retryAuth: false });
  }
  let data = null;
  try { data = await res.json(); } catch (_) { /* non-JSON error */ }
  if (!res.ok) {
    const err = (data && data.error) || {};
    throw new ApiError(err.message || `AURA server error (HTTP ${res.status})`,
      { status: res.status, code: err.code || "HTTP_ERROR", detail: err.detail || err.problems || null });
  }
  return data;
}

export const api = {
  health: async () => request("/api/health", { timeoutMs: quickTimeout((await getSettings()).backendUrl) }),
  interactionPlan: (pageUrl, elements) => request("/api/interaction-plan", { method: "POST", body: { page_url: pageUrl, elements } }),
  // Two-phase scan: the server prepares the prompt, the browser calls the provider, the server verifies.
  // `model` lets the service size the prompt for what that model accepts, and tell this browser how far
  // to shrink its capture: a provider that meters its input refuses an ordinary page otherwise.
  prepareAudit: (bundle, screenshotAttached, model) =>
    request("/api/audits/prepare", {
      method: "POST",
      body: { bundle, screenshot_attached: !!screenshotAttached, model: model || "" },
      timeoutMs: 120000,
    }),
  completeAudit: (auditId, payload) =>
    request(`/api/audits/${encodeURIComponent(auditId)}/complete`, { method: "POST", body: payload, timeoutMs: 120000 }),
  // One request, analysed entirely on the server: a deterministic-only scan, or the built-in demo AI.
  createAudit: (bundle, options) => request("/api/audits", { method: "POST", body: { bundle, options }, timeoutMs: 240000 }),
  getAudit: (id) => request(`/api/audits/${encodeURIComponent(id)}`),
  explain: (id, fid) => request(`/api/audits/${encodeURIComponent(id)}/findings/${encodeURIComponent(fid)}/explain`, { method: "POST", body: {} }),
  providers: () => request("/api/providers"),
  testProvider: () => request("/api/providers/test", { method: "POST", body: {}, timeoutMs: 45000 }),
  // Ask AURA, in the same two halves as a scan and for the same reason: most questions are answered
  // from the finding's own record and never reach a model, and the ones that do are asked by this
  // browser with this browser's key. The service holds none.
  askPrepare: (id, question, findingId) =>
    request(`/api/audits/${encodeURIComponent(id)}/ask/prepare`,
      { method: "POST", body: { question, finding_id: findingId || null } }),
  askComplete: (id, payload) =>
    request(`/api/audits/${encodeURIComponent(id)}/ask/complete`, { method: "POST", body: payload }),
  // One request, with the model called on the server. For a server that holds its own provider key.
  ask: (id, question, findingId) => request(`/api/audits/${encodeURIComponent(id)}/ask`, { method: "POST", body: { question, finding_id: findingId || null } }),
};
