from pathlib import Path
from typing import Dict, Any, List
from playwright.sync_api import Page
from aura.models.findings import ElementMetadata


class DOMAnalyzer:
    """Extracts compact structured DOM metadata, computed styles, and layout overflow indicators."""

    # Canonical extraction script, shared with the Chrome extension (see js/dom_extraction.js)
    DOM_EXTRACTION_SCRIPT = (Path(__file__).resolve().parent / "js" / "dom_extraction.js").read_text(encoding="utf-8")

    def analyze(self, page: Page) -> Dict[str, Any]:
        """Analyzes DOM structure, layout geometry, and groups elements by category."""
        try:
            raw_res = page.evaluate(self.DOM_EXTRACTION_SCRIPT)
        except Exception:
            raw_res = {}
        return self.summarize(raw_res)

    def summarize(self, raw_res: Dict[str, Any]) -> Dict[str, Any]:
        """
        Builds the dom_summary from a raw extraction result (the script's return value). Used for both the
        Playwright page and evidence collected in the user's browser by the extension.
        """
        try:
            raw_elements = raw_res.get("elements", [])
            doc_scroll_width = raw_res.get("doc_scroll_width", 0)
            doc_client_width = raw_res.get("doc_client_width", 0)
            has_horizontal_overflow = raw_res.get("has_horizontal_overflow", False)
        except Exception:
            raw_elements = []
            doc_scroll_width = 0
            doc_client_width = 0
            has_horizontal_overflow = False

        elements: List[ElementMetadata] = []
        for raw in raw_elements:
            try:
                # Clean computed_style before Pydantic parsing if needed
                raw_clean = {k: v for k, v in raw.items() if k != "computed_style"}
                elements.append(ElementMetadata(**raw_clean))
            except Exception:
                continue

        buttons = [e.model_dump(by_alias=True) for e in elements if e.tag in ("button", "input") and e.type in (None, "button", "submit", "reset") or e.role == "button"]
        links = [e.model_dump(by_alias=True) for e in elements if e.tag == "a" or e.role == "link"]
        inputs = [e.model_dump(by_alias=True) for e in elements if e.tag in ("input", "select", "textarea") and e.type not in ("button", "submit", "reset")]
        forms = [e.model_dump(by_alias=True) for e in elements if e.tag == "form"]
        headings = [e.model_dump(by_alias=True) for e in elements if e.tag in ("h1", "h2", "h3", "h4", "h5", "h6")]
        images = [e.model_dump(by_alias=True) for e in elements if e.tag == "img"]
        navs = [e.model_dump(by_alias=True) for e in elements if e.tag == "nav" or e.role == "navigation"]
        labels = [e.model_dump(by_alias=True) for e in elements if e.tag == "label"]
        status_markers = ("error", "alert", "warning", "banner", "notice", "toast", "status")
        status_messages = [
            e.model_dump(by_alias=True) for e in elements
            if e.role in ("alert", "status") or any(m in (e.class_name or "").lower() for m in status_markers)
        ]

        return {
            "total_elements": len(elements),
            "doc_scroll_width": doc_scroll_width,
            "doc_client_width": doc_client_width,
            "has_horizontal_overflow": has_horizontal_overflow,
            "buttons": buttons,
            "links": links,
            "inputs": inputs,
            "forms": forms,
            "headings": headings,
            "images": images,
            "nav_elements": navs,
            "labels": labels,
            "status_messages": status_messages,
            "all_elements": [e.model_dump(by_alias=True) for e in elements],
            "raw_elements_with_styles": raw_elements
        }
