"""
Report status manifests for data/processed.

Each tier has its own manifest, processed/{tier}/manifest.json, so runs on
different tiers (or VMs) never overwrite each other's entries. The shared
processed/manifest.json written by older code is read as a fallback only.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Iterable

logger = logging.getLogger(__name__)

TIERS = ("union", "state", "local_body")
MANIFEST_NAME = "manifest.json"


def tier_manifest_path(processed_dir, tier: str) -> Path:
    return Path(processed_dir) / tier / MANIFEST_NAME


def processed_root(path) -> Path:
    """data/processed for either data/processed or one of its tier directories."""
    path = Path(path)
    return path.parent if path.name in TIERS else path


def _read_reports(path: Path) -> Iterable[dict]:
    try:
        return json.loads(path.read_text()).get("reports", [])
    except (OSError, ValueError) as e:
        logger.warning(f"Could not read {path}: {e}")
        return []


def load_report_entries(processed_dir) -> Dict[str, dict]:
    """
    report_id -> manifest entry, from every manifest under processed_dir.

    Tier manifests win over the legacy shared manifest, which may still hold
    entries for reports not processed since the per-tier split.
    """
    root = processed_root(processed_dir)
    entries: Dict[str, dict] = {}
    for path in [root / MANIFEST_NAME] + [tier_manifest_path(root, t) for t in TIERS]:
        if path.exists():
            for report in _read_reports(path):
                if report.get("report_id"):
                    entries[report["report_id"]] = report
    return entries
