"""
Report content, part 2: Chapters 4-6, references and appendices.

Chapter 5 quotes the measurement in report/figures and benchmark_result.json. Those numbers were
produced by running each suite and reading the evaluator's output; none of them is estimated, rounded
in our favour, or carried over from an earlier version of the system.
"""

CHAPTER_4 = {
    "number": 4, "title": "PROPOSED ALGORITHM",
    "sections": [
        {"number": "4.1", "title": "OVERVIEW", "blocks": [
            {"p": "AURA's proposition is a single architectural commitment: the language model proposes, "
                  "and evidence decides. The model is given a focused packet of evidence collected from "
                  "the page and asked what is wrong. Its answer is treated as a list of hypotheses. A "
                  "verification stage that the model cannot influence then tests each hypothesis against "
                  "that same evidence, and only what survives is shown to the user."},
            {"p": "This inverts the usual arrangement. In a conventional model-backed tool the model's "
                  "output is the product; everything downstream is presentation. In AURA the model's "
                  "output is an input, and the product is the subset of it that the page itself can be "
                  "shown to support. The consequence is a guarantee that can be stated to a user: "
                  "nothing is displayed which the collected evidence contradicts."},
            {"p": "A second commitment follows from deployment rather than accuracy. The model call is "
                  "made by the user's browser, with the user's own API key, so the analysis service "
                  "never holds a credential belonging to a user and never receives a screenshot. This is "
                  "not a privacy feature bolted on afterwards; it determines the shape of the request "
                  "flow described in Section 4.3."},
        ]},
        {"number": "4.2", "title": "EVIDENCE VERIFICATION MODEL ARCHITECTURE", "blocks": [
            {"p": "The verification model is the technical core of the project. It takes a candidate "
                  "finding - a rule type, a target reference, a description and the model's own stated "
                  "confidence - and decides what, if anything, the collected evidence says about it."},
            {"p": "Verification proceeds in four stages, and a candidate may be discarded at any of them."},
            {"bullets": [
                "Target resolution. The candidate names an element by a neutral reference such as E12. "
                "The reference is resolved back to a selector, and the element is located in the captured "
                "DOM. A candidate whose target cannot be resolved cannot be verified and is not reported "
                "as if it were.",
                "Evidence checking. The claim is compared against what was measured. A claim that an "
                "element is invisible is tested against its recorded bounding box, computed visibility "
                "and position; a claim about contrast against the computed colours; a claim about "
                "overflow against the document and viewport widths. A claim the measurements contradict "
                "is rejected outright.",
                "Materiality gating. A claim the evidence neither contradicts nor confirms is classified "
                "by whether it describes a defect or a preference. 'The button could be larger' is not a "
                "defect; 'the destructive action is more prominent than the primary one' is, and is "
                "measurable from the two elements' rendered weights.",
                "Verdict assignment. What survives carries CONFIRMED, LIKELY or UNCERTAIN according to "
                "how directly the evidence supports it, together with the evidence that produced the "
                "verdict. The user is told which, and why, rather than being given a number to trust.",
            ]},
            {"figure": {"file": "fig_4_3_pipeline.png", "number": "4.1",
                        "caption": "The verification pipeline applied to one AI claim"}},
            {"p": "Alongside the verified model output, AURA reports findings that need no model at all. "
                  "Accessibility violations come from axe-core executed in the page. Runtime errors and "
                  "failed requests come from browser telemetry captured during the scan. Controls that "
                  "AURA operated and that produced no response at all are reported from the recorded "
                  "before-and-after page state. These are measurements, and they are reported whether or "
                  "not the model mentions them."},
        ]},
        {"number": "4.3", "title": "SYSTEM ARCHITECTURE", "blocks": [
            {"p": "The system divides along the boundary that the privacy commitment forces. Everything "
                  "that must see the rendered page or hold the user's key runs in the browser. "
                  "Everything that decides what is true runs on the analysis service, where it cannot be "
                  "influenced by the model that produced the claim."},
            {"figure": {"file": "fig_4_1_architecture.png", "number": "4.2",
                        "caption": "AURA system architecture"}},
            {"p": "A scan is therefore two short requests with the model call between them, rather than "
                  "one long request that passes through the service. The extension sends the evidence "
                  "and receives the prepared prompt; it calls the provider itself; it returns the raw "
                  "answer for verification. The service sees the page's structure and the model's "
                  "answer, and never the key or the screenshot."},
            {"figure": {"file": "fig_4_2_two_phase.png", "number": "4.3",
                        "caption": "The two-phase scan sequence"}},
            {"table": {"number": "4.1", "caption": "Key components and operational steps of the AURA architecture",
                       "headers": ["Step", "Where it runs", "What happens"],
                       "widths": [2200, 1900, 4900],
                       "rows": [
                           ["1. Activation", "Browser", "The user clicks the AURA icon on a tab, which grants access to that tab only. Nothing runs in any page before this."],
                           ["2. Collection", "Browser", "DOM structure, geometry and computed styles; axe-core results; runtime errors and failed requests; optional safe interactions; a screenshot."],
                           ["3. Preparation", "Service", "The evidence is validated against a schema, reduced to a focused packet with neutral element references, and rendered into the prompt."],
                           ["4. Proposal", "Browser", "The browser calls the user's chosen provider with the prompt, the screenshot and the user's key, and receives a raw answer."],
                           ["5. Verification", "Service", "The answer is parsed, each candidate is independently checked against the evidence, and unsupported claims are rejected."],
                           ["6. Interpretation", "Service", "Surviving findings are correlated, scored, and expressed in plain language with their evidence and verdict."],
                           ["7. Presentation", "Browser", "Findings are listed; Highlight marks the element in the page and Screenshot crops the capture locally, without any upload."],
                       ]}},
        ]},
        {"number": "4.3.1", "title": "MERITS OF THE PROPOSED AURA SYSTEM", "level": 3, "blocks": [
            {"bullets": [
                "A claim the evidence contradicts is never shown, so the user is not asked to filter the "
                "tool's output.",
                "Every finding carries the evidence that produced it and an honest verdict, so a "
                "developer can judge it without repeating the analysis.",
                "Findings name an element that can be resolved and highlighted in the live page.",
                "Failure is reported as failure. When the provider is unavailable or refuses the request, "
                "the deterministic findings are still produced and the absence of AI analysis is stated.",
                "The service holds no user credential and receives no screenshot, so a breach of it "
                "exposes neither.",
                "The analysis works on pages no external crawler can reach: behind a login, on localhost, "
                "in staging.",
            ]},
        ]},
        {"number": "4.3.2", "title": "MODULE DESCRIPTION", "level": 3, "blocks": [
            {"table": {"number": "4.2", "caption": "Principal modules of the AURA system",
                       "headers": ["Module", "Responsibility"],
                       "widths": [3000, 6000],
                       "rows": [
                           ["extension/sidepanel/scanner.js", "Collects evidence from the active tab and orchestrates the two-phase scan."],
                           ["extension/sidepanel/providers.js", "Calls Groq, Gemini, OpenAI or Anthropic directly from the browser with the user's key; one retry for a transient refusal."],
                           ["extension/sidepanel/shot.js", "Crops the per-finding screenshot in the browser and marks the element, so no image is uploaded."],
                           ["aura/evidence/bundle.py", "Validates the evidence bundle against a schema and bounds every field."],
                           ["aura/agent/evidence_packet.py", "Reduces the evidence to the focused packet the model is shown, with neutral element references."],
                           ["aura/verification/", "The independent verification engine: target resolution, evidence checking and the materiality gate."],
                           ["aura/findings/aggregation.py", "Assembles findings from axe-core, runtime telemetry, measured interactions and verified AI candidates."],
                           ["aura/interpretation/", "Turns a verified finding into plain language with its evidence, verdict and recommendation."],
                           ["aura/api/relay.py", "Carries the browser's model call through the pipeline, so the service runs unchanged while holding no key."],
                           ["aura/api/server.py", "The HTTP API: registration, the two-phase scan, explanation, screenshots and Ask AURA."],
                           ["aura/evaluation/", "The benchmark evaluator, which reads ground truth only after an audit has completed."],
                       ]}},
        ]},
        {"number": "4.4", "title": "NOVELTY: INDEPENDENT VERIFICATION AND MATERIALITY GATING", "blocks": [
            {"p": "The novelty of this work is not the use of a multimodal model to critique an "
                  "interface, which is now commonplace, but the refusal to treat that critique as the "
                  "result. Two mechanisms implement the refusal."},
            {"p": "The first is independent verification. The verification engine receives the candidate "
                  "and the evidence, and nothing else: it does not see the model's reasoning, cannot be "
                  "addressed by the model, and applies the same checks to every candidate regardless of "
                  "the confidence the model attached. This separation is what allows a guarantee to be "
                  "made about output rather than a claim to be made about average behaviour."},
            {"p": "The second is the materiality gate. Verification establishes whether a claim is "
                  "consistent with the evidence; materiality establishes whether it is worth reporting. "
                  "Without it, a verified but trivial observation is indistinguishable from a verified "
                  "defect, and a tool that reports everything it can justify is as unusable as one that "
                  "reports things it cannot."},
            {"p": "A third mechanism follows from the first two. Because verification is deterministic "
                  "and evidence-driven, a defect that can be established from evidence alone need not "
                  "involve the model at all. Accessibility violations, runtime errors and controls that "
                  "were operated and produced no response are reported directly from measurement, which "
                  "makes those findings independent of which model the user chose and whether it was "
                  "available."},
        ]},
        {"number": "4.4.1", "title": "COMPARISON WITH OTHER TECHNOLOGIES", "level": 3, "blocks": [
            {"table": {"number": "4.3", "caption": "AURA compared with existing technologies",
                       "headers": ["Property", "Rule engine", "Prompted LLM reviewer", "AURA"],
                       "widths": [2400, 2000, 2200, 2400],
                       "rows": [
                           ["Detects conformance defects", "Yes", "Sometimes", "Yes, from axe-core"],
                           ["Detects design-level defects", "No", "Yes, unreliably", "Yes, when evidence supports"],
                           ["Output verified against the page", "By construction", "No", "Yes, independently"],
                           ["Finding names a resolvable element", "Yes", "Rarely", "Yes, with highlight"],
                           ["Honest confidence", "Not needed", "Model self-report", "Verdict from evidence"],
                           ["Behaviour when AI fails", "Not applicable", "Empty result", "Deterministic findings, failure stated"],
                           ["Holds the user's API key", "Not applicable", "Usually yes", "Never"],
                           ["Receives screenshots", "No", "Yes", "No"],
                       ]}},
        ]},
        {"number": "4.5", "title": "ADVANTAGES", "blocks": [
            {"bullets": [
                "Trustworthy breadth: design-level defects are reported without asking the user to take "
                "the model's word for them.",
                "Actionable output: each finding can be highlighted in the live page and cropped from the "
                "screenshot taken during the scan.",
                "Privacy by architecture: no credential and no screenshot reaches the service, and nothing "
                "is written to its disk.",
                "Provider independence: four providers are supported and the user chooses; the system "
                "degrades to deterministic findings rather than failing.",
                "Free to run: the extension is free and both recommended providers have free tiers.",
                "Reproducible evaluation: a benchmark with isolated ground truth makes claims about "
                "accuracy checkable rather than asserted.",
            ]},
        ]},
    ],
}

