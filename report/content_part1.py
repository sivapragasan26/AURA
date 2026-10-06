"""
Report content, part 1: front matter and Chapters 1-3.

Every factual claim here is one that can be reproduced from the repository or from a measurement
recorded in report/measurements.json. Nothing in this file is an estimate dressed as a result.
"""

META = {
    "title": "AURA: AN AI-POWERED BROWSER EXTENSION FOR UI, UX AND ACCESSIBILITY AUDITING",
    "title_short": "AURA",
    "report_kind": "PROJECT REPORT",
    "students": [
        ("VIJAYARAGHAVAN.K", "23TN0038"),
        ("PORSEZHIAN.N", "23TN0064"),
        ("SIVAPRAGASAN.V", "23TN0091"),
        ("YUVANSHANKAR.B", "23TN0112"),
    ],
    "guide": "Mr. R. RAJ BHARATH",
    "guide_title": "Head of the Department",
    "department": "Department of Artificial Intelligence and Machine Learning",
    "department_short": "Department of AI&ML",
    "degree": "BACHELOR OF TECHNOLOGY",
    "college": "MANAKULA VINAYAGAR INSTITUTE OF TECHNOLOGY,",
    "college_place": "KALITHEERTHALKUPPAM, PONDICHERRY",
    "university": "PONDICHERRY UNIVERSITY, INDIA.",
    "month_year": "OCTOBER 2026",
    "academic_year": "2026 - 2027",
}

ABSTRACT = [
    "The \"AURA: An AI-Powered Browser Extension for UI, UX and Accessibility Auditing\" project "
    "addresses a problem that automated web quality tools have not solved: the tools that can be trusted "
    "are narrow, and the tools that are broad cannot be trusted. Rule-based engines such as axe-core "
    "detect only what a rule can express, which leaves the majority of interface defects invisible to "
    "them. Large language models asked to review a screenshot will describe hierarchy, emphasis and "
    "confusion fluently, but they also describe problems the page does not have, and they offer the "
    "developer no way to tell the two apart. AURA is built on the principle that AI proposes and "
    "evidence decides.",

    "AURA runs as a browser side panel. When the user presses Scan, it collects evidence from that one "
    "tab: the rendered DOM with geometry and computed styles, accessibility violations from axe-core "
    "executed inside the page, runtime errors and failed network requests captured during the scan, and "
    "a screenshot. A multimodal model is then shown a focused evidence packet and asked what is wrong "
    "with the page. Its answer is treated as a set of candidate findings and nothing more. Each "
    "candidate is independently re-checked against the same evidence by a verification engine that the "
    "model cannot influence: the claimed element must exist, its measured geometry and computed style "
    "must support the claim, and a claim the evidence contradicts is rejected before the user ever sees "
    "it. A materiality gate then separates genuine defects from matters of preference, and every "
    "surviving finding carries a verdict of CONFIRMED, LIKELY or UNCERTAIN together with the evidence "
    "that produced it.",

    "The system is deployed in two parts. The extension is published through the Microsoft Edge Add-ons "
    "store and runs in any Chromium browser; the verification engine is a Python service deployed "
    "publicly on Render. The AI call does not happen on that service. The browser calls the provider "
    "the user chose, with the user's own API key, so that the service never holds a credential "
    "belonging to any user; screenshots never leave the browser at all, and nothing is written to disk "
    "on the server. These are not claims made in prose but properties enforced by the code and asserted "
    "by the test suite.",

    "The system was evaluated against a purpose-built benchmark of five consolidated test suites "
    "containing thirty-one deliberately seeded interface defects, with the ground truth held in the "
    "pages themselves and read only after an audit completes, so that it can never reach the model or "
    "the verifier. Results, methodology and the limits of the measurement are reported in Chapter 5. "
    "The complete system comprises 15,180 lines of engine code, 3,470 lines of extension code and "
    "11,942 lines of test code, with 571 automated tests and five browser-driven end-to-end suites that "
    "exercise the real, unmodified extension in a real browser.",
]

