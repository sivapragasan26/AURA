// Unit tests for extension/activation.js (run: node --test tests/extension_js/).
// A fake `chrome` models Chrome's activeTab rule: scripting works on a tab only while it holds a grant.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createActivationManager, TabState, STORAGE_KEY } from "../../extension/activation.js";

function fakeChrome({ restricted = new Set() } = {}) {
  const session = {};
  const granted = new Set(); // tabs with a live activeTab grant
  const sent = [];
  const injections = [];
  const chrome = {
    storage: { session: {
      get: async (k) => ({ [k]: session[k] }),
      set: async (o) => Object.assign(session, JSON.parse(JSON.stringify(o))),
    } },
    scripting: {
      executeScript: async ({ target, func }) => {
        injections.push(target.tabId);
        if (restricted.has(target.tabId)) throw new Error("Cannot access a chrome:// URL");
        if (!granted.has(target.tabId)) throw new Error("Cannot access contents of the page. Extension manifest must request permission to access the respective host.");
        return [{ result: func() }];
      },
    },
    runtime: { sendMessage: async (m) => { sent.push(m); } },
  };
  return { chrome, session, granted, sent, injections };
}

const tabA = { id: 11, windowId: 1, url: "https://app.example/dashboard?x=1" };
const tabB = { id: 22, windowId: 1, url: "https://other.example/" };

test("a tab is not activated until the toolbar click, and is never probed before it", async () => {
  const f = fakeChrome();
  const m = createActivationManager(f.chrome);
  assert.equal((await m.getState(tabA.id)).state, TabState.NOT_ACTIVATED);
  assert.deepEqual(f.injections, [], "no page access before the user acts");
});

test("toolbar click activates the tab, stores only id/origin/time, and notifies the panel", async () => {
  const f = fakeChrome();
  const m = createActivationManager(f.chrome);
  f.granted.add(tabA.id); // Chrome grants activeTab on the action click
  const r = await m.activate(tabA);
  assert.equal(r.state, TabState.ACTIVATED);
  assert.deepEqual(Object.keys(f.session[STORAGE_KEY][tabA.id]).sort(), ["activatedAt", "origin"]);
  assert.equal(f.session[STORAGE_KEY][tabA.id].origin, "https://app.example"); // no path, no query
  assert.deepEqual(f.sent.at(-1), { type: "TAB_ACTIVATED", tabId: tabA.id, state: TabState.ACTIVATED });
  assert.equal((await m.getState(tabA.id)).state, TabState.ACTIVATED);
});

test("race: a state query sent while activation is still running waits for it", async () => {
  const f = fakeChrome();
  const m = createActivationManager(f.chrome);
  f.granted.add(tabA.id);
  const activation = m.activate(tabA); // not awaited: the panel asks immediately
  const state = await m.getState(tabA.id);
  assert.equal(state.state, TabState.ACTIVATED);
  await activation;
});

test("each tab needs its own activation; switching back keeps the first tab activated", async () => {
  const f = fakeChrome();
  const m = createActivationManager(f.chrome);
  f.granted.add(tabA.id);
  await m.activate(tabA);
  assert.equal((await m.getState(tabB.id)).state, TabState.NOT_ACTIVATED);
  assert.equal((await m.getState(tabA.id)).state, TabState.ACTIVATED);
});

test("a new tab never inherits another tab's activation", async () => {
  const f = fakeChrome();
  const m = createActivationManager(f.chrome);
  f.granted.add(tabA.id);
  await m.activate(tabA);
  assert.equal((await m.getState(99)).state, TabState.NOT_ACTIVATED);
});

test("closing a tab removes its activation record", async () => {
  const f = fakeChrome();
  const m = createActivationManager(f.chrome);
  f.granted.add(tabA.id);
  await m.activate(tabA);
  await m.onTabRemoved(tabA.id);
  assert.equal(f.session[STORAGE_KEY][tabA.id], undefined);
  assert.equal((await m.getState(tabA.id)).state, TabState.NOT_ACTIVATED);
});

test("when Chrome revokes the grant (navigation to another site) the tab reports ACCESS_LOST until re-activated", async () => {
  const f = fakeChrome();
  const m = createActivationManager(f.chrome);
  f.granted.add(tabA.id);
  await m.activate(tabA);
  f.granted.delete(tabA.id); // cross-origin navigation
  assert.equal((await m.getState(tabA.id)).state, TabState.ACCESS_LOST);
  const probes = f.injections.length;
  assert.equal((await m.getState(tabA.id)).state, TabState.ACCESS_LOST);
  assert.equal(f.injections.length, probes, "a tab that lost access is not probed again");
  assert.deepEqual(f.session[STORAGE_KEY][tabA.id], { lost: true }, "no origin of the new site is recorded");
  f.granted.add(tabA.id); // user clicks the AURA icon on the new site
  assert.equal((await m.activate({ ...tabA, url: "https://new.example/" })).state, TabState.ACTIVATED);
  assert.equal((await m.getState(tabA.id)).state, TabState.ACTIVATED);
});

test("restricted pages (chrome://) are reported as RESTRICTED, not as missing activation", async () => {
  const f = fakeChrome({ restricted: new Set([33]) });
  const m = createActivationManager(f.chrome);
  const r = await m.activate({ id: 33, windowId: 1, url: undefined });
  assert.equal(r.state, TabState.RESTRICTED);
  assert.equal(f.session[STORAGE_KEY], undefined);
});

test("activation state lives only for the session (fresh manager + empty session storage = not activated)", async () => {
  const f = fakeChrome();
  f.granted.add(tabA.id);
  await createActivationManager(f.chrome).activate(tabA);
  delete f.session[STORAGE_KEY]; // chrome.storage.session is cleared on extension reload
  f.granted.clear(); // and Chrome drops activeTab grants
  assert.equal((await createActivationManager(f.chrome).getState(tabA.id)).state, TabState.NOT_ACTIVATED);
});

test("a panel that is closed does not break activation (sendMessage rejects)", async () => {
  const f = fakeChrome();
  f.chrome.runtime.sendMessage = async () => { throw new Error("Could not establish connection. Receiving end does not exist."); };
  const m = createActivationManager(f.chrome);
  f.granted.add(tabA.id);
  assert.equal((await m.activate(tabA)).state, TabState.ACTIVATED);
});
