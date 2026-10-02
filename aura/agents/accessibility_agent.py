from typing import TYPE_CHECKING
from typing import List
# Playwright is imported lazily so the API can run without it. The extension collects its own
# evidence in the browser, so the hosted API never drives Playwright and its image needs no
# browser binaries; the Streamlit app and the Test Lab still use it locally.
if TYPE_CHECKING:  # pragma: no cover - typing only
    from playwright.sync_api import Page
from aura.analyzers.accessibility_analyzer import AccessibilityAnalyzer
from aura.models.findings import AccessibilityViolation


class AccessibilityAgent:
    """
    Accessibility Agent wrapping deterministic axe-core scanning.
    Identifies W3C WCAG accessibility violations without LLM hallucination.
    """

    def __init__(self):
        self.analyzer = AccessibilityAnalyzer()

    def run_scan(self, page: "Page") -> List[AccessibilityViolation]:
        """Runs axe-core WCAG audit on the active browser page."""
        return self.analyzer.analyze(page)