ACKNOWLEDGEMENT = [
    "We express our deep sense of gratitude to Theiva Thiru. N. Kesavan, Founder, Shri. M. Dhanasekaran, "
    "Chairman & Managing Director, Shri. S. V. Sugumaran, Vice-Chairman and Dr. K. Gowtham "
    "Narayanasamy Secretary of Sri Manakula Vinayagar Educational Trust, Puducherry for providing "
    "necessary facilities to successfully complete our project and report works.",
    "We express our sincere thanks to our beloved Principal Dr. S. Malarkkan for having provided "
    "necessary facilities and encouragement for successful completion of this project work.",
    "We express our sincere thanks to Mr. R. Raj Bharath, Head of the Department, Department of "
    "Artificial Intelligence and Machine Learning, for his support in making necessary arrangements for "
    "the conduction of Project and also for guiding us to execute our project successfully.",
    "We express our sincere thanks to Mr. R. Raj Bharath, Head of the Department, Department of "
    "Artificial Intelligence and Machine Learning for his consistent reviews which motivated us in "
    "completing the project.",
    "We thank all our department faculty members, non-teaching staff and my friends from Artificial "
    "Intelligence and Machine Learning department for helping us to complete the document successfully "
    "on time.",
    "We would like to express our eternal gratitude to our parents for the sacrifices they made for "
    "educating and preparing us for our future and their everlasting love and support. We thank the "
    "Almighty for blessing us with such wonderful people and for being with us always.",
]

SYMBOLS = [
    ("TP", "True Positives - seeded defects correctly detected"),
    ("FP", "False Positives - findings reported that are not seeded defects"),
    ("FN", "False Negatives - seeded defects the system did not detect"),
    ("P", "Precision, TP / (TP + FP)"),
    ("R", "Recall, TP / (TP + FN)"),
    ("F1", "Harmonic mean of precision and recall"),
    ("n", "Number of elements examined in a scan"),
    ("t", "Elapsed time of a scan, in seconds"),
]

ABBREVIATIONS = [
    ("AI", "Artificial Intelligence"),
    ("API", "Application Programming Interface"),
    ("ARIA", "Accessible Rich Internet Applications"),
    ("AURA", "Autonomous UI/UX Runtime Assurance"),
    ("CDP", "Chrome DevTools Protocol"),
    ("CORS", "Cross-Origin Resource Sharing"),
    ("CSS", "Cascading Style Sheets"),
    ("CSP", "Content Security Policy"),
    ("DOM", "Document Object Model"),
    ("E2E", "End to End"),
    ("F1", "F1 Score"),
    ("HTML", "HyperText Markup Language"),
    ("HTTP", "HyperText Transfer Protocol"),
    ("JSON", "JavaScript Object Notation"),
    ("LLM", "Large Language Model"),
    ("ML", "Machine Learning"),
    ("MPL", "Mozilla Public License"),
    ("MV3", "Manifest Version 3"),
    ("OTPM", "Output Tokens Per Minute"),
    ("REST", "Representational State Transfer"),
    ("RPM", "Requests Per Minute"),
    ("SPA", "Single Page Application"),
    ("TPM", "Tokens Per Minute"),
    ("UI", "User Interface"),
    ("URL", "Uniform Resource Locator"),
    ("UX", "User Experience"),
    ("VLM", "Vision Language Model"),
    ("WCAG", "Web Content Accessibility Guidelines"),
]

