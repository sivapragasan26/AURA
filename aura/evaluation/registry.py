import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from aura.utils.logger import logger


class GroundTruthRegistry:
    """
    Authoritative Single Source of Truth for loading, validating, and managing
    Test Lab Ground Truth specifications across all benchmark suites.
    
    Guarantees:
    1. Every intentional defect has exactly one unique ground_truth_id (e.g. GT-05-001).
    2. Enforces unique ground_truth_id uniqueness per suite and across the benchmark registry.
    3. Ground Truth specifications are strictly isolated from AI prompts and verifier engines.
    """

    @classmethod
    def load_suite_ground_truth(cls, site_dir: Path) -> Dict[str, Any]:
        """
        Loads machine-readable embedded HTML script tag (#aura-ground-truth) or ground_truth.json
        for a test lab suite directory. Enforces schema validation and ground_truth_id uniqueness.
        """
        site_path = Path(site_dir)
        if not site_path.is_absolute():
            from aura.config import settings
            site_path = (settings.BASE_DIR / site_path).resolve()

        raw_data: Optional[Dict[str, Any]] = None

        # 1. Try ground_truth.json first if available (canonical json source)
        gt_file = site_path / "ground_truth.json"
        html_file = site_path / "index.html"

        if gt_file.exists():
            try:
                with open(gt_file, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to parse ground_truth.json in {site_path}: {e}")

        # 2. Fallback to embedded HTML script tag if ground_truth.json not found or invalid
        if not raw_data and html_file.exists():
            try:
                with open(html_file, "r", encoding="utf-8") as f:
                    content = f.read()
                match = re.search(
                    r'<script[^>]*id=["\']aura-ground-truth["\'][^>]*>(.*?)</script>',
                    content,
                    re.DOTALL | re.IGNORECASE
                )
                if match:
                    raw_data = json.loads(match.group(1).strip())
            except Exception as e:
                logger.warning(f"Failed to parse embedded ground truth script tag in {html_file}: {e}")

        if not raw_data:
            return {
                "suite_id": site_path.name,
                "name": site_path.name,
                "version": "0.4.4.1",
                "expected_findings": [],
                "unique_ground_truth_ids": [],
                "expected_defects_count": 0,
                "registry_status": "EMPTY"
            }

        suite_id = raw_data.get("suite_id") or site_path.name
        raw_findings = raw_data.get("expected_findings") or []

        validated_findings: List[Dict[str, Any]] = []
        seen_gt_ids = set()

        for idx, item in enumerate(raw_findings):
            if not isinstance(item, dict):
                continue

            # Standardize ground_truth_id
            gt_id = (item.get("ground_truth_id") or 
                     item.get("id") or 
                     item.get("gt_id") or 
                     f"GT-{suite_id[:2].upper()}-{idx+1:03d}")

            if gt_id in seen_gt_ids:
                logger.warning(f"Duplicate ground_truth_id '{gt_id}' rejected in suite '{suite_id}'")
                continue

            seen_gt_ids.add(gt_id)

            norm_rule = (item.get("normalized_rule") or 
                         item.get("rule") or 
                         item.get("rule_type") or 
                         item.get("type") or 
                         "defect").lower().strip()

            validated_item = {
                "ground_truth_id": gt_id,
                "suite_id": suite_id,
                "category": str(item.get("category") or "UX").upper().strip(),
                "normalized_rule": norm_rule,
                # Keep the GT's own 'rule' label: it is an equivalent identifier for the same defect
                "rule": str(item.get("rule") or norm_rule).lower().strip(),
                "severity": str(item.get("severity") or "MEDIUM").upper().strip(),
                "target": str(item.get("target") or item.get("selector") or "").strip(),
                "description": item.get("description") or f"Expected {norm_rule} defect",
                "verification_method": item.get("verification_method") or "automated",
                "expected_evidence": item.get("expected_evidence") or [],
                "allowed_sources": item.get("allowed_sources") or ["AI", "AXE_CORE", "RUNTIME"]
            }
            validated_findings.append(validated_item)

        return {
            "suite_id": suite_id,
            "name": raw_data.get("name") or suite_id,
            "description": raw_data.get("description") or "",
            "version": raw_data.get("version", "0.4.4.1"),
            "expected_findings": validated_findings,
            "unique_ground_truth_ids": list(seen_gt_ids),
            "expected_defects_count": len(validated_findings),
            "registry_status": "VALIDATED"
        }

