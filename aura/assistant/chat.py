"""
"Ask AURA": a contextual assistant scoped to ONE audit, and — when the user has a finding open — to ONE
finding inside it.

Context isolation is the rule this module exists to enforce. When a finding is selected the context contains
THAT finding and nothing else: no sibling findings, no rejected candidates, no page-wide finding list. A
question AURA cannot answer from the selected finding's own evidence is answered with "not enough evidence
in this finding", never by substituting a different finding.

The context never contains ground truth, benchmark data, raw screenshots or credentials. Answers may cite
only the finding under discussion. If the provider is unavailable the assistant says so; it never fabricates.
"""
import json
import re
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from aura.agent.provider_status import ProviderStateStore, run_preflight
from aura.security.credentials import sanitize_provider_error

MAX_QUESTION_CHARS = 500
MAX_CONTEXT_FINDINGS = 25
ANSWER_CACHE_SIZE = 128

NOT_IN_THIS_FINDING = "AURA doesn't have enough evidence in this finding to answer that."

# Keys that must never appear anywhere in an assistant context (benchmark / ground-truth data)
FORBIDDEN_CONTEXT_KEYS = {"evaluation", "ground_truth", "ground_truth_id", "expected_findings", "true_positives",
                          "false_positives", "false_negatives", "precision", "recall", "f1", "benchmark",
                          "screenshot_png_base64", "api_key"}

_TONE = """Tone & Style:
- Speak naturally and simply, like an expert colleague. Lead with the conclusion.
- Avoid technical jargon (rule IDs, ARIA, DOM selectors, CSS paths, WCAG) unless the user asks for technical detail.
- Distinguish established browser facts from design judgement. "Confirmed problem" is measured; "Potential
  problem" and "Advisory" are judgements that the evidence could not settle.
- If asked whether AURA saw something in the screenshot, answer from `has_visual_evidence` only. If it is
  false, say plainly that AURA observed this through page structure and accessibility inspection, not from a
  rendered screenshot.
- Never invent files, line numbers, measurements or facts that are not in the context. Never mention
  benchmarks or ground truth.
- Be concise (around 80-120 words)."""

# Used when the user has a finding open. The context holds ONLY that finding.
ASK_FINDING_PROMPT = """You are "Ask AURA", explaining ONE specific finding to a website owner or developer.

You may ONLY discuss the finding below. It is the only finding you can see, and the only one the user is
asking about. You must not describe, compare with, or mention any other issue on this page — not even if the
question seems to be about something else.

You may also answer related general questions that arise from this finding — how this kind of problem is
usually fixed, what a good version looks like, what to watch out for, what a reasonable heading or label
might be given the page's title and address. Use your own expertise for those, and the page context below.

Keep the two kinds of answer clearly apart:
- A fact AURA measured: state it plainly.
- General advice or a suggestion of your own: mark it as such ("AURA didn't measure this, but…",
  "As a general rule…", "A sensible choice here would be…"). Never present a suggestion as something
  AURA found on the page, and never invent a measurement, a count, or an element that is not listed below.

Only when the question has nothing to do with this finding — it is about a different issue on the page, or
about something no amount of general knowledge could ground — set "answer" to exactly:
"{not_in_finding}"
and list what is missing in "evidence_gaps". Never answer by describing a different finding.

If the user disagrees with the finding (for example "but the page already looks fine"), address THIS
finding's evidence directly and honestly: explain what AURA measured, and say plainly when the finding is a
judgement rather than a measured fact.

{tone}

Return ONLY JSON: {{"answer": "...", "cited_finding_ids": ["{finding_id}"], "evidence_gaps": ["..."]}}

PAGE:
```json
{page}
```

THE FINDING UNDER DISCUSSION (id {finding_id}) — the only issue you may talk about:
```json
{finding}
```

USER QUESTION: {question}
"""

# Used only when no finding is open: a question about the audit as a whole.
ASK_AUDIT_PROMPT = """You are "Ask AURA", explaining one page audit to a website owner or developer.
Answer the user's question using ONLY the recorded audit context below.

{tone}

Return ONLY JSON: {{"answer": "...", "cited_finding_ids": ["F-001"], "evidence_gaps": ["..."]}}

AUDIT CONTEXT:
```json
{context}
```

USER QUESTION: {question}
"""