CHAPTER_1 = {
    "number": 1, "title": "INTRODUCTION",
    "sections": [
        {"number": "1.1", "title": "OVERVIEW", "blocks": [
            {"p": "Every web interface carries defects that its own developers cannot see. Some are "
                  "formal violations of accessibility standards: an image without a text alternative, a "
                  "control without an accessible name, text that fails contrast requirements. Others are "
                  "failures of design judgement that no standard describes: a destructive action styled "
                  "more prominently than the action a user actually wants, a form whose error messages "
                  "explain nothing, a layout that collapses on a narrow screen. Both kinds cost real "
                  "users real time, and both are routinely shipped."},
            {"p": "The tools available to a developer divide cleanly along that line. Rule-based "
                  "accessibility engines such as axe-core are deterministic and trustworthy: given the "
                  "same page they produce the same result, and every result can be traced to a published "
                  "rule. They are also narrow by construction. A rule can test whether an image has an "
                  "alt attribute; no rule can test whether the page's visual hierarchy leads a user "
                  "towards the wrong button."},
            {"p": "The arrival of capable multimodal language models suggested an obvious answer: show "
                  "the model a screenshot and ask it what is wrong. In practice this produces fluent, "
                  "confident, and frequently incorrect output. The model describes problems the page "
                  "does not have, attributes them to elements that do not exist, and offers no way for "
                  "the reader to distinguish a real observation from an invented one. A developer who "
                  "must verify every suggestion by hand has not been helped; they have been given more "
                  "work."},
            {"p": "AURA - Autonomous UI/UX Runtime Assurance - is built on the position that both halves "
                  "are necessary and neither is sufficient. The model is used for what it is good at: "
                  "looking at a rendered page and describing what seems wrong. Its output is then "
                  "treated as a hypothesis to be tested, not a result to be displayed. An independent "
                  "verification engine re-checks every claim against the measured evidence collected "
                  "from the page itself, and a claim that the evidence does not support is discarded "
                  "before the user sees it. What reaches the developer is the subset of the model's "
                  "observations that the page itself can be shown to support."},
            {"p": "The system runs where the page runs. AURA is a browser side panel that audits the tab "
                  "the user is already looking at, including pages behind a login, pages on localhost, "
                  "and staging environments that no external crawler can reach. It collects evidence in "
                  "that tab only, after an explicit click, and never watches pages in the background."},
            {"figure": {"file": "fig_1_1_concept.png", "number": "1.1",
                        "caption": "Illustration of evidence-verified page auditing"}},
        ]},
        {"number": "1.2", "title": "TECHNOLOGY", "blocks": [
            {"p": "AURA combines browser extension technology, a server-side analysis engine and "
                  "multimodal language models. The division of work between them is deliberate: the "
                  "browser is the only place that can see the rendered page and the only place the "
                  "user's API key should live, while the engine is the place where a claim can be "
                  "checked against evidence without the model being able to influence the outcome."},
            {"table": {"number": "1.1", "caption": "Core technologies and their role in AURA",
                       "headers": ["Technology", "Role in AURA"],
                       "widths": [3200, 5800],
                       "rows": [
                           ["Chrome Manifest V3 extension", "The side panel interface, evidence collection in the active tab, and the AI call itself. Uses activeTab so no page can be read without a user gesture."],
                           ["axe-core 4.8.2", "Executed inside the scanned page to produce deterministic accessibility violations that require no model at all."],
                           ["Python with Starlette and Uvicorn", "The analysis engine and its HTTP API: evidence validation, prompt construction, verification, materiality gating and scoring."],
                           ["Pydantic", "Schema validation of the evidence bundle and of the model's response, so malformed input is refused rather than misinterpreted."],
                           ["Multimodal LLMs (Groq, Gemini, OpenAI, Anthropic)", "Proposes candidate findings from the evidence packet and a screenshot. Interchangeable; the user chooses and supplies the key."],
                           ["Playwright", "Drives a controlled browser for the benchmark suites, independent of the extension path."],
                           ["Chrome DevTools Protocol", "Drives the real, unmodified extension in a real browser for end-to-end testing."],
                           ["Docker and Render", "Containerises and hosts the public analysis service."],
                       ]}},
            {"p": "The engine and the extension are developed as one system but deployed separately. The "
                  "extension is distributed through a browser extension store; the engine is a container "
                  "that holds no state between scans and writes nothing to disk."},
        ]},
        {"number": "1.3", "title": "CHALLENGES", "blocks": [
            {"p": "Four problems shaped the design, and each of them rules out an otherwise obvious "
                  "approach."},
            {"bullets": [
                "Hallucination. A language model asked to critique an interface will produce confident "
                "statements about elements that are not present and problems that do not exist. Any "
                "system that displays model output directly inherits this, and no amount of prompt "
                "engineering removes it.",
                "Absence of ground truth at run time. When auditing a stranger's page there is no answer "
                "sheet. The system cannot know what the defects are; it can only determine whether a "
                "proposed defect is consistent with what the page demonstrably contains.",
                "Custody of credentials. A hosted service that performs the AI call must hold the user's "
                "API key, which makes it a target and makes every user dependent on the operator's "
                "discretion. A service holding many users' keys in one process is a cross-tenant "
                "credential leak waiting to happen.",
                "Privacy of page content. An audit necessarily examines what is on the screen, which may "
                "include personal data. Any part of that which leaves the user's machine must be "
                "justified, minimised and disclosed.",
            ]},
            {"p": "AURA's answers to these are, respectively: independent verification against measured "
                  "evidence; a benchmark whose ground truth is isolated from the system under test; an "
                  "architecture in which the browser makes the AI call with the user's own key; and a "
                  "service that receives no screenshots, writes nothing to disk and keeps no page "
                  "address or title in its logs."},
        ]},
        {"number": "1.4", "title": "MOTIVATION", "blocks": [
            {"p": "Accessibility failures on the web are not marginal. Automated analyses of the most "
                  "visited home pages consistently find detectable violations on the overwhelming "
                  "majority of them, and those are only the failures a rule can detect. The defects that "
                  "rules cannot express - unclear hierarchy, misleading emphasis, confusing forms - are "
                  "neither measured nor fixed, because no affordable tool reports them in a form a "
                  "developer can act on with confidence."},
            {"p": "The motivation for AURA is therefore not to replace either kind of tool but to make "
                  "the broader kind trustworthy enough to use. A finding that a developer must "
                  "independently confirm has negative value: it consumes attention and returns "
                  "uncertainty. A finding that arrives with the evidence that supports it, an honest "
                  "statement of confidence, and the ability to highlight the element in question, can be "
                  "acted on immediately."},
            {"p": "A secondary motivation is accessibility of the tool itself. Commercial auditing "
                  "platforms are priced for organisations. AURA is free, requires no account, and works "
                  "with free-tier API keys from providers the user chooses, so that a student or an "
                  "independent developer can run the same audit as a company."},
        ]},
        {"number": "1.5", "title": "ORGANIZATION OF THE REPORT", "blocks": [
            {"p": "Chapter 1 (Introduction): Establishes the context, the technologies used, the "
                  "challenges that shaped the design and the motivation for the work."},
            {"p": "Chapter 2 (Literature Survey): Reviews rule-based accessibility engines, the "
                  "application of language and vision-language models to interface evaluation, and the "
                  "literature on hallucination and trust, identifying the research gap this project "
                  "addresses."},
            {"p": "Chapter 3 (Existing Work): Analyses the two existing families of tools in detail, "
                  "presents the existing system model and sets out the specific demerits that motivate a "
                  "different architecture."},
            {"p": "Chapter 4 (Proposed Algorithm): The core technical chapter. Presents the "
                  "evidence-verification model, the full system architecture, the module structure, and "
                  "the novelty of the approach."},
            {"p": "Chapter 5 (Performance Analysis): Describes the benchmark, its ground-truth isolation, "
                  "and the measured results, including the limits of the measurement."},
            {"p": "Chapter 6 (Conclusion): Summarises the contributions and sets out the scope for future "
                  "work."},
        ]},
    ],
}

