// Per-tab activation lifecycle for AURA's least-privilege page access (activeTab).
//
// Chrome grants `activeTab` for a tab only when the user invokes the extension on it: here, a click on
// the AURA toolbar icon, delivered as chrome.action.onClicked. The grant ends when the tab navigates to
// another origin, closes, or the extension reloads. This module records which tabs the user activated,
// never page content: only the tab id, the page origin, and the activation time. It answers the side panel's
// "can I scan the current tab?" question by checking the grant itself (a no-op script injection) instead of
// a generic permissions API, which cannot see activeTab grants.
//
// Kept free of top-level chrome.* calls so it can be unit-tested with a fake chrome object.

export const STORAGE_KEY = "aura.activatedTabs";

export const TabState = Object.freeze({
  NOT_ACTIVATED: "NOT_ACTIVATED", // user has not clicked the AURA icon on this tab (no page access)
  ACTIVATED: "ACTIVATED", // activeTab grant verified: the tab can be scanned
  ACCESS_LOST: "ACCESS_LOST", // was activated, but Chrome revoked the grant (e.g. navigated to another site)
  RESTRICTED: "RESTRICTED", // Chrome never lets extensions script this page (chrome://, Web Store, …)
  NO_TAB: "NO_TAB",
});

const RESTRICTED_RE = /chrome:\/\/|chrome-extension:\/\/|extensions gallery|webstore|edge:\/\/|about:|devtools:|chrome-error:/i;

function originOf(url) {
  try { return new URL(url).origin; } catch (_) { return null; }
}

export function createActivationManager(chromeApi) {
  // Activations in progress, so a state query that arrives before activation has finished waits for it
  // instead of reporting a stale NOT_ACTIVATED (the side panel opens while the click is still being handled).
  const pending = new Map();

  async function load() {
    const data = await chromeApi.storage.session.get(STORAGE_KEY);
    return (data && data[STORAGE_KEY]) || {};
  }

  async function save(map) {
    await chromeApi.storage.session.set({ [STORAGE_KEY]: map });
  }

  async function forget(tabId) {
    const map = await load();
    if (map[tabId]) {
      delete map[tabId];
      await save(map);
    }
  }

  // Harmless probe: injects `() => true`. It reads nothing from the page and succeeds only if Chrome
  // currently lets AURA script this tab.
  async function probe(tabId) {
    try {
      await chromeApi.scripting.executeScript({ target: { tabId, frameIds: [0] }, func: () => true });
      return { ok: true };
    } catch (e) {
      const message = String((e && e.message) || e);
      return { ok: false, restricted: RESTRICTED_RE.test(message), message };
    }
  }

  function notify(message) {
    // The side panel may be closed: nobody listening is expected, not an error.
    Promise.resolve(chromeApi.runtime.sendMessage(message)).catch(() => {});
  }

  // Called from chrome.action.onClicked (the user gesture that grants activeTab for `tab`).
  function activate(tab) {
    const tabId = tab && tab.id;
    if (!Number.isInteger(tabId)) return Promise.resolve({ state: TabState.NO_TAB });
    const work = (async () => {
      let result = await probe(tabId);
      // Right after the click the grant can lag the event by a moment: retry before reporting failure
      for (const delay of [250, 750]) {
        if (result.ok || result.restricted) break;
        await new Promise((r) => setTimeout(r, delay));
        result = await probe(tabId);
      }
      if (!result.ok) {
        await forget(tabId);
        const state = result.restricted ? TabState.RESTRICTED : TabState.NOT_ACTIVATED;
        notify({ type: "TAB_STATE_CHANGED", tabId, state });
        return { tabId, state, reason: result.message };
      }
      const map = await load();
      map[tabId] = { origin: originOf(tab.url), activatedAt: Date.now() };
      await save(map);
      notify({ type: "TAB_ACTIVATED", tabId, state: TabState.ACTIVATED });
      return { tabId, state: TabState.ACTIVATED, origin: map[tabId].origin };
    })();
    pending.set(tabId, work);
    work.finally(() => { if (pending.get(tabId) === work) pending.delete(tabId); });
    return work;
  }

  // Side panel asks: may AURA scan this tab right now?
  async function getState(tabId) {
    if (!Number.isInteger(tabId)) return { state: TabState.NO_TAB };
    if (pending.has(tabId)) await pending.get(tabId).catch(() => {});
    const map = await load();
    const record = map[tabId];
    if (!record) return { tabId, state: TabState.NOT_ACTIVATED };
    if (record.lost) return { tabId, state: TabState.ACCESS_LOST }; // stays until re-activated or closed
    const result = await probe(tabId); // only activated tabs are ever probed
    if (result.ok) return { tabId, state: TabState.ACTIVATED, origin: record.origin, activatedAt: record.activatedAt };
    if (result.restricted) {
      await forget(tabId);
      return { tabId, state: TabState.RESTRICTED };
    }
    map[tabId] = { lost: true }; // the grant was revoked: remember only that, not where the tab went
    await save(map);
    return { tabId, state: TabState.ACCESS_LOST };
  }

  async function onTabRemoved(tabId) {
    pending.delete(tabId);
    await forget(tabId);
  }

  async function onTabUpdated(tabId, changeInfo) {
    if (!changeInfo || !changeInfo.status) return;
    const map = await load();
    if (map[tabId]) notify({ type: "TAB_STATE_CHANGED", tabId });
  }

  return { activate, getState, onTabRemoved, onTabUpdated, probe, _load: load };
}