CHAPTER_5 = {
    "number": 5, "title": "PERFORMANCE ANALYSIS",
    "sections": [
        {"number": "5.1", "title": "OVERVIEW", "blocks": [
            {"p": "This chapter reports what the system was measured to do, how the measurement was "
                  "made, and what the measurement does not establish. The results are modest, and they "
                  "are reported as measured. A benchmark whose numbers cannot be reproduced is worse "
                  "than no benchmark, so the method is given in enough detail to repeat it."},
        ]},
        {"number": "5.2", "title": "SIMULATION TOOL", "blocks": [
            {"p": "Evaluating an interface auditor requires pages whose defects are known in advance. No "
                  "public dataset provides this for design-level defects, so a Test Lab was built: five "
                  "consolidated web pages, served locally, each carrying deliberately seeded defects "
                  "across the categories the system claims to address."},
            {"table": {"number": "5.1", "caption": "The Test Lab benchmark suites",
                       "headers": ["Suite", "Focus", "Seeded defects"],
                       "widths": [3000, 4200, 1800],
                       "rows": [
                           ["01 Accessibility", "Missing alternative text, unnamed controls, contrast, labels, landmarks", "6"],
                           ["02 UI/UX", "Visual hierarchy, weak call to action, confusing form, cognitive density", "6"],
                           ["03 Navigation and interaction", "Broken navigation, dead controls, failed form submission", "6"],
                           ["04 Responsive and runtime", "Horizontal overflow, clipped content, console errors, failed requests", "6"],
                           ["05 Mixed realistic", "A realistic dashboard combining defects from all categories", "7"],
                           ["Total", "", "31"],
                       ]}},
        ]},
        {"number": "5.2.1", "title": "DETAILED DESCRIPTION OF THE SIMULATION TOOL", "level": 3, "blocks": [
            {"p": "Each suite carries its ground truth as a machine-readable record listing every seeded "
                  "defect with its category, rule, target element and the evidence that should establish "
                  "it. The integrity of the benchmark rests on that record being invisible to the system "
                  "under test."},
            {"p": "Three mechanisms enforce this. The ground truth is stripped during DOM extraction, so "
                  "it cannot enter the evidence packet. It is never part of a prompt, and a test asserts "
                  "that the packet contains none of it. It is read only after an audit has completed, by "
                  "a separate evaluation engine that the audit pipeline cannot call. The system is "
                  "therefore unable to tune itself towards the answer, and a result of zero for a suite "
                  "is reported as zero."},
            {"p": "A detection counts as a true positive when a reported finding matches a seeded defect "
                  "on category, rule and target. Anything reported that does not match a seeded defect "
                  "is counted as a false positive, and any seeded defect not reported is a false "
                  "negative. Section 5.4 examines what this definition does and does not mean."},
        ]},
        {"number": "5.3", "title": "PERFORMANCE ANALYSIS AND METRICS", "blocks": [
            {"p": "The benchmark was run against the completed system using Groq's qwen/qwen3.8-27b, "
                  "with each suite audited separately. Running the five suites consecutively exhausts "
                  "the provider's free-tier allowance of one thousand output tokens per minute, which "
                  "causes whichever suite is throttled to return no analysis at all; consecutive whole-"
                  "benchmark runs then disagree with one another and neither is a measurement. Auditing "
                  "each suite on its own, with the per-request output budget held below the provider's "
                  "limit, removes that source of variation."},
            {"figure": {"file": "fig_5_1_benchmark.png", "number": "5.1",
                        "caption": "Aggregate detection performance across 31 seeded defects"}},
            {"table": {"number": "5.2", "caption": "AURA detection performance per suite",
                       "headers": ["Suite", "TP", "FP", "FN", "Precision", "Recall"],
                       "widths": [3000, 900, 900, 900, 1500, 1500],
                       "rows": [
                           ["01 Accessibility", "3", "4", "3", "42.9%", "50.0%"],
                           ["02 UI/UX", "3", "3", "3", "50.0%", "50.0%"],
                           ["03 Navigation and interaction", "1", "5", "5", "16.7%", "16.7%"],
                           ["04 Responsive and runtime", "4", "4", "2", "50.0%", "66.7%"],
                           ["05 Mixed realistic", "4", "6", "3", "40.0%", "57.1%"],
                           ["Aggregate", "15", "22", "16", "40.5%", "48.4%"],
                       ]}},
            {"figure": {"file": "fig_5_2_per_suite.png", "number": "5.2",
                        "caption": "Detection per suite"}},
            {"p": "Across the five suites AURA reported 37 findings, of which 15 matched one of the 31 "
                  "seeded defects. This gives a precision of 40.5 per cent, a recall of 48.4 per cent "
                  "and an F1 score of 44.1 per cent."},
            {"p": "Three defects found during this evaluation were traced to the implementation and "
                  "corrected, and they are reported here because the evaluation is what exposed them. "
                  "The first was in the provider client: a retry that lowers the output budget when a "
                  "request exceeds a per-minute limit was guarded by a floor of 1024 tokens, while the "
                  "free tier's stated limit is 1000, so the retry could never run for the accounts that "
                  "needed it and two of the five suites lost their AI analysis entirely. The second was "
                  "in interaction testing: the page-state signature compared only visible text, so a "
                  "control that toggled a class or an attribute was recorded identically to one that did "
                  "nothing. The third was that the evidence of a non-responsive control, once collected, "
                  "was offered only to the model, which did not report it; such controls are now reported "
                  "directly from the measurement."},
            {"table": {"number": "5.3", "caption": "Comparative performance before and after the corrections",
                       "headers": ["Measurement", "TP", "FP", "FN", "Precision", "Recall", "F1"],
                       "widths": [2600, 800, 800, 800, 1300, 1300, 1200],
                       "rows": [
                           ["Before, whole run", "15", "20", "16", "42.9%", "48.4%", "45.5%"],
                           ["After, per suite", "15", "22", "16", "40.5%", "48.4%", "44.1%"],
                       ]}},
            {"p": "The corrections did not move the aggregate. This is stated plainly because it is the "
                  "result: they fixed real defects - two suites that previously returned no analysis now "
                  "return it, and dead controls are now named - without improving the score, because the "
                  "score is limited by other factors examined in the next section."},
        ]},
        {"number": "5.4", "title": "INFERENCES AND SIGNIFICANCE", "blocks": [
            {"p": "The headline figures understate the system's usefulness in one specific, measurable "
                  "way, and overstate it in none. The reasons are worth setting out precisely."},
            {"bullets": [
                "A false positive here means 'not one of the 31 seeded defects', not 'wrong'. The suites "
                "contain real interface problems their authors did not seed, and a correct report of one "
                "is counted against the system.",
                "The ground truth and the system use different vocabularies for the same defect, and "
                "matching requires the rule to agree. AURA reports a control it operated to no effect "
                "under the rule non_responsive_control, which the evaluator's alias table relates only "
                "to dead_button. Two of suite 03's seeded defects carry the rules broken_menu and "
                "broken_form_submission on exactly the kind of control that produces such a finding, and "
                "neither is an alias of it, so a correct detection on the right element is counted as a "
                "false positive while the seeded defect remains a false negative.",
                "One seeded defect is unreachable by design. Its control is labelled 'Execute Balance "
                "Transfer', and AURA's safety policy refuses to click anything matching 'transfer', so "
                "the evidence that would establish it can never be collected. This is correct behaviour "
                "producing a permanent false negative.",
                "Recall is bounded by what the proposing model chooses to report. Given the same evidence "
                "the model consistently favours visual observations over measured interaction failures, "
                "which is why moving that class of defect to deterministic reporting was the right fix "
                "rather than further prompt engineering.",
            ]},
            {"p": "What the measurement does establish is the property the architecture was built for. "
                  "Of the candidates the model proposed across these runs, those the evidence could not "
                  "support were rejected before display rather than shown to the user, and no finding "
                  "was reported for an element that could not be resolved in the page. The verification "
                  "stage behaved as specified on every run."},
            {"p": "Beyond the benchmark, the system was exercised end to end against its deployed "
                  "service with two providers. A scan of a live page through the public service "
                  "completed in 7.0 seconds with Groq and 29.4 seconds with Gemini, the AI call being "
                  "made by the browser in both cases, with the service receiving no key and no "
                  "screenshot. The automated test suite comprises 571 tests, complemented by five "
                  "browser-driven suites that exercise the real extension in a real browser, including "
                  "one in Microsoft Edge."},
        ]},
    ],
}