CHAPTER_2 = {
    "number": 2, "title": "LITERATURE SURVEY",
    "sections": [
        {"number": "2.1", "title": "RULE-BASED ACCESSIBILITY ENGINES", "blocks": [
            {"p": "The dominant approach to automated web quality assessment is the deterministic rule "
                  "engine. axe-core, maintained by Deque Systems, is the most widely deployed example "
                  "and underlies the accessibility panels of major browser developer tools. It evaluates "
                  "a rendered document against a library of rules derived from the Web Content "
                  "Accessibility Guidelines and reports violations with the offending node and the rule "
                  "that failed [1], [2]."},
            {"p": "The strength of this approach is that it is reproducible and explainable. A violation "
                  "is traceable to a published rule and a specific element, which is what makes such "
                  "output safe to put in front of a developer. AURA uses axe-core directly for exactly "
                  "this reason, rather than attempting to replicate its judgements with a model."},
        ]},
        {"number": "2.2", "title": "LIMITATIONS OF RULE-BASED ANALYSIS", "blocks": [
            {"p": "Published analyses of rule-based tooling consistently report that automated rules "
                  "detect only a minority of the accessibility barriers that manual expert review finds. "
                  "The rules are necessarily conservative: a rule that produced false positives would "
                  "destroy the trust that makes the approach useful, so rule authors restrict "
                  "themselves to properties that can be decided mechanically."},
            {"p": "The consequence is a large class of defects that is structurally invisible to this "
                  "family of tools. Whether a call to action is sufficiently prominent, whether an error "
                  "message tells the user what to do, whether two adjacent controls are confusable, "
                  "whether the visual hierarchy of a page matches its informational hierarchy - none of "
                  "these can be expressed as a rule over the DOM, and none of them are reported."},
        ]},
        {"number": "2.3", "title": "LANGUAGE MODELS IN SOFTWARE QUALITY", "blocks": [
            {"p": "Transformer-based language models [4] have been applied across software engineering "
                  "tasks including code review, defect description and test generation. The attraction "
                  "for interface evaluation is that a model trained on a large corpus of human text "
                  "carries an implicit model of what humans find confusing, which is precisely the "
                  "judgement that rule engines cannot encode."},
            {"p": "The literature on applying such models to quality tasks repeatedly identifies the same "
                  "difficulty: output fluency is uncorrelated with output correctness. A model's "
                  "confident phrasing is not evidence, and systems that surface model output without "
                  "independent checking transfer the burden of verification to the user."},
        ]},
        {"number": "2.4", "title": "VISION-LANGUAGE MODELS FOR INTERFACE UNDERSTANDING", "blocks": [
            {"p": "The Vision Transformer [5] established that transformer architectures operating on "
                  "image patches can match or exceed convolutional networks on visual tasks, and "
                  "subsequent multimodal systems [6] accept an image and a text instruction together. "
                  "This makes it possible to ask a model about a rendered interface rather than about "
                  "its markup, which matters because many interface defects are visible only after "
                  "layout and styling have been applied."},
            {"p": "Research on interface understanding has demonstrated models that predict missing "
                  "labels for mobile interface components [13] and that detect display issues from "
                  "rendered screenshots [14]. These establish feasibility, but they are trained for "
                  "specific defect classes and evaluated offline; they do not address a general-purpose "
                  "auditor operating on arbitrary live pages."},
        ]},
        {"number": "2.5", "title": "SURVEY ON AUTOMATED UI AND UX EVALUATION", "blocks": [
            {"p": "Automated usability evaluation has a long history predating machine learning, "
                  "including heuristic evaluation formalised by Nielsen [3], model-based evaluation, and "
                  "metric-driven analysis of layout properties such as alignment, density and balance. "
                  "These methods are systematic but require either expert involvement or a model of the "
                  "specific task the user is attempting."},
            {"p": "What these approaches share with rule engines is that their coverage is bounded by "
                  "what the author of the heuristic or metric anticipated. What they lack is any "
                  "mechanism for evaluating an unanticipated defect on an arbitrary page."},
        ]},
        {"number": "2.6", "title": "DEPLOYMENT CHALLENGES IN BROWSER-BASED AI TOOLS", "blocks": [
            {"p": "Deploying a model-backed tool as a browser extension introduces constraints absent "
                  "from a research prototype. Manifest V3 forbids remotely hosted code, which rules out "
                  "loading a model or an inference client at run time [8]. Extension permissions are "
                  "reviewed and must be minimal, which rules out broad host access. The practical "
                  "consequence is that the extension must ship everything it executes, and must justify "
                  "every origin it contacts."},
            {"p": "A second constraint is economic. Inference costs money, and a free tool cannot absorb "
                  "the cost of every user's scans. The architecture must therefore allow each user to "
                  "supply their own credentials without those credentials being held centrally - a "
                  "requirement that has significant architectural consequences, developed in Chapter 4."},
        ]},
        {"number": "2.7", "title": "HALLUCINATION AND TRUST IN MODEL OUTPUT", "blocks": [
            {"p": "Hallucination - the generation of fluent content unsupported by the input - is a "
                  "well-characterised and persistent property of generative models rather than a defect "
                  "of particular implementations [9]. Surveys of the phenomenon distinguish intrinsic "
                  "hallucination, which contradicts the provided source, from extrinsic hallucination, "
                  "which cannot be verified from it. Both occur in interface critique: a model may "
                  "assert that a button is invisible when the measured geometry shows otherwise, or "
                  "assert a usability problem that the evidence can neither confirm nor refute."},
            {"p": "The literature's mitigations fall into two groups: improving generation through "
                  "grounding and retrieval, and checking output after generation. AURA takes the second "
                  "approach deliberately, because only post-hoc checking can offer the user a guarantee "
                  "about what they are shown rather than a reduction in the probability of error."},
        ]},
        {"number": "2.8", "title": "BENCHMARKS AND GROUND TRUTH FOR INTERFACE DEFECTS", "blocks": [
            {"p": "Evaluating an interface auditor requires pages whose defects are known. Public "
                  "accessibility datasets label conformance failures but not design-level defects, and "
                  "large-scale surveys such as the WebAIM Million [10] measure prevalence rather than "
                  "providing per-page ground truth suitable for scoring a detector."},
            {"p": "The absence of a suitable public benchmark for the broader class of defects is itself "
                  "a finding of this survey, and motivated the construction of the purpose-built "
                  "benchmark described in Chapter 5, in which defects are deliberately seeded and "
                  "recorded, and the record is kept strictly isolated from the system under test."},
        ]},
        {"number": "2.9", "title": "IDENTIFYING THE RESEARCH GAP", "blocks": [
            {"p": "The survey establishes three positions. Rule engines are trustworthy and narrow. "
                  "Model-based reviewers are broad and untrustworthy. Research systems that apply "
                  "vision-language models to interfaces are accurate within a trained defect class but "
                  "are not general-purpose, live, or deployable as an everyday developer tool."},
            {"table": {"number": "2.1", "caption": "Comparative analysis of existing approaches to interface auditing",
                       "headers": ["Approach", "Coverage", "Trustworthiness", "Principal limitation"],
                       "widths": [2300, 1900, 2000, 2800],
                       "rows": [
                           ["Rule engines (axe-core, WAVE)", "Narrow: conformance only", "High: deterministic and traceable", "Cannot express design-level defects"],
                           ["Automated metrics and heuristics", "Medium: anticipated properties", "Medium: depends on metric validity", "Bounded by what the author foresaw"],
                           ["Prompted LLM reviewers", "Broad: any visible defect", "Low: unverified assertions", "Hallucination; no evidence link"],
                           ["Trained defect detectors [13], [14]", "Narrow: trained classes", "High within class", "Offline; not general-purpose or live"],
                           ["AURA (proposed)", "Broad: rule-based and model-proposed", "High: every claim re-checked against evidence", "Depends on evidence being collectible"],
                       ]}},
            {"p": "The gap is therefore not a missing model or a missing rule set. It is the absence of a "
                  "mechanism that allows a broad, model-generated critique to be trusted - a way of "
                  "deciding, automatically and before display, which of the model's statements the page "
                  "itself supports."},
        ]},
        {"number": "2.10", "title": "JUSTIFICATION FOR AN EVIDENCE-VERIFIED ARCHITECTURE", "blocks": [
            {"p": "This project adopts an architecture in which the model's role is explicitly reduced to "
                  "proposing candidates, and authority over what is reported rests with a deterministic "
                  "verification stage that the model cannot influence. The justification is that this is "
                  "the only arrangement in which a guarantee can be offered to the user: not that the "
                  "model is usually right, but that nothing is displayed which the collected evidence "
                  "does not support."},
            {"p": "The approach also degrades well. If the model is unavailable, rate-limited or refuses "
                  "the request, the deterministic findings are still produced and the absence of AI "
                  "analysis is stated explicitly rather than presented as an absence of problems. This "
                  "property - never reporting silence as success - is enforced in the implementation and "
                  "is covered by the test suite."},
        ]},
    ],
}

