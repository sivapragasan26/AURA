import { api, DEFAULT_BACKEND, getSettings } from "../sidepanel/api.js";

const $ = (id) => document.getElementById(id);

function normalizeBackend(raw) {
  const u = new URL((raw || DEFAULT_BACKEND).trim());
  if (u.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(u.hostname)) {
    throw new Error("The AURA server must run on this computer (http://127.0.0.1 or http://localhost).");
  }
  return `${u.protocol}//${u.host}`;
}

async function load() {
  const s = await getSettings();
  $("backend").value = s.backendUrl;
  $("token").value = s.token;
}

async function save() {
  const status = $("status");
  let backendUrl;
  try {
    backendUrl = normalizeBackend($("backend").value);
  } catch (e) {
    status.textContent = e.message;
    return;
  }
  // A non-default port needs host access to that port (requested now, from this user gesture)
  const origin = `${backendUrl}/*`;
  if (!["http://127.0.0.1:8765/*", "http://localhost:8765/*"].includes(origin)) {
    const host = new URL(backendUrl).hostname;
    const granted = await chrome.permissions.request({ origins: [`http://${host}/*`] });
    if (!granted) { status.textContent = "Access to the server address was not granted."; return; }
  }
  await chrome.storage.local.set({ backendUrl, token: $("token").value.trim() });
  status.textContent = "Saved. Testing…";
  try {
    const h = await api.health();
    status.textContent = h.paired
      ? `Connected to AURA ${h.engine_version}. AI provider: ${h.ai.provider}${h.ai.model ? " / " + h.ai.model : ""}.`
      : "Server reachable, but the pairing token is missing or wrong.";
  } catch (e) {
    status.textContent = e.message;
  }
}

$("save").addEventListener("click", save);
$("reveal").addEventListener("change", (e) => { $("token").type = e.target.checked ? "text" : "password"; });
load();