CHAPTER_6 = {
    "number": 6, "title": "CONCLUSION",
    "sections": [
        {"number": "6.1", "title": "CONCLUSION", "blocks": [
            {"p": "This project set out to make a broad, model-generated interface critique trustworthy "
                  "enough for a developer to act on. The approach taken was to deny the model the final "
                  "word: its observations are treated as candidates, and an independent verification "
                  "stage decides, from evidence collected in the page itself, which of them may be "
                  "shown. That mechanism was implemented, deployed and measured."},
            {"p": "The system is complete and in public use. The analysis service runs as a container on "
                  "a public host, holding no user credential and writing nothing to disk; the extension "
                  "is published through the Microsoft Edge Add-ons store and runs in any Chromium "
                  "browser; the AI call is made by the user's own browser with the user's own key, so "
                  "the service cannot leak what it never receives. Screenshots never leave the browser."},
            {"p": "Measured against 31 deliberately seeded defects, the system achieved a precision of "
                  "40.5 per cent, a recall of 48.4 per cent and an F1 score of 44.1 per cent. These "
                  "figures are honest rather than flattering, and Chapter 5 sets out both the "
                  "methodological reasons they understate detection and the genuine limits they expose. "
                  "The evaluation also did what an evaluation is for: it uncovered three implementation "
                  "defects that had gone unnoticed through 571 passing tests, each of which has been "
                  "corrected and covered by a regression test."},
            {"p": "The contribution is therefore less a score than a demonstration: that a verification "
                  "stage can be interposed between a language model and a user, that it can be made "
                  "deterministic and inspectable, and that a system built this way can state what it "
                  "knows, what it suspects and what it could not establish - rather than presenting all "
                  "three in the same confident voice."},
        ]},
        {"number": "6.2", "title": "SCOPE FOR FUTURE WORK", "blocks": [
            {"bullets": [
                "Reconcile the benchmark's vocabulary with the system's. The evaluator relates "
                "non_responsive_control only to dead_button, so a correct detection on a defect seeded "
                "as broken_menu or broken_form_submission is counted twice against the system. Extending "
                "the alias table on the meaning of the rules - and deciding it before looking at what it "
                "does to the score - would make the measurement reflect behaviour.",
                "Raise recall on interaction defects. Moving non-responsive controls to deterministic "
                "reporting helped; broken menus, failed form submissions and misleading calls to action "
                "remain dependent on the model noticing them.",
                "Evaluate across models. Every figure here is from one model on one provider's free tier. "
                "Measuring the same suites across providers would separate what the architecture "
                "contributes from what the model contributes.",
                "Capture errors raised during page load. The extension attaches after load, so exceptions "
                "thrown while the page was loading cannot be observed. An opt-in reload-and-capture mode "
                "would close that gap.",
                "Handle iframes and shadow DOM, which the collector does not currently traverse.",
                "Widen the benchmark. Thirty-one seeded defects across five pages is enough to find "
                "implementation defects, and too small to support confident claims about accuracy.",
            ]},
        ]},
    ],
}