CHAPTER_3 = {
    "number": 3, "title": "EXISTING WORK",
    "sections": [
        {"number": "3.1", "title": "OVERVIEW", "blocks": [
            {"p": "This chapter examines the systems a developer would actually use today to assess an "
                  "interface, how they are composed, and why their combination still leaves the original "
                  "problem unsolved. The analysis is deliberately concrete: the demerits in Section 3.4 "
                  "are the specific behaviours that the proposed system in Chapter 4 is designed to "
                  "avoid."},
        ]},
        {"number": "3.2", "title": "AUTOMATED AUDIT TOOLS IN WEB DEVELOPMENT", "blocks": [
            {"p": "Three generations of tooling coexist in current practice, and most teams use some "
                  "combination of all three."},
        ]},
        {"number": "3.2.1", "title": "MANUAL REVIEW WORKFLOW", "level": 3, "blocks": [
            {"p": "The baseline remains expert review: a developer, designer or accessibility specialist "
                  "examines the interface, often with a screen reader and a keyboard, and records what "
                  "they find. This is the most capable method available and detects the full range of "
                  "defects, including those no automated system reports."},
            {"p": "It is also slow, expensive, inconsistent between reviewers, and performed rarely. "
                  "Because it is performed rarely, it is performed late, when the cost of change is "
                  "highest. Automation is pursued not because it is better than expert review but "
                  "because expert review does not scale to every page on every change."},
        ]},
        {"number": "3.2.2", "title": "STATIC AND RULE-BASED ANALYSIS", "level": 3, "blocks": [
            {"p": "Rule-based engines evaluate the rendered document against a rule library. In a typical "
                  "deployment, axe-core is injected into the page, traverses the accessibility tree and "
                  "the DOM, and returns violations with their offending nodes. Integration is "
                  "straightforward, execution takes under a second, and results are stable."},
            {"p": "The output is limited to the rules' domain. An audit of a page with a confusing "
                  "checkout flow, an unreadable error message and a destructive button styled as the "
                  "primary action may return no violations at all, because none of those properties is "
                  "expressible as a rule."},
        ]},
        {"number": "3.2.3", "title": "MODEL-BASED REVIEWERS", "level": 3, "blocks": [
            {"p": "The current generation of tools sends a screenshot, and sometimes the markup, to a "
                  "multimodal model with an instruction to review the interface. The model returns prose "
                  "or a list of issues. These tools are easy to build - the entire implementation is a "
                  "prompt - and they are impressive in demonstrations."},
            {"p": "Their failure mode in practice is systematic. Because the model is asked to produce a "
                  "list of problems, it produces a list of problems whether or not the page has them. "
                  "Because the output is not checked, plausible fabrications are indistinguishable from "
                  "real observations. Because nothing anchors a finding to an element, the developer "
                  "cannot even confirm which control is meant. The result is a tool that is entertaining "
                  "once and abandoned."},
        ]},
        {"number": "3.3", "title": "SYSTEM MODEL", "blocks": [
            {"p": "Figure 3.1 presents the existing system model as it stands in current practice: two "
                  "disjoint pipelines that share no information and offer the developer no way to "
                  "reconcile their output. The rule engine produces few findings, all reliable. The "
                  "model-based reviewer produces many findings, of unknown reliability. The developer is "
                  "left to perform the reconciliation manually, which is the task they were trying to "
                  "automate."},
            {"figure": {"file": "fig_3_1_existing.png", "number": "3.1",
                        "caption": "Existing system model"}},
            {"p": "Note in particular what is absent from the model-based path: there is no stage between "
                  "generation and display. Whatever the model asserts is what the user reads. Every "
                  "property of the output - its accuracy, its specificity, its relevance - is a property "
                  "of the model's generation, and nothing downstream can improve it."},
        ]},
        {"number": "3.4", "title": "DEMERITS OF EXISTING APPROACHES", "blocks": [
            {"p": "The following demerits are specific, observable, and each is addressed by a named "
                  "mechanism in Chapter 4."},
            {"bullets": [
                "Unverified assertion. Model output is displayed as produced. A statement that an element "
                "is invisible is shown even when the element's measured bounding box and computed "
                "visibility prove otherwise.",
                "No evidence trail. Findings arrive without the data that produced them, so a developer "
                "cannot judge a finding without redoing the analysis by hand.",
                "No confidence signal, or a meaningless one. Where confidence is reported it is the "
                "model's own self-assessment, which is not calibrated and carries no information about "
                "whether the page supports the claim.",
                "Unresolvable targets. Findings refer to elements in prose rather than by a selector that "
                "can be resolved, so the developer cannot reliably locate what is being discussed.",
                "Silence reported as success. When the model fails, is rate-limited or returns nothing, "
                "tools commonly display an empty result, which a user reasonably reads as 'no problems "
                "found'.",
                "Centralised credential custody. Hosted tools hold the user's API key, or bill the user "
                "for the operator's key, making the service a target and the user dependent on it.",
                "Unnecessary data exposure. Screenshots and full page content are routinely uploaded to "
                "a server when the analysis could be performed without the server ever receiving them.",
            ]},
            {"p": "Taken together these demerits explain why model-based interface review has not "
                  "displaced manual review despite the capability of the underlying models. The "
                  "capability is not the constraint; the absence of verification is."},
        ]},
    ],
}
