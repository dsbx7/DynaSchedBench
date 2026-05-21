"""Population management and genealogy tracking for RACEC evolutionary operations."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from .rules import RuleWithMeta


@dataclass
class GenealogyInfo:
    """Genealogy information for a rule."""
    
    rule_id: str
    parent_ids: List[str]
    operation: str  # "generated", "crossover", "mutation", "repository"
    generation: int
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert genealogy info to dictionary for serialization."""
        return {
            "rule_id": self.rule_id,
            "parent_ids": list(self.parent_ids),
            "operation": self.operation,
            "generation": self.generation,
            "timestamp": self.timestamp
        }
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> GenealogyInfo:
        """Create genealogy info from dictionary."""
        return GenealogyInfo(
            rule_id=str(data.get("rule_id", "")),
            parent_ids=list(data.get("parent_ids", [])),
            operation=str(data.get("operation", "generated")),
            generation=int(data.get("generation", 0)),
            timestamp=float(data.get("timestamp", 0.0))
        )


def generate_rule_id() -> str:
    """Generate a unique identifier for a rule.
    
    Returns:
        A unique string identifier (UUID4)
    """
    return str(uuid.uuid4())


def create_genealogy_info(
    operation: str,
    generation: int = 0,
    parent_ids: Optional[List[str]] = None
) -> GenealogyInfo:
    """Create genealogy information for a new rule.
    
    Args:
        operation: Type of operation ("generated", "crossover", "mutation", "repository")
        generation: Generation number
        parent_ids: List of parent rule IDs (empty for generated rules)
    
    Returns:
        GenealogyInfo object with unique rule ID and timestamp
    """
    return GenealogyInfo(
        rule_id=generate_rule_id(),
        parent_ids=parent_ids or [],
        operation=operation,
        generation=generation,
        timestamp=time.time()
    )


def add_genealogy_to_rule(
    rule: RuleWithMeta,
    genealogy: GenealogyInfo
) -> RuleWithMeta:
    """Add genealogy information to a rule's info dict.
    
    Args:
        rule: The rule to add genealogy to
        genealogy: The genealogy information
    
    Returns:
        The same rule with genealogy added to info
    """
    if not isinstance(rule.info, dict):
        rule.info = {}
    
    rule.info["genealogy"] = genealogy.to_dict()
    
    return rule


@dataclass
class RuleIndividual:
    """Wrapper for a rule with evolutionary metadata."""
    
    rule: RuleWithMeta
    fitness: float
    generation: int
    diversity_score: float = 0.0
    genealogy: Dict[str, Any] = field(default_factory=dict)


