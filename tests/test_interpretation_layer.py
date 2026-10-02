"""
Unit Tests for Phase 4: AURA Finding Interpretation Layer.

Verifies:
1. Human-understandable titles for key axe-core and AI rules (region, link-name, image-alt, color-contrast, aria-prohibited-attr, landmark-one-main, ambiguous_label)
2. Specific "What's wrong" summaries without generic text
3. Consequence ("Why it matters") statements with careful phrasing
4. Actionable recommendations
5. Descriptive human "Where" locations without raw CSS selectors
6. Status mapping (CONFIRMED -> Confirmed problem, LIKELY -> Potential problem, UNCERTAIN -> Advisory/Needs review)
7. Weak AI hypotheses are never promoted to Confirmed problem
8. Repetitive findings presentation grouping (preserving all raw IDs)
9. Sensible fallback for unknown/unmapped rules (never crashes)
10. Preview is fully removed from the interpretation layer
11. Full preservation of raw technical details
"""
import pytest
from aura.interpretation import (
    interpret_finding,
    group_findings_for_presentation,
    describe_location,
    map_human_status,
    map_confidence_label,
)
from aura.findings.models import (
    AURAFinding, FindingCategory, FindingSeverity, FindingSource,
    FindingVerificationStatus, FindingEvidence, AffectedElement
)


def _make_finding(
    rule: str,
    title: str = "Raw Detector Title",
    category: FindingCategory = FindingCategory.ACCESSIBILITY,
    source: FindingSource = FindingSource.AXE,
    verification_status: FindingVerificationStatus = FindingVerificationStatus.CONFIRMED,
    selector: str = "button.btn-primary",
    text: str = "",
    role: str = "",
    confidence: float = 0.90
) -> AURAFinding:
    return AURAFinding(
        id="F-TEST-001",
        title=title,
        description="Raw technical description from detector.",
        observation="Raw observation.",
        category=category,
        severity=FindingSeverity.HIGH,
        source=source,
        sources=[source.value if hasattr(source, "value") else str(source)],
        canonical_target=selector,
        verification_status=verification_status,
        confidence=confidence,
        raw_rule=rule,
        normalized_rule=rule,
        affected_element=AffectedElement(
            selector=selector,
            text=text,
            role=role,
            tag="button" if "button" in selector else "div",
            target_list=[selector]
        ),
        evidence=FindingEvidence(flags={"dom": True}, sources=["axe-core scan"])
    )


def test_01_region_interpretation():
    """TEST 1: 'region' rule maps to natural language title, consequence, and actionable fix."""
    f = _make_finding("region", title="Ensures all page content is contained by landmarks")
    interp = interpret_finding(f)
    assert interp["title"] == "Some content isn't assigned to a page section"
    assert "not assigned to a page section" in interp["summary"]
    assert "jumping straight to that content" in interp["why_it_matters"]
    assert "Assign the content to a clear page section" in interp["recommendation"]
    assert interp["technical"]["rule_id"] == "region"


def test_02_link_name_interpretation():
    """TEST 2: 'link-name' rule maps to clear language without generic accessibility jargon."""
    f = _make_finding("link-name", title="Elements must have discernible text")
    interp = interpret_finding(f)
    assert interp["title"] == "Some links don't have clear names"
    assert "tell users where they lead" in interp["summary"]
    assert "People using screen readers may hear an unlabelled link" in interp["why_it_matters"]
    assert "Give each link a clear name" in interp["recommendation"]
    assert interp["technical"]["rule_id"] == "link-name"


def test_03_image_alt_interpretation():
    """TEST 3: 'image-alt' rule maps to human-readable explanation and fix."""
    f = _make_finding("image-alt", title="Images must have alternate text")
    interp = interpret_finding(f)
    assert interp["title"] == "Some images are missing descriptions"
    assert "lack text descriptions" in interp["summary"]
    assert "Add a short description to meaningful images" in interp["recommendation"]
    assert interp["technical"]["rule_id"] == "image-alt"


