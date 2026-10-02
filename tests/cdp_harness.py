"""
Raw Chrome DevTools Protocol harness for testing the AURA extension with REAL toolbar-action semantics.

Chrome exposes `Extensions.loadUnpacked` and `Extensions.triggerAction` to a DevTools client connected over
`--remote-debugging-pipe` when `--enable-unsafe-extension-debugging` is set. `triggerAction` runs the
extension's toolbar action exactly like a user click, including the `activeTab` grant. The extension under
test is loaded UNMODIFIED: no test-only host permissions, so page access really depends on activeTab.

The harness launches Playwright's Chromium binary itself and speaks CDP over the pipe directly. Playwright's
own client is NOT used: it auto-attaches to new service workers and keeps them paused in the default
profile, which would stop the extension's service worker from handling the click at all.
"""
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Dict, Optional


class CDPError(RuntimeError):
    pass


_EXECUTABLE: Optional[str] = None


def chromium_executable() -> str:
    """Playwright's Chromium binary, looked up in a subprocess so no Playwright event loop lingers here."""
    global _EXECUTABLE
    if _EXECUTABLE is None:
        _EXECUTABLE = subprocess.run(
            [sys.executable, "-c", "from playwright.sync_api import sync_playwright\n"
             "with sync_playwright() as p: print(p.chromium.executable_path)"],
            capture_output=True, text=True, check=True).stdout.strip()
    return _EXECUTABLE


# Deterministic name resolution inside the test browser: when the user's own AURA server holds 127.0.0.1:8765,
# the tests run theirs on [::1]:8765 and pair the extension with http://localhost:8765 (a host the manifest
# already allows). Without this rule Chrome may pick 127.0.0.1 and reach the user's server instead.
HOST_RULES = "MAP localhost [::1]"

LAB_PORT = 8996           # Test Lab pages for extension E2E tests
CROSS_ORIGIN_PORT = 8997  # the same pages on another origin ("navigated to another site")
_servers = {}


def serve_test_lab(port: int = LAB_PORT) -> str:
    """Serves the Test Lab pages for extension E2E tests. Multi-threaded (the Test Lab's own server is
    single-threaded, and Chrome's idle preconnect sockets can stall it); uses the Test Lab's own request
    handler, so ground truth is never served. Idempotent per port. Returns the base URL."""
    if port not in _servers:
        import http.server
        from test_lab.launcher import QuietHTTPRequestHandler
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), QuietHTTPRequestHandler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        _servers[port] = server
    return f"http://127.0.0.1:{port}"


def start_cross_origin_lab() -> str:
    return serve_test_lab(CROSS_ORIGIN_PORT)


