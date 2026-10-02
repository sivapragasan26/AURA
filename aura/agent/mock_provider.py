import json
from typing import Optional, Tuple
from aura.agent.provider import AIProvider
from aura.utils.logger import logger


class MockAIProvider(AIProvider):
    """Deterministic Mock AI Provider for offline testing, UI dev, zero-key execution, and Test Lab scenario evaluation.
    Its candidates are scripted per Test Lab suite: it validates the pipeline, not AI capability."""
    provider_key = "mock"

    def analyze(self, prompt: str, screenshot_base64: Optional[str] = None, mime_type: str = "image/png") -> str:
        logger.info("MockAIProvider running evidence-driven candidate finding generator.")

        prompt_lower = prompt.lower()
        issues = []
        issue_counter = 1

        # ----------------------------------------------------
        # V0.4 Consolidated Benchmark Suite 01: Accessibility
        # ----------------------------------------------------
        if "01_accessibility_suite" in prompt_lower or "#a11y-missing-alt" in prompt_lower or "#a11y-button-name" in prompt_lower:
            issues.extend([
                {
                    "id": f"AURA-CAND-01-1",
                    "category": "ACCESSIBILITY",
                    "rule_type": "image-alt",
                    "title": "Images missing descriptive alt text",
                    "description": "Image element #a11y-missing-alt lacks alt attribute for screen readers.",
                    "observation": "Accessibility scan identified image element missing alternative text.",
                    "severity": "MEDIUM",
                    "confidence": 0.98,
                    "target": "#a11y-missing-alt",
                    "affected_element": {"selector": "#a11y-missing-alt", "tag": "img", "text": "Logo"},
                    "evidence": {"type": "accessibility", "description": "axe-core violation rule: image-alt"},
                    "recommendation": "Add alt attributes to all informational images.",
                    "why_it_matters": "Visually impaired users rely on alt text to understand image content.",
                    "claim": "Image element lacks alt text.",
                    "viewport": "1440x900",
                    "evidence_requested": ["accessibility", "dom"],
                    "reasoning": "Element #a11y-missing-alt has no alt attribute.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-01-2",
                    "category": "ACCESSIBILITY",
                    "rule_type": "button-name",
                    "title": "Buttons must have discernible text",
                    "description": "Icon button #a11y-button-name lacks accessible text or aria-label.",
                    "observation": "Unlabelled button element detected in header.",
                    "severity": "HIGH",
                    "confidence": 0.99,
                    "target": "#a11y-button-name",
                    "affected_element": {"selector": "#a11y-button-name", "tag": "button", "text": "🔍"},
                    "evidence": {"type": "accessibility", "description": "axe-core violation rule: button-name"},
                    "recommendation": "Add text content or aria-label to button elements.",
                    "why_it_matters": "Screen reader users cannot determine the function of unlabelled buttons.",
                    "claim": "Button element lacks accessible label.",
                    "viewport": "1440x900",
                    "evidence_requested": ["accessibility", "dom"],
                    "reasoning": "Icon button #a11y-button-name contains no text node or aria-label.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-01-3",
                    "category": "ACCESSIBILITY",
                    "rule_type": "color-contrast",
                    "title": "Low text contrast ratio against background",
                    "description": "Text element #a11y-contrast fails WCAG minimum contrast ratio.",
                    "observation": "Visual contrast inspection identified text with insufficient contrast ratio.",
                    "severity": "MEDIUM",
                    "confidence": 0.95,
                    "target": "#a11y-contrast",
                    "affected_element": {"selector": "#a11y-contrast", "tag": "p", "text": "Please verify"},
                    "evidence": {"type": "accessibility", "description": "axe-core violation rule: color-contrast"},
                    "recommendation": "Increase text color contrast ratio to at least 4.5:1.",
                    "why_it_matters": "Low contrast text causes readability difficulties.",
                    "claim": "Text contrast ratio fails WCAG guidelines.",
                    "viewport": "1440x900",
                    "evidence_requested": ["accessibility", "visual"],
                    "reasoning": "Element #a11y-contrast uses gray text on gray background.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-01-4",
                    "category": "ACCESSIBILITY",
                    "rule_type": "bad_links",
                    "title": "Inaccessible void link",
                    "description": "Anchor link #a11y-bad-link points to javascript:void(0).",
                    "observation": "DOM inspection identified anchor elements with empty href destinations.",
                    "severity": "MEDIUM",
                    "confidence": 0.92,
                    "target": "#a11y-bad-link",
                    "affected_element": {"selector": "#a11y-bad-link", "tag": "a", "text": "Support Portal"},
                    "evidence": {"type": "dom", "description": "href='javascript:void(0)'"},
                    "recommendation": "Use valid routes or button elements for JavaScript triggers.",
                    "why_it_matters": "Void links confuse navigation expectations.",
                    "claim": "Link destination is invalid or void.",
                    "viewport": "1440x900",
                    "evidence_requested": ["dom"],
                    "reasoning": "Element #a11y-bad-link has href='javascript:void(0)'.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-01-5",
                    "category": "ACCESSIBILITY",
                    "rule_type": "landmark-one-main",
                    "title": "Missing main landmark element",
                    "description": "Page structure lacks a <main> landmark container.",
                    "observation": "DOM structure lacks main landmark role.",
                    "severity": "MEDIUM",
                    "confidence": 0.90,
                    "target": "body",
                    "affected_element": {"selector": "body", "tag": "body", "text": "body"},
                    "evidence": {"type": "accessibility", "description": "axe-core rule: landmark-one-main"},
                    "recommendation": "Wrap primary content inside a <main> element.",
                    "why_it_matters": "Landmarks enable screen reader users to jump to main content.",
                    "claim": "Page missing main landmark role.",
                    "viewport": "1440x900",
                    "evidence_requested": ["accessibility", "dom"],
                    "reasoning": "Page body contains no <main> tag.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-01-6",
                    "category": "ACCESSIBILITY",
                    "rule_type": "label",
                    "title": "Missing form input label",
                    "description": "Form input #a11y-missing-label lacks associated label element.",
                    "observation": "Form inspection identified input field missing explicit label.",
                    "severity": "HIGH",
                    "confidence": 0.96,
                    "target": "#a11y-missing-label",
                    "affected_element": {"selector": "#a11y-missing-label", "tag": "input", "text": ""},
                    "evidence": {"type": "accessibility", "description": "axe-core rule: label"},
                    "recommendation": "Provide explicit <label for='...'> or aria-label.",
                    "why_it_matters": "Unlabeled form inputs cannot be properly announced by assistive tools.",
                    "claim": "Input field lacks associated label.",
                    "viewport": "1440x900",
                    "evidence_requested": ["accessibility", "dom"],
                    "reasoning": "Input #a11y-missing-label has placeholder but no label.",
                    "source": "AI",
                    "status": "candidate"
                }
            ])

        # ----------------------------------------------------
        # V0.4 Consolidated Benchmark Suite 02: UI & UX
        # ----------------------------------------------------
        if "02_ui_ux_suite" in prompt_lower or "#ui-visual-hierarchy" in prompt_lower or "#ux-confusing-form" in prompt_lower:
            issues.extend([
                {
                    "id": f"AURA-CAND-02-1",
                    "category": "UI",
                    "rule_type": "bad_visual_hierarchy",
                    "title": "Inverted action visual hierarchy",
                    "description": "Destructive cancel button is giant and high contrast while primary CTA is a tiny obscure link.",
                    "observation": "Visual inspection identified primary CTA hidden behind secondary cancel action.",
                    "severity": "HIGH",
                    "confidence": 0.94,
                    "target": "#ui-visual-hierarchy",
                    "affected_element": {"selector": "#ui-visual-hierarchy", "tag": "div", "text": "Cancel All Pending Orders"},
                    "evidence": {"type": "visual", "description": "Giant red cancel button vs tiny gray link"},
                    "recommendation": "Make primary action prominent and secondary actions subtle.",
                    "why_it_matters": "Inverted hierarchy leads to accidental destructive clicks.",
                    "claim": "Visual hierarchy favors destructive secondary action over primary CTA.",
                    "viewport": "1440x900",
                    "evidence_requested": ["visual", "dom"],
                    "reasoning": "Destructive button is 24px giant red while primary action is 11px gray link.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-02-2",
                    "category": "UX",
                    "rule_type": "confusing_form",
                    "title": "Confusing form layout and button behavior",
                    "description": "Form reset button is styled as a primary green submit button while submit is styled as gray reset.",
                    "observation": "Form usability inspection identified misleading button styling.",
                    "severity": "HIGH",
                    "confidence": 0.95,
                    "target": "#ux-confusing-form",
                    "affected_element": {"selector": "#ux-confusing-form", "tag": "form", "text": "Submit Form"},
                    "evidence": {"type": "dom", "description": "input[type='reset'] styled as green submit"},
                    "recommendation": "Style primary submit button clearly and avoid dangerous reset buttons.",
                    "why_it_matters": "Misleading form buttons cause users to wipe input accidentally.",
                    "claim": "Form buttons present inverted visual feedback causing accidental reset.",
                    "viewport": "1440x900",
                    "evidence_requested": ["dom", "visual"],
                    "reasoning": "Reset button says 'Submit Form' and is colored green.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-02-3",
                    "category": "UI",
                    "rule_type": "poor_information_density",
                    "title": "Poor information density and unreadable log box",
                    "description": "Log container uses 9px font with excessive horizontal repetition.",
                    "observation": "Typography inspection identified unreadable font sizing.",
                    "severity": "MEDIUM",
                    "confidence": 0.88,
                    "target": "#ui-poor-density",
                    "affected_element": {"selector": "#ui-poor-density", "tag": "div", "text": "Log item"},
                    "evidence": {"type": "visual", "description": "9px cramped monospace log scroll view"},
                    "recommendation": "Increase font size to at least 12px and format structured log entries.",
                    "why_it_matters": "Tiny text causes severe cognitive strain.",
                    "claim": "Log box text is illegible due to poor density and font size.",
                    "viewport": "1440x900",
                    "evidence_requested": ["visual"],
                    "reasoning": "Font size is 9px inside cramped log box.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-02-4",
                    "category": "UI",
                    "rule_type": "weak_cta",
                    "title": "Weak primary call-to-action prominence",
                    "description": "Primary action link #ui-weak-cta lacks visual distinction.",
                    "observation": "CTA analysis identified primary approval action obscured as tiny link.",
                    "severity": "HIGH",
                    "confidence": 0.91,
                    "target": "#ui-weak-cta",
                    "affected_element": {"selector": "#ui-weak-cta", "tag": "a", "text": "Submit Final Order Approval"},
                    "evidence": {"type": "visual", "description": "11px link styling"},
                    "recommendation": "Style primary CTA with a high-contrast button container.",
                    "why_it_matters": "Obscured CTAs reduce user conversion and action completion rates.",
                    "claim": "Primary CTA lacks visual prominence.",
                    "viewport": "1440x900",
                    "evidence_requested": ["visual"],
                    "reasoning": "Primary approval CTA rendered as small gray link.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-02-5",
                    "category": "UI",
                    "rule_type": "inconsistent_components",
                    "title": "Inconsistent component styling and typography",
                    "description": "Action buttons mix Comic Sans, Impact, bright yellow, and dashed magenta borders.",
                    "observation": "Design system analysis identified conflicting component styles.",
                    "severity": "MEDIUM",
                    "confidence": 0.86,
                    "target": "#ui-inconsistent-components",
                    "affected_element": {"selector": "#ui-inconsistent-components", "tag": "div", "text": "Legacy Export"},
                    "evidence": {"type": "visual", "description": "Conflicting font families and button border styles"},
                    "recommendation": "Enforce unified design token palette and typography scale.",
                    "why_it_matters": "Inconsistent components erode product trust.",
                    "claim": "Buttons display conflicting font families and styles.",
                    "viewport": "1440x900",
                    "evidence_requested": ["visual"],
                    "reasoning": "Component uses Impact font with yellow on green next to cyan dashed button.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-02-6",
                    "category": "UX",
                    "rule_type": "unclear_error_message",
                    "title": "Unclear system error message UX",
                    "description": "Error banner displays raw hex stack code without human-readable instructions.",
                    "observation": "Error UX inspection identified cryptic status message.",
                    "severity": "HIGH",
                    "confidence": 0.93,
                    "target": "#ux-unclear-error",
                    "affected_element": {"selector": "#ux-unclear-error", "tag": "div", "text": "STATUS 500"},
                    "evidence": {"type": "dom", "description": "Hex error code string"},
                    "recommendation": "Provide clear human-readable explanation and recovery action.",
                    "why_it_matters": "Cryptic errors confuse users and leave them stuck.",
                    "claim": "Error message provides raw technical code without recovery steps.",
                    "viewport": "1440x900",
                    "evidence_requested": ["dom", "visual"],
                    "reasoning": "Banner shows 0x8004005 without explaining how to fix.",
                    "source": "AI",
                    "status": "candidate"
                }
            ])

        # ----------------------------------------------------
        # V0.4 Consolidated Benchmark Suite 03: Navigation & Interaction
        # ----------------------------------------------------
        if "03_navigation_interaction_suite" in prompt_lower or "#nav-bad-links" in prompt_lower or "#interaction-broken-btn" in prompt_lower:
            issues.extend([
                {
                    "id": f"AURA-CAND-03-1",
                    "category": "UX",
                    "rule_type": "bad_navigation",
                    "title": "Overlapping navigation links",
                    "description": "Header navigation links overlap with negative margins.",
                    "observation": "Layout analysis identified overlapping anchor targets.",
                    "severity": "HIGH",
                    "confidence": 0.92,
                    "target": "#nav-bad-links",
                    "affected_element": {"selector": "#nav-bad-links", "tag": "nav", "text": "Dashboard"},
                    "evidence": {"type": "visual", "description": "margin-right: -30px causing link overlap"},
                    "recommendation": "Maintain adequate spacing between navigation items.",
                    "why_it_matters": "Overlapping links prevent precise clicking.",
                    "claim": "Navigation links overlap physically in header.",
                    "viewport": "1440x900",
                    "evidence_requested": ["visual", "dom"],
                    "reasoning": "Negative margin -30px causes Dashboard and Transactions links to overlap.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-03-2",
                    "category": "INTERACTION",
                    "rule_type": "interaction_failure",
                    "title": "Uncaught script exception during button click",
                    "description": "Clicking balance transfer button throws uncaught JavaScript Error.",
                    "observation": "Interaction verification recorded script error event.",
                    "severity": "CRITICAL",
                    "confidence": 0.99,
                    "target": "#interaction-broken-btn",
                    "affected_element": {"selector": "#interaction-broken-btn", "tag": "button", "text": "Execute Balance Transfer"},
                    "evidence": {"type": "runtime", "description": "Uncaught Error: Unable to complete operation"},
                    "recommendation": "Wrap event handlers in exception safeguards.",
                    "why_it_matters": "Script errors block critical workflow execution.",
                    "claim": "Button click throws uncaught exception.",
                    "viewport": "1440x900",
                    "evidence_requested": ["runtime", "interaction"],
                    "reasoning": "Clicking #interaction-broken-btn triggers Uncaught Error.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-03-3",
                    "category": "UX",
                    "rule_type": "broken_menu",
                    "title": "Dropdown menu fails to open",
                    "description": "Settings dropdown menu toggle button does not open sub-menu container.",
                    "observation": "Interaction analysis identified unresponsive dropdown toggle.",
                    "severity": "HIGH",
                    "confidence": 0.90,
                    "target": "#nav-broken-menu",
                    "affected_element": {"selector": "#nav-broken-menu", "tag": "div", "text": "Settings ▾"},
                    "evidence": {"type": "interaction", "description": "Click produces no state change in dropdown-menu"},
                    "recommendation": "Bind click event handler to toggle dropdown visibility.",
                    "why_it_matters": "Broken navigation menus lock users out of settings pages.",
                    "claim": "Dropdown menu does not expand upon click.",
                    "viewport": "1440x900",
                    "evidence_requested": ["interaction", "dom"],
                    "reasoning": "Menu remains display:none after clicking toggle button.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-03-4",
                    "category": "INTERACTION",
                    "rule_type": "dead_button",
                    "title": "Unresponsive primary action button",
                    "description": "Button #interaction-dead-btn produces no visual feedback or event response on click.",
                    "observation": "Interaction logging recorded zero state change on click.",
                    "severity": "MEDIUM",
                    "confidence": 0.88,
                    "target": "#interaction-dead-btn",
                    "affected_element": {"selector": "#interaction-dead-btn", "tag": "button", "text": "Generate Instant Audit Report"},
                    "evidence": {"type": "interaction", "description": "No listener or state change"},
                    "recommendation": "Implement action handler or disable un-implemented buttons.",
                    "why_it_matters": "Dead buttons confuse users expecting task progress.",
                    "claim": "Button activation produces no response.",
                    "viewport": "1440x900",
                    "evidence_requested": ["interaction"],
                    "reasoning": "Clicking #interaction-dead-btn yields no before/after change.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-03-5",
                    "category": "UX",
                    "rule_type": "misleading_cta",
                    "title": "Misleading navigation CTA link destination",
                    "description": "Link labeled 'Download Full Invoice PDF' uses javascript:void(0) without initiating download.",
                    "observation": "CTA route analysis identified misleading action promise.",
                    "severity": "HIGH",
                    "confidence": 0.91,
                    "target": "#nav-misleading-cta",
                    "affected_element": {"selector": "#nav-misleading-cta", "tag": "a", "text": "Download Full Invoice PDF"},
                    "evidence": {"type": "dom", "description": "javascript:void(0) anchor"},
                    "recommendation": "Link directly to file resource or execute file download handler.",
                    "why_it_matters": "Misleading CTAs cause user frustration.",
                    "claim": "Download link fails to initiate file download.",
                    "viewport": "1440x900",
                    "evidence_requested": ["dom"],
                    "reasoning": "Link claims to download PDF but has void href.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-03-6",
                    "category": "INTERACTION",
                    "rule_type": "failed_form_interaction",
                    "title": "Form submission lacks feedback or confirmation",
                    "description": "Submitting ticket form clears text input without showing success message.",
                    "observation": "Form interaction analysis identified missing feedback state.",
                    "severity": "HIGH",
                    "confidence": 0.93,
                    "target": "#interaction-form-failed",
                    "affected_element": {"selector": "#interaction-form-failed", "tag": "div", "text": "Submit Ticket"},
                    "evidence": {"type": "interaction", "description": "Input cleared without feedback message"},
                    "recommendation": "Display visible confirmation message after form submit.",
                    "why_it_matters": "Missing feedback leaves users unsure if action succeeded.",
                    "claim": "Form submission provides no confirmation feedback.",
                    "viewport": "1440x900",
                    "evidence_requested": ["interaction", "dom"],
                    "reasoning": "Feedback element stays empty and hidden post-submit.",
                    "source": "AI",
                    "status": "candidate"
                }
            ])

        # ----------------------------------------------------
        # V0.4 Consolidated Benchmark Suite 04: Responsive & Runtime
        # ----------------------------------------------------
        if "04_responsive_runtime_suite" in prompt_lower or "#responsive-overflow" in prompt_lower or "api/v1/application-status-500" in prompt_lower:
            issues.extend([
                {
                    "id": f"AURA-CAND-04-1",
                    "category": "RESPONSIVENESS",
                    "rule_type": "horizontal_overflow",
                    "title": "Horizontal document scrollbar caused by wide container",
                    "description": "Banner element #responsive-overflow is set to 1800px width causing document overflow.",
                    "observation": "Browser geometry scan measured scrollWidth > clientWidth.",
                    "severity": "HIGH",
                    "confidence": 0.98,
                    "target": "#responsive-overflow",
                    "affected_element": {"selector": "#responsive-overflow", "tag": "div", "text": "Notice: Global Infrastructure"},
                    "evidence": {"type": "responsive", "description": "scrollWidth: 1800px > clientWidth"},
                    "recommendation": "Use max-width: 100% and responsive layout units.",
                    "why_it_matters": "Horizontal overflow breaks mobile and tablet viewports.",
                    "claim": "Document exceeds viewport width causing horizontal scroll.",
                    "viewport": "1440x900",
                    "evidence_requested": ["responsive", "dom"],
                    "reasoning": "#responsive-overflow element width is fixed at 1800px.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-04-2",
                    "category": "RESPONSIVENESS",
                    "rule_type": "mobile_layout_break",
                    "title": "Unresponsive wide data table layout break",
                    "description": "Table element #responsive-mobile-break has fixed 1200px width without scroll container.",
                    "observation": "Responsive analysis identified clipped wide table component.",
                    "severity": "MEDIUM",
                    "confidence": 0.92,
                    "target": "#responsive-mobile-break",
                    "affected_element": {"selector": "#responsive-mobile-break", "tag": "div", "text": "Data Center Metric"},
                    "evidence": {"type": "responsive", "description": "1200px fixed table width"},
                    "recommendation": "Wrap wide tables in overflow-x: auto scroll containers.",
                    "why_it_matters": "Wide tables clip off-screen on smaller viewports.",
                    "claim": "Data table breaks mobile viewport layout.",
                    "viewport": "1440x900",
                    "evidence_requested": ["responsive"],
                    "reasoning": "Table width 1200px exceeds viewport container.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-04-3",
                    "category": "RESPONSIVENESS",
                    "rule_type": "clipped_content",
                    "title": "Clipped container content and hidden button",
                    "description": "Container #responsive-clipped-content uses height:35px with overflow:hidden cutting off content.",
                    "observation": "Geometry analysis detected hidden text and action button.",
                    "severity": "MEDIUM",
                    "confidence": 0.90,
                    "target": "#responsive-clipped-content",
                    "affected_element": {"selector": "#responsive-clipped-content", "tag": "div", "text": "System Status"},
                    "evidence": {"type": "responsive", "description": "overflow:hidden with fixed height:35px"},
                    "recommendation": "Use dynamic min-height or overflow auto.",
                    "why_it_matters": "Clipped elements hide critical text and action controls.",
                    "claim": "Container height clips inner content and controls.",
                    "viewport": "1440x900",
                    "evidence_requested": ["responsive", "dom"],
                    "reasoning": "Height 35px with overflow hidden clips lines of text and button.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-04-4",
                    "category": "RUNTIME",
                    "rule_type": "application_console_error",
                    "title": "Application initialization console error",
                    "description": "Console error event fired during application startup.",
                    "observation": "Telemetry collector captured application console error.",
                    "severity": "HIGH",
                    "confidence": 0.97,
                    "target": "window",
                    "affected_element": {"selector": "window", "tag": "script", "text": "console.error"},
                    "evidence": {"type": "runtime", "description": "Console error: API_GATEWAY_URL missing"},
                    "recommendation": "Ensure mandatory configuration keys are loaded.",
                    "why_it_matters": "Console errors indicate underlying initialization failures.",
                    "claim": "Application startup logs console error.",
                    "viewport": "1440x900",
                    "evidence_requested": ["runtime"],
                    "reasoning": "Console error fired: Application Initialization Error.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-04-5",
                    "category": "RUNTIME",
                    "rule_type": "application_runtime_exception",
                    "title": "Uncaught application component runtime exception",
                    "description": "Uncaught Error thrown during component rendering.",
                    "observation": "Telemetry collector recorded uncaught window error event.",
                    "severity": "CRITICAL",
                    "confidence": 0.99,
                    "target": "window",
                    "affected_element": {"selector": "window", "tag": "script", "text": "window.onload"},
                    "evidence": {"type": "runtime", "description": "CRITICAL_APPLICATION_EXCEPTION"},
                    "recommendation": "Fix component rendering logic and handle exceptions.",
                    "why_it_matters": "Uncaught exceptions crash component sub-trees.",
                    "claim": "Component mounting failure throws runtime exception.",
                    "viewport": "1440x900",
                    "evidence_requested": ["runtime"],
                    "reasoning": "Uncaught Error thrown in TelemetryEngine.render().",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-04-6",
                    "category": "RUNTIME",
                    "rule_type": "application_network_failure",
                    "title": "Application HTTP 500 network request failure",
                    "description": "Fetch request to /api/v1/application-status-500 failed.",
                    "observation": "Network telemetry captured HTTP 500 server error response.",
                    "severity": "HIGH",
                    "confidence": 0.96,
                    "target": "/api/v1/application-status-500",
                    "affected_element": {"selector": "window", "tag": "script", "text": "fetch"},
                    "evidence": {"type": "runtime", "description": "HTTP 500 response on application endpoint"},
                    "recommendation": "Inspect backend API endpoint error logs.",
                    "why_it_matters": "API network failures break dynamic data loading.",
                    "claim": "Application endpoint returns HTTP 500 error.",
                    "viewport": "1440x900",
                    "evidence_requested": ["runtime"],
                    "reasoning": "Endpoint /api/v1/application-status-500 returned 500 Internal Server Error.",
                    "source": "AI",
                    "status": "candidate"
                }
            ])

        # ----------------------------------------------------
        # V0.4 Consolidated Benchmark Suite 05: Mixed Realistic
        # ----------------------------------------------------
        if "05_mixed_realistic_suite" in prompt_lower or "#mixed-missing-alt" in prompt_lower or "#mixed-visual-hierarchy" in prompt_lower:
            issues.extend([
                {
                    "id": f"AURA-CAND-05-1",
                    "category": "ACCESSIBILITY",
                    "rule_type": "image-alt",
                    "title": "Missing alt text on brand logo",
                    "description": "Logo SVG image #mixed-missing-alt lacks alt attribute.",
                    "observation": "Accessibility scan identified missing alt text.",
                    "severity": "MEDIUM",
                    "confidence": 0.98,
                    "target": "#mixed-missing-alt",
                    "affected_element": {"selector": "#mixed-missing-alt", "tag": "img", "text": ""},
                    "evidence": {"type": "accessibility", "description": "image-alt"},
                    "recommendation": "Add alt='Company Logo'.",
                    "why_it_matters": "Screen reader support.",
                    "claim": "Brand image missing alt text.",
                    "viewport": "1440x900",
                    "evidence_requested": ["accessibility"],
                    "reasoning": "#mixed-missing-alt image lacks alt.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-05-2",
                    "category": "UI",
                    "rule_type": "bad_visual_hierarchy",
                    "title": "Inverted action visual hierarchy",
                    "description": "Delete workspace button is giant red while save settings is tiny gray link.",
                    "observation": "Visual inspection identified inverted action hierarchy.",
                    "severity": "HIGH",
                    "confidence": 0.95,
                    "target": "#mixed-visual-hierarchy",
                    "affected_element": {"selector": "#mixed-visual-hierarchy", "tag": "div", "text": "Delete Organization Workspace"},
                    "evidence": {"type": "visual", "description": "Giant red button vs tiny link"},
                    "recommendation": "Promote primary save settings button.",
                    "why_it_matters": "Prevents accidental workspace deletion.",
                    "claim": "Hierarchy favors workspace deletion over saving.",
                    "viewport": "1440x900",
                    "evidence_requested": ["visual"],
                    "reasoning": "Giant red button for delete, 10px gray link for save.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-05-3",
                    "category": "UX",
                    "rule_type": "confusing_form",
                    "title": "Confusing form reset button styling",
                    "description": "Reset button is green 'Generate Token' while submit is gray 'Clear Fields'.",
                    "observation": "Form usability inspection identified inverted submit/reset styling.",
                    "severity": "HIGH",
                    "confidence": 0.94,
                    "target": "#mixed-confusing-form",
                    "affected_element": {"selector": "#mixed-confusing-form", "tag": "form", "text": "Generate Token"},
                    "evidence": {"type": "dom", "description": "input[type='reset'] styled as green submit"},
                    "recommendation": "Fix submit button action.",
                    "why_it_matters": "Form usability.",
                    "claim": "Reset button clears inputs when user expects submit.",
                    "viewport": "1440x900",
                    "evidence_requested": ["dom"],
                    "reasoning": "Green button is type reset.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-05-4",
                    "category": "UX",
                    "rule_type": "bad_navigation",
                    "title": "Overlapping navigation menu items",
                    "description": "Header navigation links overlap with negative margins.",
                    "observation": "Layout inspection identified negative link margin.",
                    "severity": "HIGH",
                    "confidence": 0.91,
                    "target": "#mixed-bad-nav",
                    "affected_element": {"selector": "#mixed-bad-nav", "tag": "nav", "text": "Settings"},
                    "evidence": {"type": "visual", "description": "margin-left: -20px"},
                    "recommendation": "Provide adequate spacing.",
                    "why_it_matters": "Navigation usability.",
                    "claim": "Links overlap in header.",
                    "viewport": "1440x900",
                    "evidence_requested": ["visual"],
                    "reasoning": "Settings link overlaps with Overview.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-05-5",
                    "category": "RESPONSIVENESS",
                    "rule_type": "horizontal_overflow",
                    "title": "Horizontal document overflow strip",
                    "description": "Banner strip #mixed-overflow width is 1600px causing horizontal scroll.",
                    "observation": "Browser geometry recorded scrollWidth > clientWidth.",
                    "severity": "HIGH",
                    "confidence": 0.97,
                    "target": "#mixed-overflow",
                    "affected_element": {"selector": "#mixed-overflow", "tag": "div", "text": "Real-Time Active Node"},
                    "evidence": {"type": "responsive", "description": "1600px width strip"},
                    "recommendation": "Use responsive width bounds.",
                    "why_it_matters": "Viewport responsive integrity.",
                    "claim": "Page exceeds viewport width.",
                    "viewport": "1440x900",
                    "evidence_requested": ["responsive"],
                    "reasoning": "Strip width is fixed at 1600px.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-05-6",
                    "category": "INTERACTION",
                    "rule_type": "interaction_failure",
                    "title": "Backup button throws script exception on click",
                    "description": "Clicking #mixed-interaction-fail throws uncaught exception.",
                    "observation": "Interaction logger recorded script error event.",
                    "severity": "CRITICAL",
                    "confidence": 0.99,
                    "target": "#mixed-interaction-fail",
                    "affected_element": {"selector": "#mixed-interaction-fail", "tag": "button", "text": "Trigger Immediate Full Backup"},
                    "evidence": {"type": "runtime", "description": "Uncaught Exception"},
                    "recommendation": "Fix backup event listener.",
                    "why_it_matters": "Unresponsive backup button.",
                    "claim": "Button click fails with exception.",
                    "viewport": "1440x900",
                    "evidence_requested": ["runtime", "interaction"],
                    "reasoning": "Clicking button throws Backup worker process died error.",
                    "source": "AI",
                    "status": "candidate"
                },
                {
                    "id": f"AURA-CAND-05-7",
                    "category": "RUNTIME",
                    "rule_type": "application_runtime_exception",
                    "title": "Background telemetry runtime exception",
                    "description": "Console error event fired during background telemetry sync.",
                    "observation": "Runtime collector captured console telemetry error.",
                    "severity": "CRITICAL",
                    "confidence": 0.96,
                    "target": "window",
                    "affected_element": {"selector": "window", "tag": "script", "text": "console.error"},
                    "evidence": {"type": "runtime", "description": "WebSocket heartbeat error"},
                    "recommendation": "Handle WebSocket disconnects.",
                    "why_it_matters": "Runtime telemetry failure.",
                    "claim": "Background telemetry throws console error.",
                    "viewport": "1440x900",
                    "evidence_requested": ["runtime"],
                    "reasoning": "WebSocket heartbeat error logged to console.",
                    "source": "AI",
                    "status": "candidate"
                }
            ])

        # 02_bad_button_name / axe-core button-name
        if "02_bad_button_name" in prompt_lower or "button-name" in prompt_lower:
            issues.append({
                "id": f"AURA-00{issue_counter}",
                "category": "ACCESSIBILITY",
                "rule_type": "button-name",
                "title": "Buttons must have discernible text",
                "description": "Button element lacks accessible text content or aria-label.",
                "observation": "Accessibility scan found unlabelled icon/button element.",
                "severity": "critical",
                "confidence": 0.99,
                "affected_element": {"selector": "button.icon-btn", "tag": "button", "text": ""},
                "evidence": {
                    "type": "accessibility",
                    "description": "axe-core violation rule: button-name"
                },
                "recommendation": "Add text content or aria-label to button elements.",
                "why_it_matters": "Screen reader users cannot determine the function of unlabelled buttons.",
                "claim": "Button element lacks accessible label.",
                "viewport": "1440x900",
                "evidence_required": ["accessibility", "dom"],
                "status": "candidate"
            })
            issue_counter += 1

        # 03_bad_contrast / axe-core color-contrast
        if "03_bad_contrast" in prompt_lower or "color-contrast" in prompt_lower:
            issues.append({
                "id": f"AURA-00{issue_counter}",
                "category": "ACCESSIBILITY",
                "rule_type": "color-contrast",
                "title": "Low text contrast ratio against background",
                "description": "Text element foreground and background colors do not meet minimum WCAG contrast standards.",
                "observation": "Visual contrast inspection identified text with insufficient contrast ratio.",
                "severity": "high",
                "confidence": 0.95,
                "affected_element": {"selector": "p.subtext", "tag": "p", "text": "Subtle detail text"},
                "evidence": {
                    "type": "accessibility",
                    "description": "axe-core violation rule: color-contrast"
                },
                "recommendation": "Increase text color contrast ratio to at least 4.5:1.",
                "why_it_matters": "Low contrast text causes readability difficulties for users with visual impairments.",
                "claim": "Text contrast ratio fails WCAG guidelines.",
                "viewport": "1440x900",
                "evidence_required": ["accessibility", "visual"],
                "status": "candidate"
            })
            issue_counter += 1

        # 04_bad_links
        if "04_bad_links" in prompt_lower or "javascript:void(0)" in prompt_lower or "href=\"#\"" in prompt_lower:
            issues.append({
                "id": f"AURA-00{issue_counter}",
                "category": "UX",
                "rule_type": "bad_navigation",
                "title": "Broken or non-functional navigation link",
                "description": "Link element uses placeholder href value without active destination route.",
                "observation": "DOM inspection identified anchor elements with href='javascript:void(0)' or '#'.",
                "severity": "medium",
                "confidence": 0.90,
                "affected_element": {"selector": "a.broken-link", "tag": "a", "text": "Learn More"},
                "evidence": {
                    "type": "dom",
                    "description": "Anchor element has non-navigable href attribute value."
                },
                "recommendation": "Assign valid navigation target URLs to anchor elements.",
                "why_it_matters": "Broken links lead to user frustration and dead-end interaction flows.",
                "claim": "Anchor tag does not link to valid destination.",
                "viewport": "1440x900",
                "evidence_required": ["dom"],
                "status": "candidate"
            })
            issue_counter += 1

        # 05_bad_landmarks
        if "05_bad_landmarks" in prompt_lower or "landmark-one-main" in prompt_lower or "landmark" in prompt_lower:
            issues.append({
                "id": f"AURA-00{issue_counter}",
                "category": "ACCESSIBILITY",
                "rule_type": "landmark-one-main",
                "title": "Page missing main landmark role",
                "description": "Document body lacks a <main> element or role='main' landmark container.",
                "observation": "DOM inspection identified missing main content structural landmark.",
                "severity": "medium",
                "confidence": 0.95,
                "affected_element": {"selector": "body", "tag": "body", "text": "Document Body"},
                "evidence": {
                    "type": "accessibility",
                    "description": "axe-core violation rule: landmark-one-main"
                },
                "recommendation": "Wrap primary content inside a <main> structural element.",
                "why_it_matters": "Assistive technology users rely on landmarks for direct section navigation.",
                "claim": "Document lacks main landmark element.",
                "viewport": "1440x900",
                "evidence_required": ["accessibility", "dom"],
                "status": "candidate"
            })
            issue_counter += 1

        # 06_bad_form_labels
        if "06_bad_form_labels" in prompt_lower or "form elements must have labels" in prompt_lower:
            issues.append({
                "id": f"AURA-00{issue_counter}",
                "category": "FORM",
                "rule_type": "label",
                "title": "Form inputs missing associated label",
                "description": "Input fields lack explicitly linked label elements or aria-label attributes.",
                "observation": "Form inputs detected without associated label or aria-label attributes.",
                "severity": "critical",
                "confidence": 0.99,
                "affected_element": {"selector": "input#email", "tag": "input", "text": "email"},
                "evidence": {
                    "type": "dom",
                    "description": "DOM inspection found form input lacking label association."
                },
                "recommendation": "Link each input with a <label for='...'> or aria-label attribute.",
                "why_it_matters": "Screen reader users cannot identify input purpose without labels.",
                "claim": "Form input lacks linked label.",
                "viewport": "1440x900",
                "evidence_required": ["dom", "accessibility"],
                "status": "candidate"
            })
            issue_counter += 1

        # 07_bad_navigation
        if "07_bad_navigation" in prompt_lower or ("nav" in prompt_lower and "overlap" in prompt_lower) or ("navigation" in prompt_lower and "bad" in prompt_lower):
            issues.append({
                "id": f"AURA-00{issue_counter}",
                "category": "UX",
                "rule_type": "bad_navigation",
                "title": "Overlapping or misleading navigation elements",
                "description": "Navigation links overlap in absolute positioning causing layout obstruction and unclear destinations.",
                "observation": "Navigation layout analysis detected overlapping bounding boxes among header nav links.",
                "severity": "high",
                "confidence": 0.88,
                "affected_element": {"selector": "nav.main-nav", "tag": "nav", "text": "Navigation Menu"},
                "evidence": {
                    "type": "visual",
                    "description": "Bounding box geometric overlap detected in navigation element tree."
                },
                "recommendation": "Ensure navigation items have clear spacing and unambiguous labels.",
                "why_it_matters": "Overlapping navigation controls block interaction and confuse users.",
                "claim": "Navigation controls overlap or present confusing choices.",
                "viewport": "1440x900",
                "evidence_required": ["visual", "dom"],
                "status": "candidate"
            })
            issue_counter += 1

        # 08_bad_visual_hierarchy
        if "08_bad_visual_hierarchy" in prompt_lower or "hierarchy" in prompt_lower or "cta" in prompt_lower:
            issues.append({
                "id": f"AURA-00{issue_counter}",
                "category": "UX",
                "rule_type": "weak_primary_cta",
                "title": "Primary action button lacks visual hierarchy prominence",
                "description": "The primary call-to-action appears visually similar or diminished relative to secondary controls.",
                "observation": "Primary CTA button styling shares neutral contrast with adjacent secondary controls.",
                "severity": "high",
                "confidence": 0.86,
                "affected_element": {"selector": "button.btn-primary", "tag": "button", "text": "Explore Products"},
                "evidence": {
                    "type": "visual",
                    "description": "Visual inspection indicates primary CTA button lacks visual emphasis."
                },
                "recommendation": "Increase visual contrast, font size, and prominence of primary CTA button.",
                "why_it_matters": "Users may have difficulty identifying the intended primary conversion action.",
                "claim": "Primary CTA lacks sufficient visual prominence.",
                "viewport": "1440x900",
                "evidence_required": ["visual"],
                "status": "candidate"
            })
            issue_counter += 1

        # 09_runtime_errors
        if "09_runtime_errors" in prompt_lower or ("console_errors" in prompt_lower and "[]" not in prompt_lower and "console errors: []" not in prompt_lower):
            issues.append({
                "id": f"AURA-00{issue_counter}",
                "category": "RUNTIME",
                "rule_type": "application_console_error",
                "title": "Unhandled JavaScript Console Error",
                "description": "Uncaught JavaScript exception recorded during page execution.",
                "observation": "Browser telemetry captured uncaught script errors in the console log.",
                "severity": "high",
                "confidence": 0.95,
                "affected_element": {"selector": "window", "tag": "script", "text": "global console"},
                "evidence": {
                    "type": "runtime",
                    "description": "Console error event recorded during runtime inspection."
                },
                "recommendation": "Inspect stack trace and resolve uncaught exceptions.",
                "why_it_matters": "Script failures can disrupt dynamic page features and user interactions.",
                "claim": "Application throws uncaught runtime exception.",
                "viewport": "1440x900",
                "evidence_required": ["runtime"],
                "status": "candidate"
            })
            issue_counter += 1

        # 10_network_failures
        if "10_network_failures" in prompt_lower or ("network_failures" in prompt_lower and "[]" not in prompt_lower and "network failures: []" not in prompt_lower):
            issues.append({
                "id": f"AURA-00{issue_counter}",
                "category": "RUNTIME",
                "rule_type": "application_network_failure",
                "title": "HTTP Network Endpoint Failure",
                "description": "Application request returned HTTP 4xx or 5xx error status code.",
                "observation": "Network telemetry captured failing API endpoint request.",
                "severity": "high",
                "confidence": 0.96,
                "affected_element": {"selector": "network", "tag": "fetch", "text": "API request"},
                "evidence": {
                    "type": "runtime",
                    "description": "Network telemetry HTTP failure recorded."
                },
                "recommendation": "Verify API endpoint health and handle network failure states gracefully.",
                "why_it_matters": "Network failures prevent data loading and degrade user experience.",
                "claim": "HTTP network request failed with error status code.",
                "viewport": "1440x900",
                "evidence_required": ["runtime"],
                "status": "candidate"
            })
            issue_counter += 1

        # 11_mobile_layout / horizontal overflow
        if "11_mobile_layout" in prompt_lower or "has_horizontal_overflow\": true" in prompt_lower or "390x844" in prompt_lower or "overflow" in prompt_lower:
            issues.append({
                "id": f"AURA-00{issue_counter}",
                "category": "RESPONSIVENESS",
                "rule_type": "horizontal_overflow",
                "title": "Mobile horizontal layout overflow detected",
                "description": "Fixed-width container causes horizontal document scrolling and clipped content under narrow viewports.",
                "observation": "Layout geometry inspection identified document scroll width exceeding viewport width.",
                "severity": "high",
                "confidence": 0.92,
                "affected_element": {"selector": "div.container", "tag": "div", "text": "Page Layout Container"},
                "evidence": {
                    "type": "visual",
                    "description": "Document scroll width exceeds viewport width causing horizontal overflow."
                },
                "recommendation": "Use responsive max-width: 100% rules and flex/grid containers.",
                "why_it_matters": "Horizontal scrolling on mobile devices degrades readability and control usability.",
                "claim": "Page container overflows viewport horizontally.",
                "viewport": "390x844",
                "evidence_required": ["visual", "dom"],
                "status": "candidate"
            })
            issue_counter += 1

        # 12_confusing_form
        if "12_confusing_form" in prompt_lower or "type=\"reset\"" in prompt_lower or "form reset" in prompt_lower or ("reset" in prompt_lower and "submit" in prompt_lower):
            issues.append({
                "id": f"AURA-00{issue_counter}",
                "category": "UX",
                "rule_type": "confusing_form",
                "title": "Confusing form submit button resets form input",
                "description": "Form button labeled 'Submit Form' is configured with type='reset', accidentally clearing user input.",
                "observation": "Form analysis detected submit button configured with reset behavior.",
                "severity": "high",
                "confidence": 0.94,
                "affected_element": {"selector": "button[type='reset']", "tag": "button", "text": "Submit Form"},
                "evidence": {
                    "type": "dom",
                    "description": "Button labeled 'Submit Form' triggers form reset."
                },
                "recommendation": "Change button type to 'submit' or update button label to accurately reflect reset action.",
                "why_it_matters": "Unexpected form reset causes immediate data loss and user frustration.",
                "claim": "Submit button unexpectedly resets form inputs.",
                "viewport": "1440x900",
                "evidence_required": ["dom", "visual"],
                "status": "candidate"
            })
            issue_counter += 1

        # 13_interaction_failure
        if "13_interaction_failure" in prompt_lower or ("interaction" in prompt_lower and "fail" in prompt_lower):
            issues.append({
                "id": f"AURA-00{issue_counter}",
                "category": "UX",
                "rule_type": "interaction_failure",
                "title": "Interactive control fails to execute expected action",
                "description": "Clicking interactive button element throws script exception or produces no state change.",
                "observation": "Interaction logging recorded execution failure or script error upon control activation.",
                "severity": "high",
                "confidence": 0.89,
                "affected_element": {"selector": "button.action-btn", "tag": "button", "text": "Trigger Action"},
                "evidence": {
                    "type": "runtime",
                    "description": "Script error or unhandled promise rejection recorded during button interaction."
                },
                "recommendation": "Fix click event handler and add user feedback for interaction states.",
                "why_it_matters": "Unresponsive controls create dead ends in user interaction workflows.",
                "claim": "Button click fails to execute action.",
                "viewport": "1440x900",
                "evidence_required": ["runtime", "dom"],
                "status": "candidate"
            })
            issue_counter += 1

        # 14_mixed_defects
        if "14_mixed_defects" in prompt_lower and not issues:
            issues.extend([
                {
                    "id": f"AURA-00{issue_counter}",
                    "category": "ACCESSIBILITY",
                    "rule_type": "image-alt",
                    "title": "Images missing descriptive alt text",
                    "description": "Image element lacks alt text.",
                    "observation": "axe-core violation rule: image-alt",
                    "severity": "high",
                    "confidence": 0.98,
                    "affected_element": {"selector": "img", "tag": "img", "text": "Visual"},
                    "evidence": {"type": "accessibility", "description": "image-alt"},
                    "recommendation": "Add alt text.",
                    "why_it_matters": "Accessibility impact.",
                    "claim": "Missing alt text.",
                    "viewport": "1440x900",
                    "evidence_required": ["accessibility"],
                    "status": "candidate"
                },
                {
                    "id": f"AURA-00{issue_counter+1}",
                    "category": "RUNTIME",
                    "rule_type": "application_console_error",
                    "title": "Unhandled JavaScript Console Error",
                    "description": "Uncaught exception.",
                    "observation": "Console error event.",
                    "severity": "high",
                    "confidence": 0.95,
                    "affected_element": {"selector": "window", "tag": "script", "text": "script"},
                    "evidence": {"type": "runtime", "description": "Console error"},
                    "recommendation": "Fix script.",
                    "why_it_matters": "Runtime failure.",
                    "claim": "Script error.",
                    "viewport": "1440x900",
                    "evidence_required": ["runtime"],
                    "status": "candidate"
                }
            ])
            issue_counter += 2

        # Intentionally contradictory candidate finding to test REJECTED status in verifier
        issues.append({
            "id": f"AURA-00{issue_counter}",
            "category": "UI",
            "rule_type": "discoverability_problem",
            "title": "Main navigation menu appears hidden",
            "description": "Navigation links claimed to be absent or hidden.",
            "observation": "Navigation links appear absent from page header.",
            "severity": "low",
            "confidence": 0.60,
            "affected_element": {"selector": "nav.main-nav", "tag": "nav", "text": "Main Navigation"},
            "evidence": {
                "type": "visual",
                "description": "Visual observation suggests header navigation is hidden."
            },
            "recommendation": "Ensure main navigation menu is visible.",
            "why_it_matters": "Hidden navigation prevents easy section switching.",
            "claim": "Navigation menu is hidden from view.",
            "viewport": "1440x900",
            "evidence_required": ["visual", "dom"],
            "status": "candidate"
        })

        return json.dumps({
            "overall_summary": "AURA evidence-driven inspection complete. Generated candidate findings for independent verification.",
            "issues": issues
        })

    def test_connection(self) -> Tuple[bool, str]:
        return True, "Mock AI Provider active (Offline simulation mode)."