def test_04_color_contrast_interpretation():
    """TEST 4: 'color-contrast' rule maps to readable contrast explanation."""
    f = _make_finding("color-contrast", title="Elements must have sufficient color contrast")
    interp = interpret_finding(f)
    assert interp["title"] == "Text is difficult to read against its background"
    assert "too low to read comfortably" in interp["summary"]
    assert "low vision" in interp["why_it_matters"]
    assert "bright light" in interp["why_it_matters"]
    assert "Darken the text or lighten the background" in interp["recommendation"]
    assert interp["technical"]["rule_id"] == "color-contrast"


def test_05_aria_prohibited_attr_interpretation():
    """TEST 5: 'aria-prohibited-attr' rule maps to clear setting vs role explanation."""
    f = _make_finding("aria-prohibited-attr", title="ARIA attributes must not be prohibited")
    interp = interpret_finding(f)
    assert interp["title"] == "This element uses an accessibility setting that doesn't match its purpose"
    assert "isn't supported for this type of content" in interp["summary"]
    assert "confusing information" in interp["why_it_matters"]
    assert "Remove the unsupported accessibility setting" in interp["recommendation"]
    assert interp["technical"]["rule_id"] == "aria-prohibited-attr"





def test_06_landmark_one_main_interpretation():
    """TEST 6: 'landmark-one-main' rule explains missing main content area."""
    f = _make_finding("landmark-one-main", title="Page must have one main landmark")
    interp = interpret_finding(f)
    assert interp["title"] == "The page does not have a clear primary content area"
    assert "clearly defined area containing the page's main content" in interp["summary"]
    assert "move directly to the main part" in interp["why_it_matters"]
    assert "Define one clear primary content area" in interp["recommendation"]
    assert interp["technical"]["rule_id"] == "landmark-one-main"



def test_07_ambiguous_label_interpretation():
    """TEST 7: 'ambiguous_label' AI rule explains action label uncertainty."""
    f = _make_finding(
        "ambiguous_label",
        title="Label doesn't say what it does",
        category=FindingCategory.UX,
        source=FindingSource.AI,
        verification_status=FindingVerificationStatus.LIKELY,
        confidence=0.75
    )
    interp = interpret_finding(f)
    # The model's own wording is about THIS page, so it is preferred over the rule's generic template.
    # The template remains the fallback when the model's text is missing or carries jargon.
    assert interp["title"] == "Label doesn't say what it does"
    assert interp["status"] == "Potential problem"
    assert interp["confidence_label"] == "Medium"

    jargony = _make_finding(
        "ambiguous_label",
        title="aria-label on the control is non-descriptive per WCAG",
        category=FindingCategory.UX,
        source=FindingSource.AI,
        verification_status=FindingVerificationStatus.LIKELY,
    )
    fallback = interpret_finding(jargony)
    assert fallback["title"] == "This action label may be unclear"
    # Title and summary are judged independently: the jargon-free description still wins for the summary.
    assert fallback["summary"].startswith("Raw technical description from detector.")


def test_08_weak_ai_hypothesis_never_confirmed():
    """TEST 8: Weak AI design hypotheses are never marked 'Confirmed problem'."""
    # AI candidate with LIKELY verification
    f_likely = _make_finding(
        "weak_primary_cta",
        title="Primary button lacks emphasis",
        category=FindingCategory.UI,
        source=FindingSource.AI,
        verification_status=FindingVerificationStatus.LIKELY,
        confidence=0.70
    )
    interp_likely = interpret_finding(f_likely)
    assert interp_likely["status"] == "Potential problem"
    assert interp_likely["status"] != "Confirmed problem"

    # AI candidate with UNCERTAIN verification
    f_uncertain = _make_finding(
        "bad_visual_hierarchy",
        title="Visual emphasis is inverted",
        category=FindingCategory.UI,
        source=FindingSource.AI,
        verification_status=FindingVerificationStatus.UNCERTAIN,
        confidence=0.50
    )
    interp_uncertain = interpret_finding(f_uncertain)
    assert interp_uncertain["status"] == "Advisory"
    assert interp_uncertain["status"] != "Confirmed problem"


