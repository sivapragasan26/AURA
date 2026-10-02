// Client for the local AURA API. The extension holds only the backend URL and the pairing token;
// AI provider keys live on the AURA server and are never sent to or stored in the extension.
export const DEFAULT_BACKEND = "http://127.0.0.1:8765";

export async function getSettings() {
  const s = await chrome.storage.local.get({ backendUrl: DEFAULT_BACKEND, token: "" });
  return { backendUrl: (s.backendUrl || DEFAULT_BACKEND).replace(/\/+$/, ""), token: s.token || "" };
}

export class ApiError extends Error {
  constructor(message, { status = 0, code = "NETWORK", detail = null } = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

async function request(path, { method = "GET", body = undefined, timeoutMs = 180000 } = {}) {
  const { backendUrl, token } = await getSettings();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(`${backendUrl}${path}`, {
      method,
      headers: { "Content-Type": "application/json", "X-AURA-Token": token },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctrl.signal,
    });
  } catch (e) {
    throw new ApiError(
      e.name === "AbortError" ? "The AURA server did not respond in time." :
      `Cannot reach the AURA server at ${backendUrl}. Start it with: python -m aura.api`,
      { code: e.name === "AbortError" ? "TIMEOUT" : "UNREACHABLE" });
  } finally {
    clearTimeout(timer);
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

// The per-finding screenshot comes back as a PNG, not JSON, so it bypasses `request`.
export async function findingShot(auditId, findingId) {
  const { backendUrl, token } = await getSettings();
  const url = `${backendUrl}/api/audits/${encodeURIComponent(auditId)}/findings/${encodeURIComponent(findingId)}`
    + "/screenshot";
  let res;
  try {
    res = await fetch(url, { headers: { "X-AURA-Token": token } });
  } catch (e) {
    throw new ApiError("Cannot reach the AURA server for the screenshot.", { code: "UNREACHABLE" });
  }
  if (!res.ok) {
    let message = `The screenshot could not be produced (HTTP ${res.status}).`;
    try { const body = await res.json(); if (body && body.error) message = body.error.message || message; } catch (_) {}
    throw new ApiError(message, { status: res.status, code: "NO_SHOT" });
  }
  return URL.createObjectURL(await res.blob());
}

export const api = {
  health: () => request("/api/health", { timeoutMs: 5000 }),
  interactionPlan: (pageUrl, elements) => request("/api/interaction-plan", { method: "POST", body: { page_url: pageUrl, elements } }),
  createAudit: (bundle, options) => request("/api/audits", { method: "POST", body: { bundle, options }, timeoutMs: 240000 }),
  getAudit: (id) => request(`/api/audits/${encodeURIComponent(id)}`),
  explain: (id, fid) => request(`/api/audits/${encodeURIComponent(id)}/findings/${encodeURIComponent(fid)}/explain`, { method: "POST", body: {} }),
  providers: () => request("/api/providers"),
  selectProvider: (provider, model, apiKey) => request("/api/providers/select", { method: "POST", body: { provider, model, api_key: apiKey } }),
  testProvider: () => request("/api/providers/test", { method: "POST", body: {}, timeoutMs: 45000 }),
  ask: (id, question, findingId) => request(`/api/audits/${encodeURIComponent(id)}/ask`, { method: "POST", body: { question, finding_id: findingId || null } }),
};
