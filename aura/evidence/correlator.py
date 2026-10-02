import re
from typing import List, Dict, Any, Tuple, Optional
from aura.findings.models import AURAFinding, FindingSource, FindingVerificationStatus
from aura.utils.logger import logger


def normalize_target_selector(selector: str, target_identity: Optional[Dict[str, Any]] = None) -> str:
    """
    Normalizes equivalent selectors (e.g. img.logo, header img, #logo) into a stable canonical target.
    """
    # 1. If target_identity has explicit element id, use it directly
    if target_identity and isinstance(target_identity, dict) and target_identity.get("id"):
        return f"#{target_identity['id']}"

    if not selector:
        return "window / document"
    
    clean_sel = selector.strip().lower()

    # 2. Extract last node component of descendant selector path
    parts = clean_sel.split(">")
    last_part = parts[-1].strip()
    sub_parts = last_part.split(" ")
    last_sub = sub_parts[-1].strip()

    # 3. Check for ID on the target element itself first
    id_match = re.search(r'#([a-zA-Z0-9_\-]+)', last_sub)
    if id_match:
        return f"#{id_match.group(1)}"

    # 4. Fallback: check for ID anywhere in selector path
    id_match_any = re.search(r'#([a-zA-Z0-9_\-]+)', clean_sel)
    if id_match_any:
        return f"#{id_match_any.group(1)}"

    if last_sub:
        return last_sub
    return clean_sel


class EvidenceCorrelator:
    """
    Canonical Finding Correlation Layer matching AI, axe-core, and Runtime findings
    targeting identical canonical targets and normalized rules into unified Canonical Findings.
    """

    @classmethod
    def correlate_and_deduplicate(cls, findings: List[AURAFinding]) -> List[AURAFinding]:
        """
        Correlates multi-source findings into unified Canonical Findings with clean sequential IDs (F-001, F-002...).
        """
        seen_keys: Dict[str, AURAFinding] = {}
        unique_findings: List[AURAFinding] = []

        from aura.agent.analyzer_agent import normalize_rule_type

        SEMANTIC_ACCESSIBILITY_RULES = {
            "image-alt", "image_alt", "button-name", "button_name", "color-contrast", "color_contrast",
            "label", "landmark-one-main", "landmark_one_main", "bad_links", "missing_alt", "image_alt_missing", "unlabelled_button"
        }

        for f in findings:
            raw_sel = ""
            if f.affected_element and f.affected_element.selector:
                raw_sel = f.affected_element.selector
            elif f.raw_target:
                raw_sel = f.raw_target

            canonical_tgt = normalize_target_selector(raw_sel, f.target_identity)
            f.raw_target = raw_sel or "Element"
            f.canonical_target = canonical_tgt

            raw_rule = f.normalized_rule or f.raw_rule or f.title
            canonical_rule = normalize_rule_type(raw_rule)
            f.normalized_rule = canonical_rule

            # Key for correlation: (rule, canonical_target)
            if canonical_rule in SEMANTIC_ACCESSIBILITY_RULES:
                key = f"SEMANTIC:{canonical_rule}:{canonical_tgt}" if canonical_tgt and canonical_tgt != "element" else f"SEMANTIC:{canonical_rule}"
            else:
                key = f"{f.category.value}:{canonical_rule}:{canonical_tgt}" if canonical_tgt and canonical_tgt != "element" else f"{f.category.value}:{canonical_rule}"

            # Two different runtime events (e.g. two distinct console errors on 'window') are two issues;
            # only a repeat of the same event text is the same observation.
            if f.source == FindingSource.RUNTIME and (canonical_tgt in ("window", "network") or canonical_tgt.startswith("http")):
                key = f"{key}:{(f.description or '').strip().lower()}"

            if key in seen_keys:
                existing = seen_keys[key]
                logger.info(f"EvidenceCorrelator correlated finding '{f.title}' ({f.source.value}) with '{existing.title}' ({existing.source.value})")
                
                # Merge sources
                src_val = f.source.value if hasattr(f.source, "value") else str(f.source)
                if src_val not in existing.sources:
                    existing.sources.append(src_val)
                for s in f.sources:
                    if s not in existing.sources:
                        existing.sources.append(s)

                # Merge evidence sources, flags, evidence_ids, candidate_ids
                for src in f.evidence.sources:
                    if src not in existing.evidence.sources:
                        existing.evidence.sources.append(src)
                
                for flag_k, flag_v in f.evidence.flags.items():
                    if flag_v:
                        existing.evidence.flags[flag_k] = True

                for eid in f.evidence_ids:
                    if eid not in existing.evidence_ids:
                        existing.evidence_ids.append(eid)

                if f.candidate_id and f.candidate_id not in existing.candidate_ids:
                    existing.candidate_ids.append(f.candidate_id)
                for cid in f.candidate_ids:
                    if cid not in existing.candidate_ids:
                        existing.candidate_ids.append(cid)

                # Cross-source verification confirmation
                source_strings = [s.lower() for s in existing.sources]
                if "axe-core" in source_strings or "axe" in source_strings or "runtime" in source_strings:
                    if "ai" in source_strings or "AI" in existing.sources:
                        existing.verification_status = FindingVerificationStatus.CONFIRMED
                        existing.verification_score = 1.0
            else:
                src_val = f.source.value if hasattr(f.source, "value") else str(f.source)
                if src_val not in f.sources:
                    f.sources.append(src_val)
                if f.candidate_id and f.candidate_id not in f.candidate_ids:
                    f.candidate_ids.append(f.candidate_id)

                seen_keys[key] = f
                unique_findings.append(f)

        # Re-assign clean sequential Canonical Finding IDs (F-001, F-002...)
        for f_idx, canonical_f in enumerate(unique_findings, start=1):
            canonical_f.id = f"F-{f_idx:03d}"

        return unique_findings

