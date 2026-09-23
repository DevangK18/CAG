"""
Pattern Loader: Loads enrichment patterns from YAML configuration.

P1-B: Enables pattern externalization for easier maintenance and updates
without code changes.

Usage:
    from src.parsing_pipeline.modules.enrichment.pattern_loader import PatternLoader

    loader = PatternLoader()
    finding_patterns = loader.get_finding_type_patterns()
    non_finding_patterns = loader.get_non_finding_patterns()
"""

import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from functools import lru_cache

import yaml

logger = logging.getLogger(__name__)


class PatternLoader:
    """
    Loads and caches enrichment patterns from YAML configuration.

    Provides compiled regex patterns for finding types, non-finding detection,
    section classification, and entity normalization.
    """

    DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "enrichment_patterns.yaml"

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize pattern loader.

        Args:
            config_path: Path to YAML config. If None, uses default location.
        """
        self._config_path = config_path or self.DEFAULT_CONFIG_PATH
        self._config: Optional[Dict] = None
        self._compiled_patterns: Dict[str, Any] = {}

    def _load_config(self) -> Dict:
        """Load and cache YAML configuration."""
        if self._config is not None:
            return self._config

        if not self._config_path.exists():
            logger.warning(f"Pattern config not found at {self._config_path}, using empty config")
            self._config = {}
            return self._config

        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f) or {}
            logger.info(f"Loaded enrichment patterns from {self._config_path}")
        except Exception as e:
            logger.error(f"Failed to load pattern config: {e}")
            self._config = {}

        return self._config

    def get_finding_type_patterns(self) -> Dict[str, Dict]:
        """
        Get finding type patterns with compiled regex.

        Returns:
            Dict mapping finding_type -> {
                "patterns": List of (compiled_regex, confidence) tuples,
                "keywords": List of keyword strings,
                "tier_allowed": List of tier names
            }
        """
        if "finding_types" in self._compiled_patterns:
            return self._compiled_patterns["finding_types"]

        config = self._load_config()
        finding_types = config.get("finding_types", {})

        result = {}
        for finding_type, type_config in finding_types.items():
            compiled_patterns = []
            for p in type_config.get("patterns", []):
                try:
                    pattern_str = p.get("pattern") if isinstance(p, dict) else p
                    confidence = p.get("confidence", 0.8) if isinstance(p, dict) else 0.8
                    compiled = re.compile(pattern_str, re.IGNORECASE)
                    compiled_patterns.append((compiled, confidence))
                except re.error as e:
                    logger.warning(f"Invalid regex for {finding_type}: {p}, error: {e}")

            result[finding_type] = {
                "patterns": compiled_patterns,
                "keywords": type_config.get("keywords", []),
                "tier_allowed": type_config.get("tier_allowed", ["union", "state", "local_body"]),
            }

        self._compiled_patterns["finding_types"] = result
        return result

    def get_non_finding_patterns(self) -> List[Tuple[re.Pattern, str]]:
        """
        Get non-finding rejection patterns with compiled regex.

        Returns:
            List of (compiled_regex, reason) tuples
        """
        if "non_finding" in self._compiled_patterns:
            return self._compiled_patterns["non_finding"]

        config = self._load_config()
        patterns = config.get("non_finding_patterns", [])

        result = []
        for p in patterns:
            try:
                pattern_str = p.get("pattern") if isinstance(p, dict) else p
                reason = p.get("reason", "matches rejection pattern") if isinstance(p, dict) else "matches rejection pattern"
                compiled = re.compile(pattern_str, re.IGNORECASE | re.MULTILINE)
                result.append((compiled, reason))
            except re.error as e:
                logger.warning(f"Invalid non-finding regex: {p}, error: {e}")

        self._compiled_patterns["non_finding"] = result
        return result

    def get_section_patterns(self) -> Dict[str, Dict]:
        """
        Get section classification patterns with compiled regex.

        Returns:
            Dict mapping section_type -> {
                "patterns": List of compiled regex,
                "confidence": float
            }
        """
        if "section" in self._compiled_patterns:
            return self._compiled_patterns["section"]

        config = self._load_config()
        section_patterns = config.get("section_patterns", {})

        result = {}
        for section_type, type_config in section_patterns.items():
            compiled_patterns = []
            for p in type_config.get("patterns", []):
                try:
                    compiled = re.compile(p, re.IGNORECASE)
                    compiled_patterns.append(compiled)
                except re.error as e:
                    logger.warning(f"Invalid regex for section {section_type}: {p}, error: {e}")

            result[section_type] = {
                "patterns": compiled_patterns,
                "confidence": type_config.get("confidence", 0.8),
            }

        self._compiled_patterns["section"] = result
        return result

    def get_entity_aliases(self) -> Dict[str, Dict[str, List[str]]]:
        """
        Get entity alias mappings for normalization.

        Returns:
            Dict mapping category -> {canonical_name: [aliases]}
        """
        config = self._load_config()
        return config.get("entity_aliases", {})

    def get_deficiency_to_type_map(self) -> Dict[str, str]:
        """
        Build a keyword -> finding_type map from finding_types config.

        Returns:
            Dict mapping deficiency keyword -> finding_type string
        """
        if "deficiency_map" in self._compiled_patterns:
            return self._compiled_patterns["deficiency_map"]

        finding_patterns = self.get_finding_type_patterns()

        result = {}
        for finding_type, config in finding_patterns.items():
            for keyword in config.get("keywords", []):
                result[keyword.lower()] = finding_type

        self._compiled_patterns["deficiency_map"] = result
        return result

    def get_confidence_thresholds(self) -> Dict[str, float]:
        """
        Get confidence thresholds for various extractors.

        Returns:
            Dict mapping threshold_name -> float value
        """
        config = self._load_config()
        return config.get("confidence_thresholds", {
            "section_classification": 0.5,
            "finding_extraction": 0.4,
            "llm_validation_lower": 0.4,
            "llm_validation_upper": 0.7,
        })

    def get_temporal_config(self) -> Dict[str, Any]:
        """
        Get temporal extraction configuration.

        Returns:
            Dict with min_valid_year, max_valid_year, etc.
        """
        config = self._load_config()
        return config.get("temporal", {
            "min_valid_year": 2000,
            "max_valid_year": 2035,
        })

    def get_llm_validation_config(self) -> Dict[str, Any]:
        """
        Get LLM validation configuration.

        Returns:
            Dict with enabled, model, collect_refinement_data, refinement_data_path
        """
        config = self._load_config()
        return config.get("llm_validation", {
            "enabled": False,
            "model": "gemini-3.8-flash",
            "collect_refinement_data": False,
            "refinement_data_path": "logs/pattern_refinement/",
        })

    def reload(self) -> None:
        """Force reload of configuration from disk."""
        self._config = None
        self._compiled_patterns = {}
        self._load_config()
        logger.info("Pattern configuration reloaded")


# Global singleton instance
_pattern_loader: Optional[PatternLoader] = None


def get_pattern_loader() -> PatternLoader:
    """
    Get the global pattern loader instance.

    Returns:
        PatternLoader singleton
    """
    global _pattern_loader
    if _pattern_loader is None:
        _pattern_loader = PatternLoader()
    return _pattern_loader


def reload_patterns() -> None:
    """Reload patterns from disk (useful for hot-reloading)."""
    global _pattern_loader
    if _pattern_loader is not None:
        _pattern_loader.reload()