class ChromeHarness:
    def __init__(self, headless: bool = True):
        self._profile = tempfile.mkdtemp(prefix="aura-cdp-")
        our_read, chrome_write = os.pipe()   # Chrome -> harness
        chrome_read, our_write = os.pipe()   # harness -> Chrome
        args = [chromium_executable(), "--remote-debugging-pipe", "--enable-unsafe-extension-debugging",
                f"--user-data-dir={self._profile}", "--no-first-run", "--no-default-browser-check",
                "--no-sandbox", "--disable-background-timer-throttling", "--disable-features=Translate,HttpsUpgrades,HttpsFirstBalancedModeAutoEnable",
                "--disable-component-extensions-with-background-pages", f"--host-resolver-rules={HOST_RULES}",
                "about:blank"]
        if headless:
            args.insert(1, "--headless")
        if sys.platform == "win32":
            import msvcrt
            h_in, h_out = msvcrt.get_osfhandle(chrome_read), msvcrt.get_osfhandle(chrome_write)
            os.set_handle_inheritable(h_in, True)
            os.set_handle_inheritable(h_out, True)
            args.insert(1, f"--remote-debugging-io-pipes={h_in},{h_out}")
            self._proc = subprocess.Popen(args, close_fds=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            def child_fds():
                os.dup2(chrome_read, 3)
                os.dup2(chrome_write, 4)
            self._proc = subprocess.Popen(args, pass_fds=(chrome_read, chrome_write), preexec_fn=child_fds,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(chrome_read)
        os.close(chrome_write)
        self._rfd, self._wfd = our_read, our_write
        self._ids = itertools.count(1)
        self._replies: Dict[int, Dict[str, Any]] = {}
        self._cond = threading.Condition()
        self._wlock = threading.Lock()
        threading.Thread(target=self._reader, daemon=True).start()
        self.send("Target.setDiscoverTargets", {"discover": True})

    # ------------------------------------------------------------ transport (NUL-separated JSON messages)
    def _reader(self) -> None:
        buf = b""
        while True:
            try:
                chunk = os.read(self._rfd, 1 << 16)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\0" in buf:
                raw, buf = buf.split(b"\0", 1)
                msg = json.loads(raw)
                if "id" in msg:
                    with self._cond:
                        self._replies[msg["id"]] = msg
                        self._cond.notify_all()

    def send(self, method: str, params: Optional[Dict[str, Any]] = None, session: Optional[str] = None,
             timeout: float = 30.0) -> Dict[str, Any]:
        mid = next(self._ids)
        msg: Dict[str, Any] = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        with self._wlock:
            os.write(self._wfd, json.dumps(msg).encode() + b"\0")
        deadline = time.time() + timeout
        with self._cond:
            while mid not in self._replies:
                left = deadline - time.time()
                if left <= 0:
                    raise CDPError(f"{method}: timeout")
                self._cond.wait(left)
            reply = self._replies.pop(mid)
        if "error" in reply:
            raise CDPError(f"{method}: {reply['error'].get('message')}")
        return reply.get("result", {})

    # ------------------------------------------------------------ targets
    def attach(self, target_id: str) -> str:
        session = self.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})["sessionId"]
        # Targets started while a DevTools client is connected can be parked "waiting for debugger";
        # release them (no-op for targets that are already running).
        try:
            self.send("Runtime.runIfWaitingForDebugger", {}, session=session, timeout=5)
        except CDPError:
            pass
        return session

    def evaluate(self, session: str, expression: str, timeout: float = 30.0) -> Any:
        """Evaluates an expression (awaiting promises) in a target and returns its JSON value."""
        r = self.send("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True},
                      session=session, timeout=timeout)
        if r.get("exceptionDetails"):
            raise CDPError(r["exceptionDetails"].get("exception", {}).get("description") or str(r["exceptionDetails"]))
        return r.get("result", {}).get("value")

    def targets(self, type_: Optional[str] = None):
        params = {"filter": [{"type": type_}]} if type_ else {}
        return self.send("Target.getTargets", params)["targetInfos"]

    def wait_target(self, predicate: Callable[[Dict[str, Any]], bool], timeout: float = 15.0) -> Dict[str, Any]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for t in self.targets():
                if predicate(t):
                    return t
            time.sleep(0.1)
        raise CDPError("target not found")

    # ------------------------------------------------------------ extension / tabs
    def load_extension(self, path: str) -> str:
        return self.send("Extensions.loadUnpacked", {"path": path})["id"]

    def service_worker(self, ext_id: str) -> str:
        t = self.wait_target(lambda t: t["type"] == "service_worker" and ext_id in t["url"])
        return self.attach(t["targetId"])

    def extension_page(self, ext_id: str, path: str = "options/options.html", attempts: int = 3) -> str:
        """Opens an extension page in its own window; returns a session once chrome.* APIs are available.
        Right after (re)loading an extension the first navigation can land on an error page: retry."""
        for _ in range(attempts):
            target = self.open_tab(f"chrome-extension://{ext_id}/{path}", new_window=True, wait=False)
            session = self.attach(target)
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    if self.evaluate(session, "typeof chrome !== 'undefined' && !!chrome.storage && !!chrome.tabs", timeout=5):
                        return session
                except CDPError:
                    pass
                time.sleep(0.3)
            self.close_tab(target)
            time.sleep(1.0)
        raise CDPError("extension page did not load")

    def wait_loaded(self, target_id: str, url_prefix: str = "", timeout: float = 20.0) -> None:
        """Waits until the tab has committed `url_prefix` and finished loading. A toolbar click that lands
        before the navigation commits grants activeTab to the previous document (about:blank), and Chrome
        revokes it on commit; a real user clicks on a loaded page."""
        session = self.attach(target_id)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.evaluate(session, f"document.readyState === 'complete' && location.href.startsWith({json.dumps(url_prefix)})", timeout=5):
                    time.sleep(0.2)
                    return
            except CDPError:
                pass
            time.sleep(0.2)
        raise CDPError(f"tab did not finish loading {url_prefix}")

    def open_tab(self, url: str, new_window: bool = False, wait: bool = True) -> str:
        target_id = self.send("Target.createTarget", {"url": url, "newWindow": new_window})["targetId"]
        if wait and url.startswith("http"):
            self.wait_loaded(target_id, url)
        return target_id

    def activate(self, target_id: str) -> None:
        self.send("Target.activateTarget", {"targetId": target_id})

    def close_tab(self, target_id: str) -> None:
        self.send("Target.closeTarget", {"targetId": target_id})

    def navigate(self, target_id: str, url: str) -> None:
        s = self.attach(target_id)
        self.send("Page.navigate", {"url": url}, session=s)
        self.wait_loaded(target_id, url)

    def reload(self, target_id: str) -> None:
        s = self.attach(target_id)
        url = self.evaluate(s, "location.href")
        self.send("Page.reload", {}, session=s)
        time.sleep(0.5)
        self.wait_loaded(target_id, url)

    def tab_target(self, page_target_id: str) -> str:
        """The 'tab' target that owns a page target (Extensions.triggerAction only accepts tab targets)."""
        page = next(t for t in self.targets() if t["targetId"] == page_target_id)
        matches = [t for t in self.targets("tab") if t["url"] == page["url"]]
        if len(matches) != 1:
            raise CDPError(f"cannot uniquely map page target to tab target ({len(matches)} matches)")
        return matches[0]["targetId"]

    def click_toolbar_action(self, ext_id: str, page_target_id: str) -> None:
        """Exactly what a user's click on the AURA toolbar icon does in that tab (grants activeTab).
        A user clicks the toolbar of the focused window, on its active tab: bring that tab to the front first
        (in a headless multi-window browser, captureVisibleTab never settles for a window that is not in front)."""
        self.activate(page_target_id)
        self.send("Extensions.triggerAction", {"id": ext_id, "targetId": self.tab_target(page_target_id)})

    def close(self) -> None:
        try:
            self.send("Browser.close", timeout=5)
        except Exception:
            pass
        try:
            self._proc.wait(timeout=10)
        except Exception:
            self._proc.kill()
        shutil.rmtree(self._profile, ignore_errors=True)


