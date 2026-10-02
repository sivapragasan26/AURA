// AURA service worker.
//
// Page access model (least privilege): AURA can read a page ONLY after the user clicks the AURA toolbar
// icon on that tab. That click is delivered as chrome.action.onClicked and is the gesture that grants
// `activeTab` for the tab. The handler opens the side panel and records the tab as activated.
//
// `openPanelOnActionClick` must stay FALSE: with it enabled, Chrome opens the panel itself, never dispatches
// chrome.action.onClicked and does not grant activeTab, so the panel could never scan the tab.
// The behaviour is persisted in the Chrome profile, so it is reset on every service-worker start (a profile
// that ran an older AURA build keeps `true` otherwise).
import { clearPageOverlays } from "./sidepanel/page_functions.js";
import { createActivationManager } from "./activation.js";

const activation = createActivationManager(chrome);

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false }).catch(() => {});

chrome.action.onClicked.addListener((tab) => {
  // sidePanel.open() must run synchronously inside the user gesture: call it before any await.
  chrome.sidePanel.open({ windowId: tab.windowId }).catch((e) => console.warn("AURA: side panel could not be opened:", e));
  activation.activate(tab);
});

chrome.tabs.onRemoved.addListener((tabId) => { activation.onTabRemoved(tabId); });
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => { activation.onTabUpdated(tabId, changeInfo); });

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  // Only AURA's own extension pages (the side panel) may ask; content scripts and web pages cannot.
  if (!msg || sender.id !== chrome.runtime.id || !sender.url || !sender.url.startsWith(`chrome-extension://${chrome.runtime.id}/`)) {
    return false;
  }
  if (msg.type === "GET_TAB_STATE" && Number.isInteger(msg.tabId)) {
    activation.getState(msg.tabId).then(sendResponse, (e) => sendResponse({ state: "NO_TAB", error: String(e) }));
    return true; // async response
  }
  return false;
});

// Each side panel keeps a port open to announce the tabs it drew on (highlight); when the
// panel closes, those marks are removed. The set is per port: a panel in another window keeps its own.
// If Chrome stops this service worker the port disconnects; the panel reconnects and re-announces its tabs.
chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "aura-panel") return;
  const touchedTabs = new Set();
  port.onMessage.addListener((msg) => {
    if (msg && msg.type === "touched-tab" && Number.isInteger(msg.tabId)) touchedTabs.add(msg.tabId);
  });
  port.onDisconnect.addListener(async () => {
    for (const tabId of touchedTabs) {
      try {
        await chrome.scripting.executeScript({ target: { tabId }, func: clearPageOverlays });
      } catch (_) {
        // tab closed or navigated away: nothing left to clean
      }
    }
    touchedTabs.clear();
  });
});