REFERENCES = [
    "Deque Systems, \"axe-core: Accessibility Engine for Automated Web UI Testing,\" Version 4.8.2, "
    "2023. [Online]. Available: https://github.com/dequelabs/axe-core",
    "World Wide Web Consortium, \"Web Content Accessibility Guidelines (WCAG) 2.1,\" W3C "
    "Recommendation, June 2018.",
    "J. Nielsen, Usability Engineering. San Francisco, CA: Morgan Kaufmann, 1993.",
    "A. Vaswani, N. Shazeer, N. Parmar, J. Uszkoreit, L. Jones, A. N. Gomez, L. Kaiser, and I. "
    "Polosukhin, \"Attention Is All You Need,\" in Advances in Neural Information Processing Systems "
    "(NeurIPS), pp. 5998-6008, 2017.",
    "A. Dosovitskiy, L. Beyer, A. Kolesnikov, D. Weissenborn, X. Zhai, T. Unterthiner, et al., \"An "
    "Image is Worth 16x16 Words: Transformers for Image Recognition at Scale,\" in International "
    "Conference on Learning Representations (ICLR), pp. 1-21, 2021.",
    "OpenAI, \"GPT-4 Technical Report,\" arXiv preprint arXiv:2303.08774, 2023.",
    "Google, \"Lighthouse: Automated Auditing, Performance Metrics and Best Practices for the Web,\" "
    "Chrome Developers Documentation, 2024.",
    "Chrome Developers, \"Manifest V3: Extensions Platform Documentation,\" Google, 2024. [Online]. "
    "Available: https://developer.chrome.com/docs/extensions/develop",
    "Z. Ji, N. Lee, R. Frieske, T. Yu, D. Su, Y. Xu, et al., \"Survey of Hallucination in Natural "
    "Language Generation,\" ACM Computing Surveys, vol. 55, no. 12, pp. 1-38, 2023.",
    "WebAIM, \"The WebAIM Million: An Annual Accessibility Analysis of the Top 1,000,000 Home Pages,\" "
    "Utah State University, 2024.",
    "A. Alshayban, I. Ahmed, and S. Malek, \"Accessibility Issues in Android Apps: State of Affairs, "
    "Sentiments, and Ways Forward,\" in Proc. 42nd International Conference on Software Engineering "
    "(ICSE), pp. 1323-1334, 2020.",
    "J. Chen, C. Chen, Z. Xing, X. Xu, L. Zhu, G. Li, and J. Wang, \"Unblind Your Apps: Predicting "
    "Natural-Language Labels for Mobile GUI Components by Deep Learning,\" in Proc. 42nd International "
    "Conference on Software Engineering (ICSE), pp. 322-334, 2020.",
    "Z. Liu, C. Chen, J. Wang, Y. Huang, J. Hu, and Q. Wang, \"Owl Eyes: Spotting UI Display Issues via "
    "Visual Understanding,\" in Proc. 35th IEEE/ACM International Conference on Automated Software "
    "Engineering (ASE), pp. 398-409, 2020.",
    "Mozilla, \"Mozilla Public License Version 2.0,\" 2012. [Online]. Available: "
    "https://www.mozilla.org/MPL/2.0/",
    "Encode, \"Starlette: The Little ASGI Framework That Shines,\" 2024. [Online]. Available: "
    "https://www.starlette.io/",
]

