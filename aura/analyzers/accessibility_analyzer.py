from typing import TYPE_CHECKING
import urllib.request
from pathlib import Path
from typing import List, Dict, Any
# Playwright is imported lazily so the API can run without it. The extension collects its own
# evidence in the browser, so the hosted API never drives Playwright and its image needs no
# browser binaries; the Streamlit app and the Test Lab still use it locally.
if TYPE_CHECKING:  # pragma: no cover - typing only
    from playwright.sync_api import Page
from aura.models.findings import AccessibilityViolation
from aura.utils.logger import logger

AXE_VERSION = "4.8.2"
AXE_CDN_URL = f"https://cdnjs.cloudflare.com/ajax/libs/axe-core/{AXE_VERSION}/axe.min.js"
# Vendored copy of the same axe-core release; the Chrome extension bundles an identical file (MV3 forbids
# remotely hosted code), so both collectors run the same axe version.
AXE_LOCAL_PATH = Path(__file__).resolve().parent.parent / "vendor" / "axe.min.js"

RULE_WHY_IT_MATTERS = {
    "image-alt": "Screen reader users cannot understand the meaning or context of images without alternative text.",
    "label": "Form controls without labels cannot be identified by assistive technologies, making forms impossible to complete.",
    "link-name": "Screen readers read link names out of context; unlabelled links leave users unaware of navigation destinations.",
    "button-name": "Screen readers announce buttons by their accessible name; unlabelled buttons confuse users about action outcomes.",
    "color-contrast": "Low color contrast makes content difficult or impossible to read for users with vision impairments or under bright light.",
    "document-title": "Page titles provide primary context for users switching browser tabs or using screen readers.",
    "html-has-lang": "Screen readers use language attributes to choose appropriate voice pronunciation and speech synthesis."
}

HEURISTIC_A11Y_SCRIPT = """
() => {
    const violations = [];
    
    document.querySelectorAll('img').forEach((img, idx) => {
        if (!img.hasAttribute('alt')) {
            violations.push({
                id: 'image-alt',
                impact: 'critical',
                description: 'Images must have alt text',
                helpUrl: 'https://dequeuniversity.com/rules/axe/4.8/image-alt',
                nodes: [{ target: [`img:nth-of-type(${idx + 1})`] }]
            });
        }
    });
    
    document.querySelectorAll('input, select, textarea').forEach((input) => {
        const id = input.id;
        const hasLabel = id ? document.querySelector(`label[for="${id}"]`) : input.closest('label');
        const ariaLabel = input.getAttribute('aria-label') || input.getAttribute('aria-labelledby');
        if (!hasLabel && !ariaLabel && input.type !== 'submit' && input.type !== 'hidden') {
            violations.push({
                id: 'label',
                impact: 'critical',
                description: 'Form elements must have labels',
                helpUrl: 'https://dequeuniversity.com/rules/axe/4.8/label',
                nodes: [{ target: [id ? `#${id}` : input.tagName.toLowerCase()] }]
            });
        }
    });

    document.querySelectorAll('a').forEach((a, idx) => {
        const text = (a.innerText || a.getAttribute('aria-label') || '').trim();
        if (!text) {
            violations.push({
                id: 'link-name',
                impact: 'serious',
                description: 'Links must have discernible text',
                helpUrl: 'https://dequeuniversity.com/rules/axe/4.8/link-name',
                nodes: [{ target: [a.id ? `#${a.id}` : `a:nth-of-type(${idx + 1})`] }]
            });
        }
    });

    document.querySelectorAll('button').forEach((btn, idx) => {
        const text = (btn.innerText || btn.getAttribute('aria-label') || '').trim();
        if (!text) {
            violations.push({
                id: 'button-name',
                impact: 'critical',
                description: 'Buttons must have discernible text',
                helpUrl: 'https://dequeuniversity.com/rules/axe/4.8/button-name',
                nodes: [{ target: [btn.id ? `#${btn.id}` : `button:nth-of-type(${idx + 1})`] }]
            });
        }
    });

    return { violations };
}
"""


class AccessibilityAnalyzer:
    """Runs axe-core accessibility auditing on Playwright page context."""

    def __init__(self):
        self._axe_script_content: str = ""

    def _load_axe_script(self) -> str:
        if self._axe_script_content:
            return self._axe_script_content

        try:
            if AXE_LOCAL_PATH.exists():
                self._axe_script_content = AXE_LOCAL_PATH.read_text(encoding="utf-8")
                return self._axe_script_content
        except OSError as e:
            logger.warning(f"Could not read vendored axe-core ({e}); trying CDN.")

        try:
            req = urllib.request.Request(AXE_CDN_URL, headers={"User-Agent": "AURA-Agent/1.0"})
            with urllib.request.urlopen(req, timeout=5) as response:
                self._axe_script_content = response.read().decode("utf-8")
                return self._axe_script_content
        except Exception as e:
            logger.warning(f"Could not load axe-core from CDN ({e}), using built-in heuristic scanner fallback.")
            return ""

    @staticmethod
    def convert_raw_violations(raw_violations: List[Dict[str, Any]]) -> List[AccessibilityViolation]:
        """axe-core `violations` (from any collector) -> AccessibilityViolation models."""
        violations: List[AccessibilityViolation] = []
        for v in raw_violations or []:
            target_selectors = []
            for node in v.get("nodes", []):
                target_selectors.extend(node.get("target", []))

            rule_id = v.get("id", "unknown-rule")
            why_it_matters = RULE_WHY_IT_MATTERS.get(
                rule_id,
                "Users of assistive technology may be unable to perceive or interact with this element."
            )

            violations.append(
                AccessibilityViolation(
                    rule=rule_id,
                    impact=v.get("impact") or "moderate",
                    description=v.get("description", "Accessibility violation detected"),
                    target=target_selectors,
                    help_url=v.get("helpUrl"),
                    why_it_matters=why_it_matters
                )
            )
        return violations

    def analyze(self, page: "Page") -> List[AccessibilityViolation]:
        violations: List[AccessibilityViolation] = []
        axe_js = self._load_axe_script()

        try:
            if axe_js:
                page.evaluate(axe_js)
                raw_results = page.evaluate("() => axe.run()")
                raw_violations = raw_results.get("violations", [])
            else:
                raw_results = page.evaluate(HEURISTIC_A11Y_SCRIPT)
                raw_violations = raw_results.get("violations", [])

            violations.extend(self.convert_raw_violations(raw_violations))
        except Exception as e:
            logger.error(f"Accessibility scan failed: {e}")
            try:
                raw_results = page.evaluate(HEURISTIC_A11Y_SCRIPT)
                for v in raw_results.get("violations", []):
                    rule_id = v.get("id", "unknown")
                    violations.append(
                        AccessibilityViolation(
                            rule=rule_id,
                            impact=v.get("impact", "moderate"),
                            description=v.get("description", ""),
                            target=[n.get("target", ["target"])[0] for n in v.get("nodes", []) if n.get("target")],
                            why_it_matters=RULE_WHY_IT_MATTERS.get(rule_id, "Assistive technology impact.")
                        )
                    )
            except Exception as ex:
                logger.error(f"Heuristic accessibility fallback failed: {ex}")

        return violations
