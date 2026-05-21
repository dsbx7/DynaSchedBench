"""Rule evaluator for batch evaluation of repository rules.

This module provides efficient batch evaluation of multiple rules on the same
evaluation pool, with caching support to avoid redundant evaluations.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from .config import LLMCoderConfig
from .rules import PriorityRule, RuleWithMeta
from .sandbox_eval import (
    evaluate_candidate_rule,
    evaluate_candidate_rule_jms,
    evaluate_rule_absolute,
    evaluate_rule_absolute_jms,
    EvalEventsPool,
    JMSEvalPool,
)


class RuleEvaluator:
    """Evaluator for batch evaluation of rules.
    
    Provides efficient evaluation of multiple rules on the same eval pool,
    with caching to avoid redundant evaluations.
    """
    
    def __init__(self, cfg: LLMCoderConfig):
        """Initialize rule evaluator.
        
        Args:
            cfg: Configuration object
        """
        self.cfg = cfg
        self._cache: Dict[Tuple[str, str], float] = {}  # (rule_id, instance_id) -> fitness
        
    def batch_evaluate(
        self,
        rules: List[RuleWithMeta],
        eval_pool: EvalEventsPool | JMSEvalPool,
        baseline_rule: PriorityRule,
        objective_metric: str,
        time_budget: float = 30.0,
        max_rules: Optional[int] = None,
    ) -> Dict[str, float]:
        """Evaluate multiple rules on the same eval pool.
        
        All rules are evaluated on the exact same episodes for fair comparison.
        
        Args:
            rules: List of rules to evaluate
            eval_pool: Evaluation pool (same episodes for all rules)
            baseline_rule: Baseline rule for comparison
            objective_metric: Metric to optimize
            time_budget: Maximum time budget in seconds
            max_rules: Maximum number of rules to evaluate (None = all)
        
        Returns:
            Dictionary mapping rule_id to fitness (relative improvement)
        """
        start_time = time.time()
        results: Dict[str, float] = {}
        
        # Limit number of rules if specified
        rules_to_eval = rules[:max_rules] if max_rules else rules
        
        logger.info(
            "RuleEvaluator: starting batch evaluation of {} rules (time_budget={:.1f}s, max_rules={})",
            len(rules_to_eval),
            time_budget,
            max_rules
        )
        
        for i, rule in enumerate(rules_to_eval):
            # Check time budget
            elapsed = time.time() - start_time
            if elapsed >= time_budget:
                logger.info(
                    "RuleEvaluator: time budget exceeded after {} rules ({:.1f}s / {:.1f}s)",
                    i,
                    elapsed,
                    time_budget
                )
                break
            
            # Get rule ID for caching
            rule_id = self._get_rule_id(rule)
            
            # Evaluate rule
            fitness = self.evaluate_single(
                rule,
                eval_pool,
                baseline_rule,
                objective_metric
            )
            
            if fitness is not None:
                results[rule_id] = fitness
                logger.debug(
                    "RuleEvaluator: evaluated rule {} ({}/{}): fitness={:.4f}",
                    rule.name,
                    i + 1,
                    len(rules_to_eval),
                    fitness
                )
            else:
                logger.warning(
                    "RuleEvaluator: failed to evaluate rule {} ({}/{})",
                    rule.name,
                    i + 1,
                    len(rules_to_eval)
                )
        
        elapsed = time.time() - start_time
        logger.info(
            "RuleEvaluator: batch evaluation complete, evaluated {} rules in {:.1f}s",
            len(results),
            elapsed
        )
        
        return results


    def batch_evaluate_absolute(
        self,
        rules: List[RuleWithMeta],
        eval_pool: EvalEventsPool | JMSEvalPool,
        objective_metric: str,
        time_budget: float = 30.0,
        max_rules: Optional[int] = None,
    ) -> Dict[str, float]:
        """Evaluate multiple rules and return absolute objective metric mean.

        Returns a dictionary mapping rule_id to metric mean on the eval pool.
        For metrics like makespan, lower is better.
        """
        start_time = time.time()
        results: Dict[str, float] = {}

        rules_to_eval = rules[:max_rules] if max_rules else rules

        logger.info(
            "RuleEvaluator: starting absolute batch evaluation of {} rules (time_budget={:.1f}s, max_rules={}, metric='{}')",
            len(rules_to_eval),
            time_budget,
            max_rules,
            objective_metric,
        )

        for i, rule in enumerate(rules_to_eval):
            elapsed = time.time() - start_time
            if elapsed >= time_budget:
                logger.info(
                    "RuleEvaluator: time budget exceeded after {} rules ({:.1f}s / {:.1f}s)",
                    i,
                    elapsed,
                    time_budget,
                )
                break

            rule_id = self._get_rule_id(rule)
            metric_mean = self.evaluate_single_absolute(rule, eval_pool, objective_metric)
            if metric_mean is not None:
                results[rule_id] = float(metric_mean)
                logger.debug(
                    "RuleEvaluator: absolute-evaluated rule {} ({}/{}): metric_mean={:.6f}",
                    rule.name,
                    i + 1,
                    len(rules_to_eval),
                    float(metric_mean),
                )
            else:
                logger.warning(
                    "RuleEvaluator: failed to absolute-evaluate rule {} ({}/{})",
                    rule.name,
                    i + 1,
                    len(rules_to_eval),
                )

        elapsed = time.time() - start_time
        logger.info(
            "RuleEvaluator: absolute batch evaluation complete, evaluated {} rules in {:.1f}s",
            len(results),
            elapsed,
        )
        return results
    
    def evaluate_single(
        self,
        rule: RuleWithMeta,
        eval_pool: EvalEventsPool | JMSEvalPool,
        baseline_rule: PriorityRule,
        objective_metric: str
    ) -> Optional[float]:
        """Evaluate a single rule on eval pool.
        
        Args:
            rule: Rule to evaluate
            eval_pool: Evaluation pool
            baseline_rule: Baseline rule for comparison
            objective_metric: Metric to optimize
        
        Returns:
            Fitness (relative improvement) or None if evaluation failed
        """
        # Get rule ID and instance ID for caching
        rule_id = self._get_rule_id(rule)
        instance_id = self._get_instance_id(eval_pool)
        cache_key = (rule_id, instance_id)
        
        # Check cache
        if cache_key in self._cache:
            logger.debug(
                "RuleEvaluator: cache hit for rule {} on instance {}",
                rule.name,
                instance_id
            )
            return self._cache[cache_key]
        
        # Evaluate rule
        try:
            # Get rule code for subprocess evaluation
            rule_code = None
            if hasattr(rule, "info") and isinstance(rule.info, dict):
                rule_code = rule.info.get("code")
            
            # Choose evaluation function based on pool type
            if isinstance(eval_pool, JMSEvalPool):
                eval_result = evaluate_candidate_rule_jms(
                    baseline_rule=baseline_rule,
                    candidate_rule=rule.rule,
                    cfg=self.cfg,
                    candidate_code=rule_code,
                    events_pool=eval_pool,  # Fixed: use events_pool parameter name
                    objective_metric=objective_metric,
                )
            else:
                # EvalEventsPool
                eval_result = evaluate_candidate_rule(
                    baseline_rule=baseline_rule,
                    candidate_rule=rule.rule,
                    cfg=self.cfg,
                    candidate_code=rule_code,
                    events_pool=eval_pool,
                    objective_metric=objective_metric,
                )
            
            if eval_result is None:
                logger.warning(
                    "RuleEvaluator: evaluation returned None for rule {}",
                    rule.name
                )
                return None

            # Extract fitness (relative improvement)
            fitness = float(eval_result.relative_improvement)

            # Cache result
            self._cache[cache_key] = fitness

            return fitness

        except Exception as e:
            logger.error(
                "RuleEvaluator: evaluation failed for rule {}: {}",
                rule.name,
                e
            )
            return None


    def evaluate_single_absolute(
        self,
        rule: RuleWithMeta,
        eval_pool: EvalEventsPool | JMSEvalPool,
        objective_metric: str,
    ) -> Optional[float]:
        """Evaluate a single rule and return absolute objective metric mean."""
        rule_id = self._get_rule_id(rule)
        instance_id = self._get_instance_id(eval_pool)
        cache_key = (rule_id, instance_id)

        if cache_key in self._cache:
            logger.debug(
                "RuleEvaluator: cache hit for absolute eval rule {} on instance {}",
                rule.name,
                instance_id,
            )
            return self._cache[cache_key]

        try:
            rule_code = None
            if hasattr(rule, "info") and isinstance(rule.info, dict):
                rule_code = rule.info.get("code")

            if isinstance(eval_pool, JMSEvalPool):
                eval_result = evaluate_rule_absolute_jms(
                    candidate_rule=rule.rule,
                    cfg=self.cfg,
                    candidate_code=rule_code,
                    events_pool=eval_pool,
                    objective_metric=objective_metric,
                )
            else:
                eval_result = evaluate_rule_absolute(
                    candidate_rule=rule.rule,
                    cfg=self.cfg,
                    candidate_code=rule_code,
                    events_pool=eval_pool,
                    objective_metric=objective_metric,
                )

            if eval_result is None:
                logger.warning(
                    "RuleEvaluator: absolute evaluation returned None for rule {}",
                    rule.name,
                )
                return None

            metric_mean = float(eval_result.metric_mean)
            self._cache[cache_key] = metric_mean
            return metric_mean

        except Exception as e:
            logger.error(
                "RuleEvaluator: absolute evaluation failed for rule {}: {}",
                rule.name,
                e,
            )
            return None
            
    
    def _get_rule_id(self, rule: RuleWithMeta) -> str:
        """Get unique identifier for a rule.
        
        Args:
            rule: Rule to get ID for
        
        Returns:
            Unique rule identifier
        """
        # Try to get rule_id from genealogy
        if hasattr(rule, "info") and isinstance(rule.info, dict):
            genealogy = rule.info.get("genealogy")
            if isinstance(genealogy, dict):
                rule_id = genealogy.get("rule_id")
                if rule_id:
                    return str(rule_id)
        
        # Fallback to rule name
        return rule.name
    
    def _get_instance_id(self, eval_pool: EvalEventsPool | JMSEvalPool) -> str:
        """Get unique identifier for an eval pool instance.
        
        Args:
            eval_pool: Evaluation pool
        
        Returns:
            Unique instance identifier
        """
        # Use pool's base seed and size as identifier
        try:
            if isinstance(eval_pool, JMSEvalPool):
                # JMS pool identifier
                return f"jms_{id(eval_pool)}"
            else:
                # Events pool identifier
                base_seed = getattr(eval_pool, "_base_seed", 0)
                pool_size = getattr(eval_pool, "_pool_size", 0)
                return f"events_{base_seed}_{pool_size}"
        except Exception:
            # Fallback to object ID
            return f"pool_{id(eval_pool)}"
    
    def clear_cache(self) -> None:
        """Clear evaluation cache."""
        self._cache.clear()
        logger.debug("RuleEvaluator: cache cleared")
