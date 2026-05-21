"""Diversity metrics for evolutionary computation in RACEC.

This module provides functions to compute structural and behavioral diversity
between scheduling rules, which is essential for maintaining population diversity
and preventing premature convergence in evolutionary algorithms.
"""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from .rules import RuleWithMeta, choose_action_by_rule


# Global cache for diversity computations
_DIVERSITY_CACHE: Dict[Tuple[str, str], DiversityMetrics] = {}
_CACHE_MAX_SIZE = 1000


@dataclass
class DiversityMetrics:
    """Diversity metrics for a rule or population.
    
    Attributes:
        structural_diversity: AST-based structural difference (0.0 to 1.0)
        behavioral_diversity: Action selection-based behavioral difference (0.0 to 1.0)
        combined_diversity: Weighted combination of structural and behavioral (0.0 to 1.0)
    """
    structural_diversity: float
    behavioral_diversity: float
    combined_diversity: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary format."""
        return {
            "structural": self.structural_diversity,
            "behavioral": self.behavioral_diversity,
            "combined": self.combined_diversity
        }


def extract_ast_features(tree: ast.AST) -> Dict[str, int]:
    """Extract countable features from an AST for diversity computation.
    
    Args:
        tree: Parsed AST of Python code
        
    Returns:
        Dictionary mapping feature names to counts
    """
    features = {
        "num_if": 0,
        "num_for": 0,
        "num_while": 0,
        "num_binop": 0,
        "num_compare": 0,
        "num_call": 0,
        "num_attribute": 0,
        "num_subscript": 0,
        "num_return": 0,
        "num_assign": 0,
        "depth": 0
    }
    
    try:
        class FeatureVisitor(ast.NodeVisitor):
            """Visitor to count AST node types."""
            
            def __init__(self):
                self.current_depth = 0
                self.max_depth = 0
            
            def generic_visit(self, node):
                self.current_depth += 1
                self.max_depth = max(self.max_depth, self.current_depth)
                super().generic_visit(node)
                self.current_depth -= 1
            
            def visit_If(self, node):
                features["num_if"] += 1
                self.generic_visit(node)
            
            def visit_For(self, node):
                features["num_for"] += 1
                self.generic_visit(node)
            
            def visit_While(self, node):
                features["num_while"] += 1
                self.generic_visit(node)
            
            def visit_BinOp(self, node):
                features["num_binop"] += 1
                self.generic_visit(node)
            
            def visit_Compare(self, node):
                features["num_compare"] += 1
                self.generic_visit(node)
            
            def visit_Call(self, node):
                features["num_call"] += 1
                self.generic_visit(node)
            
            def visit_Attribute(self, node):
                features["num_attribute"] += 1
                self.generic_visit(node)
            
            def visit_Subscript(self, node):
                features["num_subscript"] += 1
                self.generic_visit(node)
            
            def visit_Return(self, node):
                features["num_return"] += 1
                self.generic_visit(node)
            
            def visit_Assign(self, node):
                features["num_assign"] += 1
                self.generic_visit(node)
        
        visitor = FeatureVisitor()
        visitor.visit(tree)
        features["depth"] = visitor.max_depth
        
    except Exception as exc:
        logger.warning("extract_ast_features: failed to extract features: {}", exc)
        # Return default features on error
    
    return features


def compute_feature_distance(features1: Dict[str, int], features2: Dict[str, int]) -> float:
    """Compute normalized distance between two feature vectors.
    
    Uses normalized Manhattan distance (L1 norm) between feature vectors.
    
    Args:
        features1: Feature counts from first rule
        features2: Feature counts from second rule
        
    Returns:
        Normalized distance in range [0.0, 1.0]
    """
    # Get all feature keys
    all_keys = set(features1.keys()) | set(features2.keys())
    
    if not all_keys:
        return 0.0
    
    # Compute Manhattan distance
    total_distance = 0.0
    max_possible_distance = 0.0
    
    for key in all_keys:
        val1 = features1.get(key, 0)
        val2 = features2.get(key, 0)
        distance = abs(val1 - val2)
        total_distance += distance
        # Maximum possible distance for this feature
        max_possible_distance += max(val1, val2)
    
    # Normalize by maximum possible distance
    if max_possible_distance == 0:
        return 0.0
    
    normalized_distance = total_distance / max_possible_distance
    
    # Clamp to [0.0, 1.0]
    return min(1.0, max(0.0, normalized_distance))


def compute_structural_diversity(rule1: RuleWithMeta, rule2: RuleWithMeta) -> float:
    """Compute structural diversity between two rules using AST comparison.
    
    Args:
        rule1: First rule with metadata
        rule2: Second rule with metadata
        
    Returns:
        Structural diversity score in range [0.0, 1.0], where 0.0 means identical
        structure and 1.0 means maximally different structure. Returns 0.0 if
        either rule cannot be parsed.
    """
    # Fallback diversity score for errors
    FALLBACK_DIVERSITY = 0.0
    
    # Extract code from rule metadata
    try:
        code1 = rule1.info.get("code", "")
        code2 = rule2.info.get("code", "")
    except Exception as exc:
        logger.warning("compute_structural_diversity: failed to extract code from rules: {}", exc)
        return FALLBACK_DIVERSITY
    
    if not code1 or not code2:
        logger.warning("compute_structural_diversity: missing code in rule metadata")
        return FALLBACK_DIVERSITY
    
    # Parse code into AST
    try:
        tree1 = ast.parse(code1)
    except SyntaxError as exc:
        logger.warning(
            "compute_structural_diversity: syntax error parsing rule1 code: {}",
            exc
        )
        return FALLBACK_DIVERSITY
    except Exception as exc:
        logger.warning(
            "compute_structural_diversity: failed to parse rule1 code: {}",
            exc
        )
        return FALLBACK_DIVERSITY
    
    try:
        tree2 = ast.parse(code2)
    except SyntaxError as exc:
        logger.warning(
            "compute_structural_diversity: syntax error parsing rule2 code: {}",
            exc
        )
        return FALLBACK_DIVERSITY
    except Exception as exc:
        logger.warning(
            "compute_structural_diversity: failed to parse rule2 code: {}",
            exc
        )
        return FALLBACK_DIVERSITY
    
    # Extract features from both ASTs
    try:
        features1 = extract_ast_features(tree1)
        features2 = extract_ast_features(tree2)
    except Exception as exc:
        logger.warning("compute_structural_diversity: failed to extract AST features: {}", exc)
        return FALLBACK_DIVERSITY
    
    # Compute normalized distance
    try:
        distance = compute_feature_distance(features1, features2)
    except Exception as exc:
        logger.warning("compute_structural_diversity: failed to compute feature distance: {}", exc)
        return FALLBACK_DIVERSITY
    
    logger.debug(
        "compute_structural_diversity: computed diversity={:.4f} between '{}' and '{}'",
        distance,
        rule1.name,
        rule2.name
    )
    
    return distance


def generate_test_scenarios(
    model_summary: Optional[Dict[str, Any]] = None,
    num_scenarios: int = 10
) -> List[Dict[str, Any]]:
    """Generate test scenarios for behavioral diversity computation.
    
    Creates synthetic scheduling scenarios with observations, legal actions,
    and a mock environment for testing rule behavior.
    
    Args:
        model_summary: Optional model summary with job/machine information
        num_scenarios: Number of scenarios to generate
        
    Returns:
        List of scenario dictionaries with 'obs', 'legal_actions', and 'env' keys
    """
    scenarios = []
    
    # Default values if no model summary provided
    num_jobs = 5
    num_machines = 3
    
    if model_summary:
        num_jobs = model_summary.get("num_jobs", 5)
        num_machines = model_summary.get("num_machines", 3)
    
    for i in range(num_scenarios):
        # Create synthetic observation
        ready_ops = []
        for j in range(min(num_jobs, 3)):  # Limit to 3 ready ops per scenario
            ready_ops.append({
                "job_id": j,
                "machine_group": f"mg_{j % num_machines}",
                "process_time": 10.0 + i * 2.0 + j * 3.0,
                "remaining_work": 50.0 - i * 5.0,
                "remaining_ops": 5 - i,
                "flexibility": 0.5 + (i * 0.1) % 0.5,
                "priority": 1.0 + j * 0.2
            })
        
        obs = {
            "ready_ops": ready_ops,
            "current_time": i * 10.0,
            "num_jobs": num_jobs,
            "num_machines": num_machines
        }
        
        # Create legal actions corresponding to ready ops
        legal_actions = []
        for ro in ready_ops:
            legal_actions.append({
                "job_id": ro["job_id"],
                "machine_group": ro["machine_group"],
                "machine_candidates": [0, 1] if num_machines >= 2 else [0]
            })
        
        # Create mock environment (minimal interface)
        class MockEnv:
            def __init__(self):
                self.num_jobs = num_jobs
                self.num_machines = num_machines
        
        scenarios.append({
            "obs": obs,
            "legal_actions": legal_actions,
            "env": MockEnv()
        })
    
    return scenarios


def compute_behavioral_diversity(
    rule1: RuleWithMeta,
    rule2: RuleWithMeta,
    test_scenarios: Optional[List[Dict[str, Any]]] = None,
    model_summary: Optional[Dict[str, Any]] = None
) -> float:
    """Compute behavioral diversity based on action selection differences.
    
    Measures how often two rules make different action choices on the same
    scheduling scenarios. Higher diversity means the rules behave differently.
    
    Args:
        rule1: First rule with metadata
        rule2: Second rule with metadata
        test_scenarios: Optional list of test scenarios. If None, generates default scenarios.
        model_summary: Optional model summary for scenario generation
        
    Returns:
        Behavioral diversity score in range [0.0, 1.0], where 0.0 means identical
        behavior and 1.0 means completely different behavior. Returns 0.0 if
        scenarios cannot be evaluated.
    """
    # Fallback diversity score for errors
    FALLBACK_DIVERSITY = 0.0
    
    # Generate test scenarios if not provided
    if test_scenarios is None:
        try:
            test_scenarios = generate_test_scenarios(model_summary=model_summary, num_scenarios=10)
        except Exception as exc:
            logger.warning("compute_behavioral_diversity: failed to generate test scenarios: {}", exc)
            return FALLBACK_DIVERSITY
    
    if not test_scenarios:
        logger.warning("compute_behavioral_diversity: no test scenarios available")
        return FALLBACK_DIVERSITY
    
    disagreements = 0
    total_decisions = 0
    
    for scenario in test_scenarios:
        try:
            obs = scenario.get("obs", {})
            legal_actions = scenario.get("legal_actions", [])
            env = scenario.get("env")
            
            if not legal_actions:
                continue
            
            # Get action selected by each rule
            try:
                action1 = choose_action_by_rule(rule1.rule, obs, legal_actions, env)
            except Exception as exc:
                logger.debug(
                    "compute_behavioral_diversity: rule1 failed on scenario: {}",
                    exc
                )
                continue
            
            try:
                action2 = choose_action_by_rule(rule2.rule, obs, legal_actions, env)
            except Exception as exc:
                logger.debug(
                    "compute_behavioral_diversity: rule2 failed on scenario: {}",
                    exc
                )
                continue
            
            total_decisions += 1
            
            # Compare actions (by job_id and machine_id if present)
            if action1 is None or action2 is None:
                if action1 != action2:
                    disagreements += 1
            else:
                job1 = action1.get("job_id")
                job2 = action2.get("job_id")
                machine1 = action1.get("machine_id")
                machine2 = action2.get("machine_id")
                
                if job1 != job2 or machine1 != machine2:
                    disagreements += 1
        
        except Exception as exc:
            logger.debug("compute_behavioral_diversity: error processing scenario: {}", exc)
            continue
    
    if total_decisions == 0:
        logger.warning("compute_behavioral_diversity: no valid decisions made, using fallback")
        return FALLBACK_DIVERSITY
    
    try:
        diversity = disagreements / total_decisions
    except Exception as exc:
        logger.warning("compute_behavioral_diversity: failed to compute diversity: {}", exc)
        return FALLBACK_DIVERSITY
    
    return diversity


def compute_combined_diversity(
    rule1: RuleWithMeta,
    rule2: RuleWithMeta,
    test_scenarios: Optional[List[Dict[str, Any]]] = None,
    model_summary: Optional[Dict[str, Any]] = None,
    structural_weight: float = 0.5,
    behavioral_weight: float = 0.5,
    timeout: float = 5.0
) -> DiversityMetrics:
    """Compute combined diversity metrics between two rules.
    
    Computes both structural (AST-based) and behavioral (action-based) diversity,
    then combines them with configurable weights. Includes timeout handling and caching.
    
    Args:
        rule1: First rule with metadata
        rule2: Second rule with metadata
        test_scenarios: Optional list of test scenarios for behavioral diversity
        model_summary: Optional model summary for scenario generation
        structural_weight: Weight for structural diversity (default 0.5)
        behavioral_weight: Weight for behavioral diversity (default 0.5)
        timeout: Maximum time in seconds for computation (default 5.0)
        
    Returns:
        DiversityMetrics object with all three diversity scores
    """
    # Fallback diversity score for errors
    FALLBACK_DIVERSITY = 0.5
    
    # Check cache first
    cache_key = _get_cache_key(rule1, rule2)
    if cache_key in _DIVERSITY_CACHE:
        logger.debug(
            "compute_combined_diversity: cache hit for '{}' vs '{}'",
            rule1.name,
            rule2.name
        )
        return _DIVERSITY_CACHE[cache_key]
    
    start_time = time.time()
    
    # Compute structural diversity
    try:
        if time.time() - start_time > timeout:
            logger.warning(
                "compute_combined_diversity: timeout before structural computation for '{}' vs '{}'",
                rule1.name,
                rule2.name
            )
            return _create_fallback_metrics(FALLBACK_DIVERSITY)
        
        structural = compute_structural_diversity(rule1, rule2)
    except Exception as exc:
        logger.warning("compute_combined_diversity: structural diversity computation failed: {}", exc)
        structural = FALLBACK_DIVERSITY
    
    # Compute behavioral diversity
    try:
        if time.time() - start_time > timeout:
            logger.warning(
                "compute_combined_diversity: timeout before behavioral computation for '{}' vs '{}', using structural only",
                rule1.name,
                rule2.name
            )
            # Use structural diversity only
            result = DiversityMetrics(
                structural_diversity=structural,
                behavioral_diversity=structural,  # Use structural as fallback
                combined_diversity=structural
            )
            _cache_result(cache_key, result)
            return result
        
        behavioral = compute_behavioral_diversity(
            rule1, rule2,
            test_scenarios=test_scenarios,
            model_summary=model_summary
        )
    except Exception as exc:
        logger.warning("compute_combined_diversity: behavioral diversity computation failed: {}", exc)
        behavioral = FALLBACK_DIVERSITY
    
    # Check timeout before combining
    if time.time() - start_time > timeout:
        logger.warning(
            "compute_combined_diversity: timeout after behavioral computation for '{}' vs '{}', using partial results",
            rule1.name,
            rule2.name
        )
        result = DiversityMetrics(
            structural_diversity=structural,
            behavioral_diversity=behavioral,
            combined_diversity=(structural + behavioral) / 2.0
        )
        _cache_result(cache_key, result)
        return result
    
    # Compute weighted combination
    try:
        combined = (structural_weight * structural + behavioral_weight * behavioral)
        
        # Normalize weights if they don't sum to 1.0
        total_weight = structural_weight + behavioral_weight
        if total_weight > 0:
            combined = combined / total_weight
        else:
            logger.warning("compute_combined_diversity: total weight is zero, using fallback")
            combined = FALLBACK_DIVERSITY
    except Exception as exc:
        logger.warning("compute_combined_diversity: failed to compute combined diversity: {}", exc)
        combined = FALLBACK_DIVERSITY
    
    elapsed = time.time() - start_time
    logger.debug(
        "compute_combined_diversity: computed metrics for '{}' vs '{}' in {:.3f}s (structural={:.4f}, behavioral={:.4f}, combined={:.4f})",
        rule1.name,
        rule2.name,
        elapsed,
        structural,
        behavioral,
        combined
    )
    
    result = DiversityMetrics(
        structural_diversity=structural,
        behavioral_diversity=behavioral,
        combined_diversity=combined
    )
    
    # Cache the result
    _cache_result(cache_key, result)
    
    return result


def _get_cache_key(rule1: RuleWithMeta, rule2: RuleWithMeta) -> Tuple[str, str]:
    """Generate cache key for rule pair.
    
    Args:
        rule1: First rule
        rule2: Second rule
    
    Returns:
        Tuple of (rule1_id, rule2_id) sorted for consistency
    """
    # Try to get rule IDs from genealogy
    rule1_info = getattr(rule1, "info", {}) or {}
    rule2_info = getattr(rule2, "info", {}) or {}
    
    rule1_genealogy = rule1_info.get("genealogy", {})
    rule2_genealogy = rule2_info.get("genealogy", {})
    
    rule1_id = rule1_genealogy.get("rule_id") if isinstance(rule1_genealogy, dict) else None
    rule2_id = rule2_genealogy.get("rule_id") if isinstance(rule2_genealogy, dict) else None
    
    # Fallback to names if no IDs
    if not rule1_id:
        rule1_id = f"name_{rule1.name}"
    if not rule2_id:
        rule2_id = f"name_{rule2.name}"
    
    # Sort to ensure consistent cache keys regardless of order
    return tuple(sorted([rule1_id, rule2_id]))


def _cache_result(cache_key: Tuple[str, str], result: DiversityMetrics) -> None:
    """Cache diversity computation result.
    
    Args:
        cache_key: Cache key for the rule pair
        result: Diversity metrics to cache
    """
    global _DIVERSITY_CACHE
    
    # Limit cache size
    if len(_DIVERSITY_CACHE) >= _CACHE_MAX_SIZE:
        # Remove oldest entries (simple FIFO)
        keys_to_remove = list(_DIVERSITY_CACHE.keys())[:_CACHE_MAX_SIZE // 2]
        for key in keys_to_remove:
            del _DIVERSITY_CACHE[key]
        logger.debug("_cache_result: pruned cache to {} entries", len(_DIVERSITY_CACHE))
    
    _DIVERSITY_CACHE[cache_key] = result


def _create_fallback_metrics(fallback_value: float) -> DiversityMetrics:
    """Create fallback diversity metrics.
    
    Args:
        fallback_value: Value to use for all metrics
    
    Returns:
        DiversityMetrics with all values set to fallback_value
    """
    return DiversityMetrics(
        structural_diversity=fallback_value,
        behavioral_diversity=fallback_value,
        combined_diversity=fallback_value
    )


def clear_diversity_cache() -> None:
    """Clear the diversity computation cache.
    
    Useful for testing or when memory is a concern.
    """
    global _DIVERSITY_CACHE
    _DIVERSITY_CACHE.clear()
    logger.debug("clear_diversity_cache: cache cleared")
