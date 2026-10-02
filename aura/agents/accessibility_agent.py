from typing import List
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

    def run_scan(self, page: Page) -> List[AccessibilityViolation]:
        """Runs axe-core WCAG audit on the active browser page."""
        return self.analyzer.analyze(page)

