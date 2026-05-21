"""Similarity filtering for evolutionary operations in RACEC.

This module provides functionality to filter repository rules by similarity
to the current instance, ensuring that only relevant rules are used as parents
for crossover and mutation operations.
"""

from __future__ import annotations

from typing import Any, Dict, List

from loguru import logger

from .rules import RuleWithMeta


class SimilarityFilter:
    """Filter repository rules by similarity to target instance."""
    
    def __init__(
        self,
        min_threshold: float = 0.6,
        weights: Dict[str, float] | None = None
    ):
        """Initialize similarity filter.
        
        Args:
            min_threshold: Minimum similarity score (0.0-1.0) for a rule to be considered similar
            weights: Weights for similarity components. Must sum to 1.0.
                     Default: {"num_jobs": 0.3, "num_machines": 0.3, "config_path": 0.4}
        
        Raises:
            ValueError: If min_threshold not in [0.0, 1.0] or weights don't sum to 1.0
        """
        if not 0.0 <= min_threshold <= 1.0:
            raise ValueError(f"min_threshold must be in [0.0, 1.0], got {min_threshold}")
        
        self._min_threshold = min_threshold
        
        # Set default weights if not provided
        if weights is None:
            self._weights = {
                "num_jobs": 0.3,
                "num_machines": 0.3,
                "config_path": 0.4
            }
        else:
            self._weights = dict(weights)
        
        # Validate weights sum to 1.0 (with small tolerance for floating point)
        weight_sum = sum(self._weights.values())
        if not (0.99 <= weight_sum <= 1.01):
            raise ValueError(f"Weights must sum to 1.0, got {weight_sum}")
        
        logger.debug(
            "SimilarityFilter initialized with threshold={:.2f}, weights={}",
            self._min_threshold,
            self._weights
        )
    
    def compute_similarity(
        self,
        rule_summary: Dict[str, Any],
        target_summary: Dict[str, Any]
    ) -> float:
        """Compute similarity score between rule and target instance.
        
        Similarity is computed as a weighted combination of:
        - Job count similarity: 1.0 - |rule_jobs - target_jobs| / max(rule_jobs, target_jobs)
        - Machine count similarity: 1.0 - |rule_machines - target_machines| / max(rule_machines, target_machines)
        - Config path match: 1.0 if paths match, 0.0 otherwise
        
        Args:
            rule_summary: Model summary from rule's info
                         {"num_jobs": int, "num_machines": int, "config_path": str}
            target_summary: Model summary for current instance
                           {"num_jobs": int, "num_machines": int, "config_path": str}
        
        Returns:
            Similarity score in [0.0, 1.0], where 1.0 means identical
        """
        # Extract values with defaults
        rule_jobs = float(rule_summary.get("num_jobs", 0) or 0)
        rule_machines = float(rule_summary.get("num_machines", 0) or 0)
        rule_config = str(rule_summary.get("config_path", "") or "")
        
        target_jobs = float(target_summary.get("num_jobs", 0) or 0)
        target_machines = float(target_summary.get("num_machines", 0) or 0)
        target_config = str(target_summary.get("config_path", "") or "")
        
        # Compute job count similarity
        if rule_jobs == 0 and target_jobs == 0:
            jobs_sim = 1.0
        elif rule_jobs == 0 or target_jobs == 0:
            jobs_sim = 0.0
        else:
            max_jobs = max(rule_jobs, target_jobs)
            jobs_sim = 1.0 - abs(rule_jobs - target_jobs) / max_jobs
        
        # Compute machine count similarity
        if rule_machines == 0 and target_machines == 0:
            machines_sim = 1.0
        elif rule_machines == 0 or target_machines == 0:
            machines_sim = 0.0
        else:
            max_machines = max(rule_machines, target_machines)
            machines_sim = 1.0 - abs(rule_machines - target_machines) / max_machines
        
        # Compute config path match
        config_sim = 1.0 if rule_config and rule_config == target_config else 0.0
        
        # Weighted combination
        similarity = (
            self._weights.get("num_jobs", 0.0) * jobs_sim +
            self._weights.get("num_machines", 0.0) * machines_sim +
            self._weights.get("config_path", 0.0) * config_sim
        )
        
        # Clamp to [0.0, 1.0] to handle floating point errors
        similarity = max(0.0, min(1.0, similarity))
        
        logger.debug(
            "Similarity computed: jobs_sim={:.3f}, machines_sim={:.3f}, config_sim={:.3f}, total={:.3f}",
            jobs_sim,
            machines_sim,
            config_sim,
            similarity
        )
        
        return similarity
    
    def filter_rules(
        self,
        rules: List[RuleWithMeta],
        target_summary: Dict[str, Any]
    ) -> List[RuleWithMeta]:
        """Filter rules by similarity to target instance.
        
        Args:
            rules: List of rules from repository
            target_summary: Model summary for current instance
        
        Returns:
            List of rules with similarity >= min_threshold, sorted by similarity (descending)
        """
        if not rules:
            logger.debug("SimilarityFilter: no rules to filter")
            return []
        
        # Compute similarity for each rule
        rule_similarities: List[tuple[RuleWithMeta, float]] = []
        
        for rule in rules:
            try:
                # Extract model_summary from rule info
                rule_info = getattr(rule, "info", {}) or {}
                rule_summary = rule_info.get("model_summary", {})
                
                if not isinstance(rule_summary, dict):
                    logger.warning(
                        "SimilarityFilter: rule '{}' has invalid model_summary, skipping",
                        getattr(rule, "name", "unknown")
                    )
                    continue
                
                # Compute similarity
                similarity = self.compute_similarity(rule_summary, target_summary)
                
                # Only keep if meets threshold
                if similarity >= self._min_threshold:
                    rule_similarities.append((rule, similarity))
                    logger.debug(
                        "SimilarityFilter: rule '{}' similarity={:.3f} (>= threshold={:.3f})",
                        getattr(rule, "name", "unknown"),
                        similarity,
                        self._min_threshold
                    )
                else:
                    logger.debug(
                        "SimilarityFilter: rule '{}' similarity={:.3f} (< threshold={:.3f}), filtered out",
                        getattr(rule, "name", "unknown"),
                        similarity,
                        self._min_threshold
                    )
            
            except Exception as exc:
                logger.warning(
                    "SimilarityFilter: error computing similarity for rule '{}': {}",
                    getattr(rule, "name", "unknown"),
                    exc
                )
                continue
        
        # Sort by similarity (descending)
        rule_similarities.sort(key=lambda x: x[1], reverse=True)
        
        # Extract rules
        filtered_rules = [rule for rule, _ in rule_similarities]
        
        logger.info(
            "SimilarityFilter: filtered {} rules from {} total (threshold={:.2f})",
            len(filtered_rules),
            len(rules),
            self._min_threshold
        )
        
        if filtered_rules:
            avg_similarity = sum(sim for _, sim in rule_similarities) / len(rule_similarities)
            logger.info(
                "SimilarityFilter: average similarity of filtered rules: {:.3f}",
                avg_similarity
            )
        
        return filtered_rules
    
    @property
    def min_threshold(self) -> float:
        """Get minimum similarity threshold."""
        return self._min_threshold
    
    @property
    def weights(self) -> Dict[str, float]:
        """Get similarity weights."""
        return dict(self._weights)