def test_09_repeated_identical_violations_grouped():
    """TEST 9: 49 repeated identical violations are grouped into a single primary finding with count."""
    findings = []
    for i in range(1, 50):
        f = _make_finding(
            "region",
            title=f"region violation {i}",
            selector=f"#content > div.section-{i}",
            verification_status=FindingVerificationStatus.CONFIRMED
        )
        interp = interpret_finding(f)
        findings.append(interp)

    grouped = group_findings_for_presentation(findings)
    assert len(grouped) == 1
    parent = grouped[0]
    assert parent["affected_count"] == 49
    assert len(parent["affected_elements"]) == 49
    assert "49 elements across the page" in parent["location_description"]
    # Technical details preserve all underlying findings
    assert len(parent["technical_details"]["all_finding_ids"]) == 49
    assert len(parent["technical_details"]["all_selectors"]) == 49


def test_10_unknown_unmapped_rule_fallback():
    """TEST 10: Unknown / bespoke rules fall back gracefully without crashing."""
    f = _make_finding(
        "custom_novel_detector_rule_xyz",
        title="Custom detector finding",
        category=FindingCategory.CONTENT
    )
    interp = interpret_finding(f)
    assert interp["title"] == "Custom detector finding"
    # The generic "AURA identified an issue on this element" filler is gone. An unmapped rule keeps the
    # detector's own wording and is marked GENERIC so the view layer holds it back from the findings list.
    assert interp["summary"] == "Raw technical description from detector."
    assert "AURA identified an issue" not in interp["summary"]
    assert interp["explanation_specificity"] == "GENERIC"
    assert interp["status"] == "Confirmed problem"
    assert interp["confidence_label"] == "High"


def test_11_preview_is_completely_removed():
    """TEST 11: Preview Fix is gone. No interpretation output may carry preview metadata."""
    import aura.interpretation.interpreter as interp_mod
    import aura.interpretation as interp_pkg

    assert not hasattr(interp_mod, "evaluate_preview_capability")
    assert not hasattr(interp_pkg, "evaluate_preview_capability")

    f = _make_finding("color-contrast", title="Elements must have sufficient color contrast")
    out = interpret_finding(f)
    for container in (out, out["human"], out["technical"]):
        assert not any("preview" in str(k).lower() for k in container.keys()), container.keys()

    # The interpretation tables no longer carry a preview strategy element.
    for table in (interp_mod.AXE_INTERPRETATIONS, interp_mod.AI_INTERPRETATIONS, interp_mod.RUNTIME_INTERPRETATIONS):
        for rule, entry in table.items():
            assert len(entry) == 4, f"{rule} still has a preview strategy element"


def test_12_location_description_never_raw_selector():
    """TEST 12: Location description derives human-friendly text and never displays raw CSS selector."""
    # Complex selector with visible text
    loc1 = describe_location(
        selector="#buttons > ytd-button-renderer > yt-button-shape > button",
        text="Create",
        role="button",
        bounding_box={"y": 40}
    )
    assert "Create" in loc1
    assert "button" in loc1.lower()
    assert "top navigation" in loc1
    assert "ytd-button-renderer" not in loc1

    # Complex selector for Verified badge
    loc2 = describe_location(
        selector=".ytContentMetadataViewModelIcon.ytIconWrapperHost[aria-label=\"Verified\"]",
        role="img",
        bounding_box={"y": 300}
    )
    assert "Verified badge" in loc2
    assert "ytIconWrapperHost" not in loc2

    # Unidentifiable selector fallback
    loc3 = describe_location(selector="div.c-129481 > div:nth-child(2)")
    assert loc3 == "One element on this page (the exact location is in Technical details)"
    assert "nth-child" not in loc3


def test_13_technical_details_full_preservation():
    """TEST 13: All raw technical evidence is strictly preserved under technical_details."""
    f = _make_finding(
        "color-contrast",
        title="Elements must have sufficient color contrast",
        verification_status=FindingVerificationStatus.CONFIRMED,
        confidence=0.95
    )
    interp = interpret_finding(f)
    tech = interp["technical_details"]
    assert tech["rule_id"] == "color-contrast"
    assert tech["verification_status"] == "CONFIRMED"
    assert tech["confidence_score"] == 0.95
    assert "axe-core scan" in tech["evidence_sources"]
    assert tech["evidence_flags"].get("dom") is True