class SidePanel:
    """The REAL AURA side panel (chrome-extension://<id>/sidepanel/index.html), driven through its DOM."""

    def __init__(self, h: ChromeHarness, ext_id: str, timeout: float = 15.0):
        self.h, self.ext_id = h, ext_id
        t = h.wait_target(lambda t: t["type"] == "page" and t["url"].startswith(f"chrome-extension://{ext_id}/sidepanel/"),
                          timeout=timeout)
        self.target_id = t["targetId"]
        self.session = h.attach(self.target_id)
        self.wait("document.readyState === 'complete' && !!document.getElementById('access')")

    def js(self, expr: str) -> Any:
        return self.h.evaluate(self.session, expr)

    def text(self, element_id: str) -> str:
        return self.js(f"document.getElementById({json.dumps(element_id)}).innerText")

    def click(self, selector: str) -> None:
        self.js(f"document.querySelector({json.dumps(selector)}).click()")

    def visible(self, element_id: str) -> bool:
        return bool(self.js(f"!document.getElementById({json.dumps(element_id)}).classList.contains('hidden')"))

    def wait(self, expr: str, timeout: float = 15.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.js(expr):
                    return True
            except CDPError:
                pass
            time.sleep(0.2)
        raise AssertionError(f"timeout waiting for: {expr}")

    def access(self) -> Dict[str, Any]:
        return self.js("({cls: document.getElementById('access').className, text: document.getElementById('access').textContent,"
                       " scanDisabled: document.getElementById('scan').disabled, host: document.getElementById('page-host').textContent})")

    def wait_access(self, cls: str, timeout: float = 15.0) -> Dict[str, Any]:
        self.wait(f"document.getElementById('access').classList.contains('{cls}')", timeout)
        return self.access()

    def scan(self, timeout: float = 180.0) -> None:
        """Clicks Scan current page and waits for results; on failure reports where the scan stopped."""
        self.wait_access("access-ok")
        self.wait("!document.getElementById('scan').disabled", 30)  # enabled only once the tab is scannable
        self.click("#scan")
        done = ("!document.getElementById('results').classList.contains('hidden') || "
                "!document.getElementById('error').classList.contains('hidden')")
        try:
            self.wait(done, timeout)
        except AssertionError:
            steps = self.js("document.getElementById('steps').innerText").replace("\n", " | ")
            raise AssertionError(f"scan did not finish in {timeout}s; progress: {steps}")
        if self.visible("error"):
            raise AssertionError("scan failed: " + self.text("error"))

    def screenshot(self, path: str) -> None:
        import base64
        data = self.h.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True}, session=self.session)["data"]
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(data))

    def close(self) -> None:
        self.h.close_tab(self.target_id)
