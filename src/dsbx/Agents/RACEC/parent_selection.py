"""Parent selection for evolutionary operations in RACEC.

This module provides functionality to select parent rules from the repository
for crossover and mutation operations.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from .rules import RuleWithMeta


class ParentSelector:
    """Select parent rules for evolutionary operations."""
    
    def __init__(
        self,
        tournament_size: int = 3,
        diversity_weight: float = 0.3
    ):
        """Initialize parent selector.
        
        Args:
            tournament_size: Size of tournament for selection (must be >= 2)
            diversity_weight: Weight for diversity in selection (0.0-1.0)
                             0.0 = pure fitness-based, 1.0 = pure diversity-based
        
        Raises:
            ValueError: If tournament_size < 2 or diversity_weight not in [0.0, 1.0]
        """
        if tournament_size < 2:
            raise ValueError(f"tournament_size must be >= 2, got {tournament_size}")
        if not 0.0 <= diversity_weight <= 1.0:
            raise ValueError(f"diversity_weight must be in [0.0, 1.0], got {diversity_weight}")
        
        self._tournament_size = tournament_size
        self._diversity_weight = diversity_weight
        
        logger.debug(
            "ParentSelector initialized with tournament_size={}, diversity_weight={:.2f}",
            self._tournament_size,
            self._diversity_weight
        )
    
    def select_for_crossover(
        self,
        pool: List[RuleWithMeta],
        criteria: Optional[Dict[str, Any]] = None
    ) -> Tuple[RuleWithMeta, RuleWithMeta]:
        """Select 2 parents for crossover.
        
        Selection strategy:
        1. If criteria specifies parent IDs or strategies, try to match them
        2. Otherwise, use tournament selection with diversity consideration
        3. Ensure selected parents are distinct
        
        Args:
            pool: Pool of candidate parent rules (must have >= 2 rules)
            criteria: Optional selection criteria from Planner
                     {"parent1_strategy": "...", "parent2_strategy": "...", ...}
                     or {"parent1_id": "...", "parent2_id": "..."}
        
        Returns:
            Tuple of (parent1, parent2), guaranteed to be distinct
        
        Raises:
            ValueError: If pool has < 2 rules
        """
        if len(pool) < 2:
            raise ValueError(f"Need at least 2 rules in pool for crossover, got {len(pool)}")
        
        # Try criteria-based selection first
        if criteria:
            parent1 = self._select_by_criteria(pool, criteria, "parent1")
            parent2 = self._select_by_criteria(pool, criteria, "parent2")
            
            # If both found and distinct, use them
            if parent1 and parent2 and parent1.name != parent2.name:
                logger.info(
                    "ParentSelector: selected parents by criteria: '{}' and '{}'",
                    parent1.name,
                    parent2.name
                )
                return (parent1, parent2)
            
            # If only one found, use it as parent1 and select parent2 randomly
            if parent1:
                # Exclude parent1 from pool
                remaining = [r for r in pool if r.name != parent1.name]
                if remaining:
                    parent2 = self._tournament_selection(remaining)
                    logger.info(
                        "ParentSelector: selected parent1 by criteria '{}', parent2 by tournament '{}'",
                        parent1.name,
                        parent2.name
                    )
                    return (parent1, parent2)
        
        # Fallback: tournament selection for both parents
        parent1 = self._tournament_selection(pool)
        
        # Exclude parent1 from pool for parent2 selection
        remaining = [r for r in pool if r.name != parent1.name]
        if not remaining:
            # Edge case: only 2 rules in pool and they have same name
            # This shouldn't happen, but handle it gracefully
            logger.warning(
                "ParentSelector: all remaining rules have same name as parent1, using random selection"
            )
            remaining = [r for r in pool if r is not parent1]
        
        parent2 = self._tournament_selection(remaining)
        
        logger.info(
            "ParentSelector: selected parents by tournament: '{}' and '{}'",
            parent1.name,
            parent2.name
        )
        
        return (parent1, parent2)
    
    def select_for_mutation(
        self,
        pool: List[RuleWithMeta],
        parent_id: Optional[str] = None
    ) -> RuleWithMeta:
        """Select 1 parent for mutation.
        
        Selection strategy:
        1. If parent_id specified, try to find rule with that ID or name
        2. Otherwise, use fitness-based selection (higher fitness = higher probability)
        
        Args:
            pool: Pool of candidate parent rules (must have >= 1 rule)
            parent_id: Optional specific parent ID or name from Planner
        
        Returns:
            Selected parent rule
        
        Raises:
            ValueError: If pool is empty
        """
        if not pool:
            raise ValueError("Need at least 1 rule in pool for mutation")
        
        # Try specific parent_id first
        if parent_id:
            for rule in pool:
                # Match by name or rule_id
                rule_name = getattr(rule, "name", "")
                rule_info = getattr(rule, "info", {}) or {}
                rule_id = rule_info.get("rule_id", "")
                try:
                    if not rule_id and isinstance(rule_info.get("genealogy"), dict):
                        rule_id = rule_info.get("genealogy", {}).get("rule_id", "")
                except Exception:
                    rule_id = rule_info.get("rule_id", "")
                
                if rule_name == parent_id or rule_id == parent_id:
                    logger.info(
                        "ParentSelector: selected parent by ID '{}' for mutation",
                        rule_name
                    )
                    return rule
            
            logger.info(
                "ParentSelector: parent_id '{}' not found in pool, using fitness-based selection",
                parent_id
            )
        
        # Fallback: fitness-based selection
        parent = self._fitness_based_selection(pool)
        
        logger.info(
            "ParentSelector: selected parent '{}' by fitness for mutation",
            getattr(parent, "name", "unknown")
        )
        
        return parent
    
    def _select_by_criteria(
        self,
        pool: List[RuleWithMeta],
        criteria: Dict[str, Any],
        parent_key: str
    ) -> Optional[RuleWithMeta]:
        """Try to select a parent based on criteria.
        
        Args:
            pool: Pool of candidate rules
            criteria: Selection criteria dict
            parent_key: "parent1" or "parent2"
        
        Returns:
            Selected rule or None if not found
        """
        # Try ID-based selection
        id_key = f"{parent_key}_id"
        if id_key in criteria:
            target_id = str(criteria[id_key])
            for rule in pool:
                rule_name = getattr(rule, "name", "")
                rule_info = getattr(rule, "info", {}) or {}
                rule_id = rule_info.get("rule_id", "")
                
                if rule_name == target_id or rule_id == target_id:
                    return rule
        
        # Try strategy-based selection
        strategy_key = f"{parent_key}_strategy"
        if strategy_key in criteria:
            target_strategy = str(criteria[strategy_key]).lower()
            for rule in pool:
                rule_name = getattr(rule, "name", "").lower()
                rule_info = getattr(rule, "info", {}) or {}
                rule_desc = str(rule_info.get("description", "")).lower()
                
                # Match if strategy name appears in rule name or description
                if target_strategy in rule_name or target_strategy in rule_desc:
                    return rule
        
        return None
    
    def _tournament_selection(
        self,
        pool: List[RuleWithMeta]
    ) -> RuleWithMeta:
        """Select a rule using tournament selection.
        
        Tournament selection:
        1. Randomly sample tournament_size rules from pool
        2. Compute score for each: (1 - diversity_weight) * fitness + diversity_weight * diversity
        3. Return rule with highest score
        
        Args:
            pool: Pool of candidate rules (must be non-empty)
        
        Returns:
            Selected rule
        """
        if not pool:
            raise ValueError("Cannot select from empty pool")
        
        # Sample tournament participants
        tournament_size = min(self._tournament_size, len(pool))
        tournament = random.sample(pool, tournament_size)
        
        # Compute scores
        best_rule = None
        best_score = float("-inf")
        
        for rule in tournament:
            # Extract fitness and diversity from rule info
            rule_info = getattr(rule, "info", {}) or {}
            fitness = float(rule_info.get("fitness", 0.0))
            diversity = float(rule_info.get("diversity", 0.5))  # Default to mid-range
            
            # Compute combined score
            score = (1.0 - self._diversity_weight) * fitness + self._diversity_weight * diversity
            
            if score > best_score:
                best_score = score
                best_rule = rule
        
        logger.debug(
            "ParentSelector: tournament selected '{}' with score={:.4f}",
            getattr(best_rule, "name", "unknown"),
            best_score
        )
        
        return best_rule
    
    def _fitness_based_selection(
        self,
        pool: List[RuleWithMeta]
    ) -> RuleWithMeta:
        """Select a rule using fitness-proportionate selection.
        
        Fitness-proportionate selection:
        1. Compute fitness for each rule
        2. Normalize to probabilities (handle negative fitness)
        3. Sample according to probabilities
        
        Args:
            pool: Pool of candidate rules (must be non-empty)
        
        Returns:
            Selected rule
        """
        if not pool:
            raise ValueError("Cannot select from empty pool")
        
        # Extract fitness values
        fitnesses = []
        for rule in pool:
            rule_info = getattr(rule, "info", {}) or {}
            fitness = float(rule_info.get("fitness", 0.0))
            fitnesses.append(fitness)
        
        # Shift to make all positive (for probability computation)
        min_fitness = min(fitnesses)
        if min_fitness < 0:
            fitnesses = [f - min_fitness + 1.0 for f in fitnesses]
        
        # Compute probabilities
        total = sum(fitnesses)
        if total <= 0:
            # All zero fitness, use uniform selection
            selected = random.choice(pool)
        else:
            probabilities = [f / total for f in fitnesses]
            selected = random.choices(pool, weights=probabilities, k=1)[0]
        
        logger.debug(
            "ParentSelector: fitness-based selected '{}'",
            getattr(selected, "name", "unknown")
        )
        
        return selected
    
    @property
    def tournament_size(self) -> int:
        """Get tournament size."""
        return self._tournament_size
    
    @property
    def diversity_weight(self) -> float:
        """Get diversity weight."""
        return self._diversity_weight