class PopulationManager:
    """Manages populations for evolutionary computation."""
    
    def __init__(
        self,
        max_size: int = 50,
        min_diversity: float = 0.3
    ):
        """Initialize population manager.
        
        Args:
            max_size: Maximum population size
            min_diversity: Minimum diversity threshold
        """
        self._max_size = max_size
        self._min_diversity = min_diversity
        self._population: List[RuleIndividual] = []
        self._generation = 0
    
    def add_individual(
        self,
        rule: RuleWithMeta,
        fitness: float,
        parent_ids: Optional[List[str]] = None,
        operation: str = "generated"
    ) -> None:
        """Add a rule to the population.
        
        Args:
            rule: The rule to add
            fitness: Fitness score
            parent_ids: Parent rule IDs for genealogy
            operation: Operation type ("generated", "crossover", "mutation")
        """
        # Extract genealogy from rule info if present
        genealogy = rule.info.get("genealogy", {})
        if not genealogy:
            # Create new genealogy if not present
            genealogy_info = create_genealogy_info(
                operation=operation,
                generation=self._generation,
                parent_ids=parent_ids
            )
            genealogy = genealogy_info.to_dict()
            rule.info["genealogy"] = genealogy
            logger.debug(
                "PopulationManager: created genealogy for rule '{}' (operation={}, generation={})",
                rule.name,
                operation,
                self._generation
            )
        
        individual = RuleIndividual(
            rule=rule,
            fitness=fitness,
            generation=genealogy.get("generation", self._generation),
            diversity_score=0.0,
            genealogy=genealogy
        )
        
        self._population.append(individual)
        
        logger.info(
            "PopulationManager: added individual '{}' (fitness={:.6f}, generation={}, operation={})",
            rule.name,
            fitness,
            individual.generation,
            operation
        )
        
        # Prune if exceeds max size
        if len(self._population) > self._max_size:
            logger.debug(
                "PopulationManager: population size {} exceeds max {}, pruning",
                len(self._population),
                self._max_size
            )
            self.prune_population()
    
    def select_parents(
        self,
        n: int = 2,
        method: str = "tournament"
    ) -> List[RuleIndividual]:
        """Select parent rules for evolutionary operations.
        
        Args:
            n: Number of parents to select
            method: Selection method ("tournament", "roulette", "rank")
        
        Returns:
            List of selected parent individuals
        """
        if not self._population or n <= 0:
            return []
        
        if method == "tournament":
            return self._tournament_selection(n)
        elif method == "roulette":
            return self._roulette_selection(n)
        elif method == "rank":
            return self._rank_selection(n)
        else:
            # Default to tournament
            return self._tournament_selection(n)
    
    def _tournament_selection(self, n: int, tournament_size: int = 3) -> List[RuleIndividual]:
        """Tournament selection."""
        import random
        
        selected = []
        for _ in range(n):
            if len(self._population) <= tournament_size:
                tournament = self._population
            else:
                tournament = random.sample(self._population, tournament_size)
            
            # Select best from tournament
            winner = max(tournament, key=lambda x: x.fitness)
            selected.append(winner)
        
        return selected
    
    def _roulette_selection(self, n: int) -> List[RuleIndividual]:
        """Roulette wheel selection."""
        import random
        
        # Shift fitness to be non-negative
        min_fitness = min(ind.fitness for ind in self._population)
        if min_fitness < 0:
            adjusted_fitness = [ind.fitness - min_fitness + 1.0 for ind in self._population]
        else:
            adjusted_fitness = [ind.fitness for ind in self._population]
        
        total_fitness = sum(adjusted_fitness)
        if total_fitness <= 0:
            # Fallback to random selection
            return random.sample(self._population, min(n, len(self._population)))
        
        selected = []
        for _ in range(n):
            r = random.uniform(0, total_fitness)
            cumsum = 0.0
            for i, ind in enumerate(self._population):
                cumsum += adjusted_fitness[i]
                if cumsum >= r:
                    selected.append(ind)
                    break
        
        return selected
    
    def _rank_selection(self, n: int) -> List[RuleIndividual]:
        """Rank-based selection."""
        import random
        
        # Sort by fitness
        sorted_pop = sorted(self._population, key=lambda x: x.fitness)
        
        # Assign ranks (1 to len)
        ranks = list(range(1, len(sorted_pop) + 1))
        total_rank = sum(ranks)
        
        selected = []
        for _ in range(n):
            r = random.uniform(0, total_rank)
            cumsum = 0.0
            for i, ind in enumerate(sorted_pop):
                cumsum += ranks[i]
                if cumsum >= r:
                    selected.append(ind)
                    break
        
        return selected
    
    def compute_diversity(
        self,
        rule1: RuleWithMeta,
        rule2: RuleWithMeta
    ) -> float:
        """Compute diversity score between two rules.
        
        This is a placeholder that returns 0.5. The actual implementation
        will be provided by the diversity module.
        
        Args:
            rule1: First rule
            rule2: Second rule
        
        Returns:
            Diversity score between 0 and 1
        """
        # Placeholder - will be implemented in diversity module
        return 0.5
    
    def prune_population(self) -> None:
        """Remove low-fitness, low-diversity individuals."""
        if len(self._population) <= self._max_size:
            return
        
        initial_size = len(self._population)
        
        # Sort by fitness (descending)
        sorted_pop = sorted(self._population, key=lambda x: x.fitness, reverse=True)
        
        # Keep top performers
        keep_count = int(self._max_size * 0.7)  # Keep 70% based on fitness
        kept = sorted_pop[:keep_count]
        
        # Fill remaining slots with diverse individuals
        remaining = sorted_pop[keep_count:]
        remaining_slots = self._max_size - len(kept)
        
        if remaining and remaining_slots > 0:
            # Simple diversity-based selection: keep individuals that are different
            # This is a placeholder - actual diversity computation will be more sophisticated
            diverse_kept = remaining[:remaining_slots]
            kept.extend(diverse_kept)
        
        self._population = kept
        
        logger.info(
            "PopulationManager: pruned population from {} to {} individuals (kept top {} by fitness, {} by diversity)",
            initial_size,
            len(self._population),
            keep_count,
            len(self._population) - keep_count
        )
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get population statistics.
        
        Returns:
            Dictionary with population statistics
        """
        if not self._population:
            return {
                "size": 0,
                "generation": self._generation,
                "avg_fitness": 0.0,
                "max_fitness": 0.0,
                "min_fitness": 0.0
            }
        
        fitnesses = [ind.fitness for ind in self._population]
        
        return {
            "size": len(self._population),
            "generation": self._generation,
            "avg_fitness": sum(fitnesses) / len(fitnesses),
            "max_fitness": max(fitnesses),
            "min_fitness": min(fitnesses),
            "avg_diversity": sum(ind.diversity_score for ind in self._population) / len(self._population)
        }
    
    def increment_generation(self) -> None:
        """Move to next generation."""
        self._generation += 1
        stats = self.get_statistics()
        logger.info(
            "PopulationManager: incremented to generation {} (population_size={}, avg_fitness={:.6f}, max_fitness={:.6f})",
            self._generation,
            stats["size"],
            stats["avg_fitness"],
            stats["max_fitness"]
        )
    
    @property
    def generation(self) -> int:
        """Get current generation number."""
        return self._generation
    
    @property
    def population(self) -> List[RuleIndividual]:
        """Get current population."""
        return list(self._population)