APPENDIX_2_STEPS = [
    ("STEP 1", "Install AURA from the Microsoft Edge Add-ons store, or load the extension folder "
               "unpacked from edge://extensions with Developer mode enabled."),
    ("STEP 2", "Open any ordinary web page. Browser pages such as edge://extensions cannot be scanned, "
               "which the panel states if one is open."),
    ("STEP 3", "Click the AURA icon in the browser toolbar on that tab. This grants access to that tab "
               "only and opens the side panel. The connection pill shows the service status."),
    ("STEP 4", "Open the AI provider panel, choose Groq or Gemini - both marked 'free tier' - and paste "
               "your own API key. The key is stored in the extension and is sent only to that provider. "
               "Leaving Mock AI selected runs the scan with no AI request at all."),
    ("STEP 5", "Click Scan current page. The step list reports each stage: reading the page structure, "
               "the accessibility scan, capturing the page, preparing the evidence, asking the provider "
               "from the browser, and verifying every claim against the evidence."),
    ("STEP 6", "Review the findings. Each shows its severity, category and verdict - Confirmed problem, "
               "Potential problem or Needs review - with a one-sentence statement of the problem."),
    ("STEP 7", "Select a finding and use Highlight to mark the element in the live page, Screenshot to "
               "see that part of the capture with the element outlined, Explain for a plain-language "
               "account, or Ask AURA to ask a question about it."),
]
