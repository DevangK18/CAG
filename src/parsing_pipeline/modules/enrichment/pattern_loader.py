"""
Pattern Loader: Loads enrichment patterns from YAML configuration.

P1-B: Enables pattern externalization for easier maintenance and updates
without code changes.

Usage:
    from src.parsing_pipeline.modules.enrichment.pattern_loader import get_pattern_loader

    aliases = get_pattern_loader().get_entity_aliases()
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml

logger = logging.getLogger(__name__)


class PatternLoader:
    """
    Loads and caches enrichment patterns from YAML configuration.

    Provides entity aliases and the section-classification threshold.
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

    def get_entity_aliases(self) -> Dict[str, Dict[str, List[str]]]:
        """
        Get entity alias mappings for normalization.

        Returns:
            Dict mapping category -> {canonical_name: [aliases]}
        """
        config = self._load_config()
        return config.get("entity_aliases", {})

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