# ---------------------------------------------------------------------------------------------------
# Answer cache: audit_id + finding_id + normalized question. Never keyed on the question alone, so the
# same wording asked on two different findings can never return the other finding's answer.
# ---------------------------------------------------------------------------------------------------
_cache: "OrderedDict[Tuple[str, str, str], Dict[str, Any]]" = OrderedDict()
_cache_lock = threading.Lock()


def normalize_question(question: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (question or "").lower()).strip()


def cache_key(audit_id: Optional[str], finding_id: Optional[str], question: str) -> Tuple[str, str, str]:
    return (str(audit_id or ""), str(finding_id or ""), normalize_question(question))


def cache_get(key: Tuple[str, str, str]) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        hit = _cache.get(key)
        if hit is None:
            return None
        _cache.move_to_end(key)
        return dict(hit)


def cache_put(key: Tuple[str, str, str], value: Dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = dict(value)
        _cache.move_to_end(key)
        while len(_cache) > ANSWER_CACHE_SIZE:
            _cache.popitem(last=False)


def cache_clear() -> None:
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------------------------------
def compact_finding(f: Dict[str, Any]) -> Dict[str, Any]:
    """The allow-listed, ground-truth-free view of one finding."""
    h = f.get("human") or {}
    ev = f.get("evidence") or {}
    rep = f.get("reproduction") or {}
    conc = f.get("conclusion") or {}
    why_reported = h.get("why_aura_reported_this") or f.get("why_aura_reported_this") or {}
    target = f.get("target") or {}
    return {
        "id": f["id"],
        "title": h.get("title") or f.get("title"),
        "category": f.get("category"),
        "severity": f.get("severity"),
        "status": h.get("status_label") or f.get("status") or f.get("verification_status"),
        "confidence": h.get("confidence_label") or f.get("confidence_label"),
        "verification_status": f.get("verification_status"),
        "verification_note": f.get("verification_note"),
        "origin": f.get("origin"),
        "ai_contribution_type": f.get("ai_contribution_type"),
        "what_is_wrong": h.get("summary") or f.get("summary") or f.get("description"),
        "why_it_matters": h.get("why_it_matters") or f.get("why_it_matters"),
        "what_to_do": h.get("what_to_do") or f.get("recommendation"),
        "where": h.get("location") or f.get("location_description") or target.get("description"),
        "evidence_sources": (ev.get("sources") or [])[:4],
        "evidence_provenance": ev.get("types", []),
        "has_visual_evidence": bool(ev.get("has_visual_evidence")),
        "evidence_evaluated": (why_reported.get("evaluated_sources") or [])[:6],
        "reproduction_state": rep.get("state"),
        "reproduction_action": rep.get("action_attempted"),
        "safety_boundary": rep.get("safety_boundary"),
        "known_fact": conc.get("known_fact") or h.get("known_fact"),
        "inferred_impact": conc.get("inferred_judgement") or h.get("inferred_judgement"),
        "conclusion_strength": conc.get("strength") or h.get("conclusion_strength"),
        "affected_count": f.get("affected_count"),
        "target_kind": target.get("kind"),
        "target_text": target.get("text"),
    }


def build_finding_context(view: Dict[str, Any], finding: Dict[str, Any]) -> Dict[str, Any]:
    """
    Context for ONE finding. Deliberately contains no other finding.

    The page's own title and address are included: they are what lets a general question such as "what
    might the heading be?" get a useful answer instead of a refusal, without inventing anything.
    """
    ctx = {
        "page": {"url": view.get("page_url"), "title": view.get("title"), "viewport": view.get("viewport"),
                 "scan_summary": view.get("summary")},
        "finding": compact_finding(finding),
    }
    assert_no_forbidden_keys(ctx)
    return ctx


def build_chat_context(view: Dict[str, Any], finding_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Allow-listed, GT-free context for one audit.

    With a finding_id, the context is narrowed to that finding alone: `findings` holds exactly one entry and
    no rejected candidates are included. Without one, the audit-wide context is built.
    """
    if finding_id:
        selected = next((f for f in (view.get("findings") or []) if f.get("id") == finding_id), None)
        if selected is not None:
            ctx = build_finding_context(view, selected)
            return {
                "page": ctx["page"],
                "selected_finding_id": finding_id,
                "findings": [ctx["finding"]],
                "scope": "SINGLE_FINDING",
            }

    ctx = {
        "page": {"url": view.get("page_url"), "title": view.get("title"), "viewport": view.get("viewport")},
        "result_state": view.get("result_state"),
        "ai_analysis": {"state": (view.get("ai") or {}).get("state"), "message": (view.get("ai") or {}).get("message")},
        "scores": {k: v for k, v in (view.get("scores") or {}).items() if k != "note"},
        "severity_counts": view.get("severity_counts"),
        "findings": [compact_finding(f) for f in (view.get("findings") or [])[:MAX_CONTEXT_FINDINGS]],
        "rejected_ai_candidates": [{"title": r.get("title"), "reason": r.get("reason")}
                                   for r in (view.get("rejected_ai_candidates") or [])[:10]],
        "evidence_coverage_notes": (view.get("evidence_coverage") or {}).get("notes", []),
        "scope": "WHOLE_AUDIT",
    }
    assert_no_forbidden_keys(ctx)
    return ctx


def assert_no_forbidden_keys(obj: Any) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in FORBIDDEN_CONTEXT_KEYS:
                raise ValueError(f"Forbidden key in assistant context: {k}")
            assert_no_forbidden_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            assert_no_forbidden_keys(v)


# ---------------------------------------------------------------------------------------------------
# Question intent: the six standard questions are answered from the recorded finding, with 0 AI requests.
# Each intent produces a DIFFERENT answer drawn from a different part of the finding.
# ---------------------------------------------------------------------------------------------------
INTENT_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("SCREENSHOT", re.compile(r"\b(screenshot|did you (actually )?see|see this in|visually (confirm|verif)|"
                              r"from the image|in the picture)\b", re.I)),
    ("IS_CONFIRMED", re.compile(r"\b(is (this|it) (really )?(confirmed|certain|sure|verified|a real)|"
                                r"are you (sure|certain)|how (confident|sure) are you|confirmed\?)", re.I)),
    ("WHY_REPORTED", re.compile(r"\b(why did aura|why was this reported|why aura reported|what did aura (observe|find)|"
                                r"what evidence|how (was|did) (this|you) (get )?verif|how do you know|"
                                r"is this reproducib|how was this (found|detected))\b", re.I)),
    ("HOW_FIX", re.compile(r"\b(how (do|can|should|would) i (fix|solve|resolve|correct|repair)|how to (fix|solve|resolve|correct)|"
                           r"how (do|to) (i )?(sort|address)|what should i do|what to do|what can i do|"
                           r"fix (this|it)|solve (this|it)|resolve (this|it)|recommendation|suggest(ion|ed fix)?)\b", re.I)),
    ("WHY_MATTERS", re.compile(r"\b(why does (this|it) matter|why is (this|it) (a problem|important|an issue|bad)|"
                               r"why it matters|what('s| is) the impact|who does (this|it) affect|so what)\b", re.I)),
    ("WHAT_IS_WRONG", re.compile(r"\b(what('s| is| does this) (wrong|the problem|the issue|this|it)|"
                                 r"what does this mean|explain (this|it)|tell me (about|more)|what happened)\b", re.I)),
]


def classify_question(question: str) -> Optional[str]:
    """The standard question this is, or None when only the model can answer it."""
    for intent, pattern in INTENT_PATTERNS:
        if pattern.search(question or ""):
            return intent
    return None


STATUS_EXPLANATION = {
    "CONFIRMED": "Yes. AURA measured this directly in the browser, so it is a confirmed problem rather than an opinion.",
    "LIKELY": "Not fully. AURA verified the element on the page, but the harm itself could not be measured, so this "
              "is recorded as a potential problem rather than a confirmed one.",
    "UNCERTAIN": "No. AURA could not confirm this with browser evidence, so it is recorded for review rather than as "
                 "a confirmed problem.",
    "REJECTED": "No. Browser evidence contradicted this suggestion, so AURA does not report it as a problem.",
}


def _grounded(answer: str, finding_id: str, gaps: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "state": "OK",
        "answer": answer,
        "cited_finding_ids": [finding_id],
        "evidence_gaps": gaps or [],
        "provider": "evidence_store",
        "model": "grounded_interpretation",
        "answered_from": "RECORDED_EVIDENCE",
        "note": "Answered directly from this finding's recorded evidence. 0 AI requests used.",
    }


def answer_from_finding(intent: str, finding: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One distinct, grounded answer per standard question. None when the finding lacks what it needs."""
    fid = finding["id"]
    h = finding.get("human") or {}
    ev = finding.get("evidence") or {}
    conc = finding.get("conclusion") or {}
    rep = finding.get("reproduction") or {}
    why_reported = h.get("why_aura_reported_this") or finding.get("why_aura_reported_this") or {}

    if intent == "WHAT_IS_WRONG":
        what = h.get("summary") or finding.get("summary") or finding.get("description")
        where = h.get("location") or finding.get("location_description")
        if not what:
            return None
        text = f"In simple terms: {what}"
        if where:
            text += f" This applies to {where}."
        return _grounded(text, fid)

    if intent == "WHY_MATTERS":
        why = h.get("why_it_matters") or finding.get("why_it_matters")
        impact = conc.get("inferred_judgement") or h.get("inferred_judgement")
        if not why:
            return None
        text = f"Why it matters: {why}"
        if impact and impact.strip() != why.strip():
            text += f" In practice: {impact}"
        return _grounded(text, fid)

    if intent == "HOW_FIX":
        fix = h.get("what_to_do") or finding.get("recommendation")
        where = h.get("location") or finding.get("location_description")
        if not fix:
            return None
        text = f"What to do: {fix}"
        if where:
            text += f" Apply it to {where}."
        return _grounded(text, fid)

    if intent == "WHY_REPORTED":
        observation = why_reported.get("observation") or h.get("summary") or finding.get("summary")
        fact = conc.get("known_fact") or h.get("known_fact")
        action = rep.get("action_attempted")
        state = rep.get("state") or h.get("reproduction_state")
        if not (observation or fact):
            return None
        parts = []
        if action:
            parts.append(f"AURA {action[0].lower() + action[1:] if action else ''}".rstrip())
        if fact:
            parts.append(f"What it established: {fact}")
        if observation:
            parts.append(f"That is why this was reported: {observation}")
        if state:
            parts.append(f"Verification state: {state}.")
        return _grounded(" ".join(p for p in parts if p), fid)

    if intent == "IS_CONFIRMED":
        status = (finding.get("verification_status") or "").upper()
        strength = conc.get("strength") or h.get("status_label") or finding.get("status_label")
        explanation = STATUS_EXPLANATION.get(status)
        if not explanation:
            return None
        text = f"{explanation} AURA records this as: {strength}."
        note = finding.get("verification_note")
        if note:
            text += f" Verifier note: {note}"
        return _grounded(text, fid)

    if intent == "SCREENSHOT":
        has_visual = bool(ev.get("has_visual_evidence")) or "VISUAL" in [t.upper() for t in (ev.get("types") or [])]
        if has_visual:
            return _grounded(
                "Yes. This finding was evaluated against the rendered page screenshot that AURA captured during "
                "the scan, so what you see on screen was part of the evidence.", fid)
        return _grounded(
            "No. AURA did not identify this from a rendered screenshot. It was observed through the page's own "
            "structure and accessibility information during the scan.", fid,
            ["Rendered screenshot was not part of this finding's evidence"])

    return None


def _parse_answer(raw: str, valid_ids: set) -> Optional[Dict[str, Any]]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\{[\s\S]*\}", text)
    try:
        data = json.loads(m.group(0) if m else text)
    except (ValueError, AttributeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("answer"), str) or not data["answer"].strip():
        return None
    cited = [c for c in data.get("cited_finding_ids") or [] if isinstance(c, str) and c in valid_ids]
    gaps = [g for g in data.get("evidence_gaps") or [] if isinstance(g, str)][:5]
    return {"answer": data["answer"].strip()[:2000], "cited_finding_ids": cited, "evidence_gaps": gaps}


def ask(provider: Any, view: Dict[str, Any], question: str, finding_id: Optional[str] = None) -> Dict[str, Any]:
    """
    One grounded answer about the selected finding (or, with none selected, about the audit).

    The finding is taken from the request, never from previous state: there is no "last finding" anywhere in
    this module. Standard questions are answered from recorded evidence (0 AI requests).
    """
    question = (question or "").strip()[:MAX_QUESTION_CHARS]
    if not question:
        return {"state": "INVALID_QUESTION", "answer": None, "message": "Ask a question about this audit."}

    findings = view.get("findings") or []
    valid_ids = {f["id"] for f in findings}
    if finding_id and finding_id not in valid_ids:
        finding_id = None

    key = cache_key(view.get("audit_id"), finding_id, question)
    cached = cache_get(key)
    if cached is not None:
        return {**cached, "cached": True}

    selected = next((f for f in findings if f["id"] == finding_id), None) if finding_id else None

    # 1. Standard questions are answered from this finding's own record.
    if selected is not None:
        intent = classify_question(question)
        if intent:
            direct = answer_from_finding(intent, selected)
            if direct is not None:
                cache_put(key, direct)
                return direct

    # 2. Anything else needs the model, with a context holding only what may be discussed.
    provider_key = getattr(provider, "provider_key", "unknown")
    if provider_key in ("mock", "unknown"):
        return {"state": "AI_UNAVAILABLE", "answer": None,
                "message": "Ask AURA requires a real AI provider. Select Groq, Gemini, OpenAI or Anthropic under AI in "
                           "the panel. Explain still works with Mock AI and costs no AI request."}

    preflight = run_preflight(provider, check_remote=False, needs_image=False)
    if preflight.blocked:
        return {"state": "AI_UNAVAILABLE", "answer": None, "preflight_status": preflight.status,
                "message": f"AI provider unavailable ({preflight.status}). No answer was generated."}

    if selected is not None:
        ctx = build_finding_context(view, selected)
        prompt = ASK_FINDING_PROMPT.format(
            not_in_finding=NOT_IN_THIS_FINDING, tone=_TONE, finding_id=finding_id,
            page=json.dumps(ctx["page"], ensure_ascii=False),
            finding=json.dumps(ctx["finding"], ensure_ascii=False), question=question)
        citable = {finding_id}
    else:
        ctx = build_chat_context(view, None)
        prompt = ASK_AUDIT_PROMPT.format(tone=_TONE, context=json.dumps(ctx, ensure_ascii=False), question=question)
        citable = valid_ids

    model = getattr(provider, "model", "default")
    try:
        raw = provider.analyze(prompt=prompt)
    except Exception as e:  # provider failure: report it, never answer from nothing
        ProviderStateStore.record(provider_key, model, getattr(provider, "last_execution_metadata", {}) or {})
        return {"state": "AI_UNAVAILABLE", "answer": None,
                "message": f"The AI provider request failed: {sanitize_provider_error(e)[:300]}"}
    ProviderStateStore.record(provider_key, model, getattr(provider, "last_execution_metadata", {}) or {})
    parsed = _parse_answer(raw, citable)
    if parsed is None:
        return {"state": "AI_RESPONSE_INVALID", "answer": None, "message": "The AI response could not be used."}

    result = {"state": "OK", **parsed, "provider": provider_key, "model": model,
              "answered_from": "SINGLE_FINDING" if selected is not None else "WHOLE_AUDIT",
              "scoped_finding_id": finding_id,
              "note": ("AI-generated answer grounded in this finding's recorded evidence. 1 AI request used."
                       if selected is not None else
                       "AI-generated answer grounded in this audit's findings. 1 AI request used.")}
    cache_put(key, result)
    return result
