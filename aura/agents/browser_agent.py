import time
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from aura.config import settings
from aura.browser.browser_manager import BrowserManager
from aura.browser.interaction_policy import InteractionPolicy
from aura.analyzers.dom_analyzer import DOMAnalyzer
from aura.utils.logger import logger


class BrowserAgent:
    """
    Browser Agent managing Playwright browser automation, structured DOM extraction,
    screenshot evidence capture, and hypothesis-driven Level-B controlled interactions.
    """

    def __init__(self, headless: bool = settings.BROWSER_HEADLESS):
        self.browser_manager = BrowserManager(headless=headless)
        self.dom_analyzer = DOMAnalyzer()
        self.interaction_log: List[Dict[str, Any]] = []

    def start(self, viewport: Dict[str, int]):
        """Starts Playwright browser session."""
        self.browser_manager.start(viewport=viewport)

    def navigate(self, url: str) -> Tuple[bool, str, float]:
        """Navigates to URL and measures page load timing."""
        return self.browser_manager.navigate(url)

    def capture_screenshots(self, output_dir: Path) -> Tuple[str, str]:
        """Captures viewport and full-page screenshots."""
        return self.browser_manager.capture_screenshots(output_dir)

    def extract_structured_dom_summary(self) -> Dict[str, Any]:
        """Extracts structured, compact DOM evidence with interactive element details."""
        page = self.browser_manager.page
        if not page:
            return {"title": "", "url": "", "total_elements": 0, "interactive_elements": []}
        return self.dom_analyzer.analyze(page)

    # Visible-content signature: innerText excludes display:none content, so revealing/hiding UI changes it
    # Did the page respond to that? Visible text alone cannot answer it: a dropdown that toggles a class,
    # a panel that gains aria-expanded, a control that becomes disabled - all leave the text identical, so
    # a working control was recorded exactly like a dead one, and the evidence of a dead control carried no
    # information. The signature therefore also covers element count, the attributes that carry interface
    # state, and the address. Focus is deliberately excluded: clicking anything moves focus, so including
    # it would make every control look responsive, which is the same failure in the other direction.
    STATE_SIGNATURE_SCRIPT = """
    () => {
        if (!document.body) return '';
        const text = document.body.innerText || '';
        const stateful = document.querySelectorAll(
            '[aria-expanded],[aria-hidden],[aria-selected],[aria-checked],[open],[disabled],[hidden],' +
            '.active,.open,.show,.selected,.expanded,.visible,.hidden,.disabled');
        let state = '';
        let seen = 0;
        for (const el of stateful) {
            if (seen++ > 200) break;
            state += (el.id || el.tagName) + '='
                  + (el.getAttribute('aria-expanded') || '') + (el.getAttribute('aria-hidden') || '')
                  + (el.getAttribute('aria-selected') || '') + (el.getAttribute('aria-checked') || '')
                  + (el.hasAttribute('open') ? 'o' : '') + (el.hasAttribute('hidden') ? 'h' : '')
                  + (el.disabled ? 'd' : '') + '|' + String(el.className || '').slice(0, 60) + ';';
        }
        return [text.length, document.querySelectorAll('*').length, location.href,
                state.slice(0, 1500), text.slice(0, 1500)].join('~');
    }
    """
    ELEMENT_INFO_SCRIPT = """
    (el) => {
        const ids = []; for (let p = el; p && p.nodeType === 1; p = p.parentElement) { if (p.id) ids.push(p.id); }
        return { tag: el.tagName.toLowerCase(), text: (el.innerText || el.value || '').trim().slice(0, 100),
                 type: el.getAttribute('type'), href: el.getAttribute('href'), role: el.getAttribute('role'),
                 aria_label: el.getAttribute('aria-label'), id: el.id || null, id_chain: ids };
    }
    """
    SKIP_INPUT_TYPES = {"hidden", "password", "file", "checkbox", "radio", "submit", "reset", "button", "image", "range", "color"}

    @classmethod
    def plan_interactions(cls, elements: List[Dict[str, Any]]) -> List[Tuple[float, str, Dict[str, Any]]]:
        """
        Orders candidate actions by expected evidence value (safety is checked separately):
          1   buttons (incl. input type=button)            -> click
          2.0 form text inputs                             -> fill (before submitting)
          2.1 form submit/reset controls                   -> click
          3   navigation controls (nav links, placeholder links, menus/dropdown toggles) -> click
          4   other links                                  -> click
        Generic containers are not hovered: that spends the budget without testing behavior.
        """
        plan = []
        for order, e in enumerate(elements):
            tag = (e.get("tag") or "").lower()
            typ = (e.get("type") or "").lower()
            role = (e.get("role") or "").lower()
            href = (e.get("href") or "").strip().lower()
            cls_name = (e.get("class") or e.get("class_name") or "").lower()
            if not e.get("visible", True) or not e.get("selector"):
                continue
            if tag == "input" and typ in ("submit", "reset"):
                prio, action = 2.1, "click"
            elif tag == "button" and typ in ("submit", "reset"):
                prio, action = 2.1, "click"
            elif tag == "button" or role == "button" or (tag == "input" and typ == "button"):
                prio, action = 1.0, "click"
            elif tag in ("input", "textarea") and typ not in cls.SKIP_INPUT_TYPES:
                prio, action = 2.0, "input"
            elif tag == "a" and (href in ("", "#") or href.startswith("javascript:") or "nav" in [c.lower() for c in (e.get("id_chain") or [])]
                                 or any(k in cls_name for k in ("nav", "menu", "dropdown"))):
                prio, action = 3.0, "click"
            elif tag == "a":
                prio, action = 4.0, "click"
            else:
                continue
            plan.append((prio + order / 100000.0, action, e))
        plan.sort(key=lambda x: x[0])
        return plan

    def _state_signature(self, page) -> str:
        try:
            return page.evaluate(self.STATE_SIGNATURE_SCRIPT)
        except Exception:
            return ""

    def _perform(self, page, action: str, selector: str, info: Dict[str, Any], hypothesis: str,
                 origin_url: str, trigger: str) -> Dict[str, Any]:
        """Executes one policy-approved action and records target-specific outcome evidence."""
        collector = self.collector
        errors_before = len(collector.console_errors)
        net_before = len(collector.network_failures)
        sig_before = self._state_signature(page)
        entry = {
            "hypothesis": hypothesis, "action": action, "target": selector, "element_selector": selector,
            "element_id_chain": info.get("id_chain") or [], "target_text": info.get("text") or "",
            "trigger": trigger, "status": "executed", "reason": "Safe interaction permitted under AURA Level-B Safety Policy.",
            "before_state": f"URL: {page.url}", "after_state": None, "timestamp": time.strftime("%H:%M:%S"),
        }
        try:
            if action == "click":
                page.click(selector, timeout=2500)
            elif action == "input":
                page.fill(selector, "test_input", timeout=1500)
            elif action == "hover":
                page.hover(selector, timeout=1500)
            page.wait_for_timeout(500)
        except Exception as e:
            entry.update(status="failed", reason=f"Runtime execution exception: {str(e)[:200]}", after_state="Action execution failed.")
            return entry

        navigated = page.url.split("#")[0] != origin_url.split("#")[0]
        new_errors = [c.text for c in collector.console_errors[errors_before:] if c.type in ("error", "exception")]
        entry["url_changed"] = navigated
        entry["after_state"] = f"URL: {page.url}"
        if navigated:
            # Errors after a navigation belong to the loaded page, not to this control. Restore the audited
            # page and drop telemetry produced by the navigation/restore (other pages, reload duplicates).
            entry["errors_after_navigation"] = new_errors[:3]
            entry["dom_changed"] = True
            try:
                page.goto(origin_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(1000)
            except Exception as e:
                logger.warning(f"Could not restore audited page after navigation: {e}")
            del collector.console_errors[errors_before:]
            del collector.network_failures[net_before:]
            entry["after_state"] += " | navigated away; audited page restored"
        else:
            for c in collector.console_errors[errors_before:]:
                c.triggered_by = selector  # attribute errors to the control that raised them
            entry["errors_after_action"] = new_errors[:3]
            entry["dom_changed"] = self._state_signature(page) != sig_before
        return entry

    def execute_controlled_interactions(self, max_interactions: int = settings.MAX_INTERACTIONS_PER_AUDIT) -> List[Dict[str, Any]]:
        """
        Performs prioritized Level-B interactions (see plan_interactions). Every action is checked by
        InteractionPolicy; blocked actions are logged and do not consume the budget.
        """
        page = self.browser_manager.page
        if not page:
            return []

        self.interaction_log = []
        origin_url = page.url or ""
        dom_summary = self.extract_structured_dom_summary()
        executed = 0

        for _, action, item in self.plan_interactions(dom_summary.get("all_elements") or []):
            if executed >= max_interactions:
                break
            selector = item["selector"]
            text = item.get("text", "")
            is_safe, reason = InteractionPolicy.is_action_safe(action, item, current_url=origin_url)
            hypothesis = (f"Testing whether '{text or selector}' produces a visible, error-free result when {action}ed."
                          if action != "input" else f"Testing whether field '{selector}' accepts non-destructive input.")
            if not is_safe:
                logger.info(f"Interaction Policy BLOCKED action on '{selector}': {reason}")
                self.interaction_log.append({
                    "hypothesis": hypothesis, "action": action, "target": selector, "element_selector": selector,
                    "element_id_chain": item.get("id_chain") or [], "target_text": text, "trigger": "planned",
                    "status": "blocked", "reason": reason, "before_state": f"URL: {origin_url}", "after_state": None,
                    "timestamp": time.strftime("%H:%M:%S"),
                })
                continue
            entry = self._perform(page, action, selector, item, hypothesis, origin_url, trigger="planned")
            self.interaction_log.append(entry)
            if entry["status"] == "executed":
                executed += 1
                logger.info(f"Interaction Policy EXECUTED safe action '{action}' on '{selector}'")

        return self.interaction_log

    INTERACTIVE_DESCENDANT = "button, a, input[type=submit], input[type=button], input[type=reset], [role=button]"

    def execute_targeted_interactions(self, target_selectors: List[str], interaction_log: List[Dict[str, Any]],
                                      max_interactions: int = settings.MAX_TARGETED_INTERACTIONS) -> List[Dict[str, Any]]:
        """
        Exercises controls referenced by AI candidates that the planned pass did not reach, so the verifier
        can judge interaction claims on target-specific evidence. Same safety policy; appends to the log.
        """
        page = self.browser_manager.page
        if not page:
            return []
        origin_url = page.url or ""
        exercised = {e.get("element_selector") for e in interaction_log if e.get("status") in ("executed", "blocked")}
        added: List[Dict[str, Any]] = []
        for selector in dict.fromkeys(s for s in target_selectors if s):
            if len([a for a in added if a["status"] == "executed"]) >= max_interactions:
                break
            try:
                handle = page.query_selector(selector)
                if handle is None:
                    continue
                info = handle.evaluate(self.ELEMENT_INFO_SCRIPT)
                if info["tag"] not in ("button", "a", "input") and info.get("role") != "button":
                    # Candidate points at a container: exercise its first interactive control
                    inner = handle.query_selector(self.INTERACTIVE_DESCENDANT)
                    if inner is None:
                        continue
                    info = inner.evaluate(self.ELEMENT_INFO_SCRIPT)
                    selector = inner.evaluate("(el) => { const p=[]; for (let n=el; n && n.nodeType===1 && n!==document.documentElement; n=n.parentElement) { if (n.id) { p.unshift('#' + CSS.escape(n.id)); return p.join(' > '); } let s=n.tagName.toLowerCase(); const par=n.parentElement; if (par) { const same=Array.from(par.children).filter(c=>c.tagName===n.tagName); if (same.length>1) s+=':nth-of-type('+(same.indexOf(n)+1)+')'; } p.unshift(s);} return p.join(' > '); }")
            except Exception:
                continue
            if selector in exercised:
                continue
            exercised.add(selector)
            is_safe, reason = InteractionPolicy.is_action_safe("click", {**info, "selector": selector}, current_url=origin_url)
            hypothesis = f"Verifying AI-referenced control '{info.get('text') or selector}' on click."
            if not is_safe:
                added.append({"hypothesis": hypothesis, "action": "click", "target": selector, "element_selector": selector,
                              "element_id_chain": info.get("id_chain") or [], "target_text": info.get("text") or "",
                              "trigger": "candidate_reference", "status": "blocked", "reason": reason,
                              "before_state": f"URL: {origin_url}", "after_state": None, "timestamp": time.strftime("%H:%M:%S")})
                continue
            added.append(self._perform(page, "click", selector, info, hypothesis, origin_url, trigger="candidate_reference"))
        interaction_log.extend(added)
        return added

    TARGET_RESOLUTION_SCRIPT = """
    (queries) => {
        const MAX_ELEMENTS = 10;
        const norm = (t) => (t || '').replace(/\\s+/g, ' ').trim();
        const idChain = (n) => { const ids = []; for (let p = n; p && p.nodeType === 1; p = p.parentElement) { if (p.id) ids.push(p.id); } return ids; };
        const describe = (n) => ({ tag: n.tagName.toLowerCase(), id: n.id || null, id_chain: idChain(n) });
        return queries.map((q) => {
            let nodes = [];
            let method = 'unresolved';
            if (q.selector) {
                try {
                    nodes = Array.from(document.querySelectorAll(q.selector));
                    method = nodes.length === 1 ? 'selector_unique' : (nodes.length > 1 ? 'selector_ambiguous' : 'selector_no_match');
                } catch (e) {
                    method = 'selector_invalid';
                }
            }
            // Fall back to the element whose own visible text exactly equals the reported text,
            // accepted only when exactly one innermost element carries that text.
            const text = norm(q.text);
            if (nodes.length !== 1 && text.length >= 3) {
                const withText = Array.from(document.body.querySelectorAll('*')).filter(
                    (n) => !['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT'].includes(n.tagName) && norm(n.innerText || n.value) === text);
                const innermost = withText.filter((n) => !withText.some((m) => m !== n && n.contains(m)));
                if (innermost.length === 1) { nodes = innermost; method = 'visible_text_unique'; }
            }
            return { method: method, match_count: nodes.length, elements: nodes.slice(0, MAX_ELEMENTS).map(describe) };
        });
    }
    """

    DOCUMENT_LEVEL_TARGETS = {"", "window", "document", "body", "html", "element", "document element", "window / network"}

    def resolve_finding_targets(self, findings: List[Any]) -> None:
        """
        Resolves each finding's reported target to concrete DOM elements (with their ancestor id chain)
        and stores it on finding.resolved_target. This is target identity evidence only: it never
        consults ground truth and does not change the finding.
        """
        page = self.browser_manager.page
        if not page or not findings:
            return

        queries, owners = [], []
        for f in findings:
            selector = (f.raw_target or (f.affected_element.selector if f.affected_element else "") or "").strip()
            if selector.lower() in self.DOCUMENT_LEVEL_TARGETS or selector.startswith(("http://", "https://", "/")):
                continue
            text = (f.affected_element.text if f.affected_element and f.affected_element.text else "") or ""
            queries.append({"selector": selector, "text": text[:200]})
            owners.append(f)

        if not queries:
            return
        try:
            results = page.evaluate(self.TARGET_RESOLUTION_SCRIPT, queries)
        except Exception as e:
            logger.warning(f"Target resolution failed: {e}")
            return
        for f, res in zip(owners, results):
            f.resolved_target = res

    @property
    def collector(self):
        return self.browser_manager.collector

    def stop(self):
        """Stops browser manager session."""
        self.browser_manager.stop()
