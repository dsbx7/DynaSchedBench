"""Candidate generation for evolutionary operations in RACEC.

This module provides unified candidate generation from all strategy types:
generate, crossover, and mutation.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from loguru import logger

from .agentic import StrategyPlan, CandidateRecord
from .coder import LLMCoder
from .evolutionary import CrossoverOperator, MutationOperator
from .parent_selection import ParentSelector
from .iteration_pool import IterationPool
from .rules import RuleWithMeta


class CandidateGenerator:
    """Unified interface for generating candidates from all strategy types."""
    
    def __init__(
        self,
        llm_coder: LLMCoder,
        crossover_op: CrossoverOperator,
        mutation_op: MutationOperator,
        parent_selector: ParentSelector
    ):
        """Initialize candidate generator.
        
        Args:
            llm_coder: LLM coder for generate strategies
            crossover_op: Crossover operator for crossover strategies
            mutation_op: Mutation operator for mutation strategies
            parent_selector: Parent selector for evolutionary operations
        """
        self._llm_coder = llm_coder
        self._crossover_op = crossover_op
        self._mutation_op = mutation_op
        self._parent_selector = parent_selector
        
        logger.debug("CandidateGenerator initialized")
    
    def generate_from_plans(
        self,
        plans: List[StrategyPlan],
        model_summary: Dict[str, Any],
        obs_example: Dict[str, Any],
        baseline_name: str,
        objective_metric: str,
        repository_rules_pool: Optional[List[RuleWithMeta]] = None,
        similar_rules_pool: Optional[List[RuleWithMeta]] = None,
        iteration: int = 0
    ) -> List[CandidateRecord]:
        """Generate candidates from strategy plans.
        
        Process plans in order:
        1. Sort plans: generate first, then crossover/mutation
        2. For each plan, generate candidate
        3. After each successful generation, add to iteration pool
        4. Subsequent plans can use newly generated rules as parents
        
        Args:
            plans: List of strategy plans from Planner
            repository_rules_pool: All rules from repository (no filtering)
            model_summary: Model summary for current instance
            obs_example: Observation example
            baseline_name: Name of baseline heuristic
            objective_metric: Objective metric to optimize
            iteration: Current iteration number
        
        Returns:
            List of CandidateRecord with generated rules
        """
        if not plans:
            logger.info("CandidateGenerator: no plans to process")
            return []
        
        # Backward compatibility: earlier versions used similar_rules_pool
        base_pool = repository_rules_pool
        if base_pool is None:
            base_pool = similar_rules_pool
        if base_pool is None:
            base_pool = []

        # Initialize iteration pool with all repository rules
        iteration_pool = IterationPool(base_pool)
        
        # Sort plans: generate first, then crossover/mutation
        sorted_plans = self._sort_plans(plans)

        allow_crossover = bool(getattr(self._llm_coder.cfg, "evolution_allow_crossover", True))
        allow_mutation = bool(getattr(self._llm_coder.cfg, "evolution_allow_mutation", True))
        
        logger.info(
            "CandidateGenerator: processing {} plans (generate: {}, crossover: {}, mutation: {})",
            len(sorted_plans),
            sum(1 for p in sorted_plans if p.strategy_type == "generate"),
            sum(1 for p in sorted_plans if p.strategy_type == "crossover"),
            sum(1 for p in sorted_plans if p.strategy_type == "mutation")
        )
        
        # Generate candidates
        candidates: List[CandidateRecord] = []
        candidate_index = 0
        
        for plan_idx, plan in enumerate(sorted_plans):
            st = str(getattr(plan, "strategy_type", "generate") or "generate").lower()
            if st == "crossover" and not allow_crossover:
                logger.info(
                    "CandidateGenerator: skipping crossover plan '{}' because evolution_allow_crossover is disabled",
                    plan.name,
                )
                continue
            if st == "mutation" and not allow_mutation:
                logger.info(
                    "CandidateGenerator: skipping mutation plan '{}' because evolution_allow_mutation is disabled",
                    plan.name,
                )
                continue
            logger.info(
                "CandidateGenerator: processing plan {}/{}: '{}' (type: {})",
                plan_idx + 1,
                len(sorted_plans),
                plan.name,
                plan.strategy_type
            )
            
            # Build context for generation
            context = {
                "model_summary": model_summary,
                "obs_example": obs_example,
                "baseline_name": baseline_name,
                "objective_metric": objective_metric,
                "objective_mode": "min",  # Assuming min for now
                "plan": plan,
                "iteration_pool": iteration_pool.get_pool()
            }
            
            # Generate candidate
            try:
                rule = self._generate_candidate(plan, context)
                
                if rule is not None:
                    # Generate temporary ID
                    temp_id = IterationPool.generate_temp_id()
                    
                    # Create candidate record
                    candidate = CandidateRecord(
                        index=candidate_index,
                        rule=rule,
                        plan=plan,
                        iteration=iteration
                    )
                    candidates.append(candidate)
                    candidate_index += 1
                    
                    # Add to iteration pool for subsequent plans
                    iteration_pool.add_candidate(rule, temp_id)
                    
                    logger.info(
                        "CandidateGenerator: successfully generated candidate '{}' from plan '{}' (type: {})",
                        rule.name,
                        plan.name,
                        plan.strategy_type
                    )
                else:
                    logger.warning(
                        "CandidateGenerator: failed to generate candidate from plan '{}' (type: {})",
                        plan.name,
                        plan.strategy_type
                    )
            
            except Exception as exc:
                logger.error(
                    "CandidateGenerator: error generating candidate from plan '{}': {}",
                    plan.name,
                    exc
                )
                continue
        
        logger.info(
            "CandidateGenerator: generated {} candidates from {} plans",
            len(candidates),
            len(sorted_plans)
        )
        
        return candidates
    
    def _generate_candidate(
        self,
        plan: StrategyPlan,
        context: Dict[str, Any]
    ) -> Optional[RuleWithMeta]:
        """Generate single candidate based on strategy type.
        
        Args:
            plan: Strategy plan
            context: Generation context
        
        Returns:
            Generated rule or None if generation fails
        """
        strategy_type = plan.strategy_type.lower()
        
        if strategy_type == "generate":
            return self._generate_from_scratch(plan, context)
        elif strategy_type == "crossover":
            return self._generate_from_crossover(plan, context)
        elif strategy_type == "mutation":
            return self._generate_from_mutation(plan, context)
        else:
            logger.error(
                "CandidateGenerator: unknown strategy_type '{}'",
                strategy_type
            )
            return None
    
    def _generate_from_scratch(
        self,
        plan: StrategyPlan,
        context: Dict[str, Any]
    ) -> Optional[RuleWithMeta]:
        """Generate candidate from scratch using LLMCoder.
        
        Args:
            plan: Strategy plan
            context: Generation context
        
        Returns:
            Generated rule or None if generation fails
        """
        try:
            model_summary = context.get("model_summary", {})
            obs_example = context.get("obs_example", {})
            baseline_name = context.get("baseline_name", "SPT")
            objective_metric = context.get("objective_metric", "makespan")

            rule = None

            # Backward compatibility: older LLMCoder interface
            build_single = getattr(self._llm_coder, "build_candidate_rule", None)
            if callable(build_single):
                try:
                    rule = build_single(
                        model_summary=model_summary,
                        obs_example=obs_example,
                        baseline_name=baseline_name,
                        objective_metric=objective_metric,
                        plan=plan,
                    )
                except TypeError:
                    rule = build_single(
                        model_summary=model_summary,
                        obs_example=obs_example,
                        baseline_name=baseline_name,
                        objective_metric=objective_metric,
                    )
            else:
                # Newer interface: build candidates from plans
                candidates = self._llm_coder.build_candidates_from_plans(
                    model_summary=model_summary,
                    obs_example=obs_example,
                    baseline_name=baseline_name,
                    plans=[plan],  # Pass as list
                    objective_metric=objective_metric
                )
                # Extract first candidate from list
                if isinstance(candidates, list) and candidates:
                    rule = candidates[0]
            
            if rule is not None:
                # Mark source as llm_generated
                rule.info["source"] = "llm_generated"
                
                # Add genealogy for generated rule
                if "genealogy" not in rule.info:
                    rule.info["genealogy"] = {
                        "rule_id": rule.info.get("rule_id", ""),
                        "parent_ids": [],
                        "operation": "generated",
                        "generation": 0
                    }
            
            return rule
        
        except Exception as exc:
            logger.error("CandidateGenerator: generate from scratch failed: {}", exc)
            return None
    
    def _generate_from_crossover(
        self,
        plan: StrategyPlan,
        context: Dict[str, Any]
    ) -> Optional[RuleWithMeta]:
        """Generate candidate from crossover.
        
        Args:
            plan: Strategy plan
            context: Generation context
        
        Returns:
            Generated rule or None if generation fails
        """
        try:
            iteration_pool = context.get("iteration_pool", [])
            
            if len(iteration_pool) < 2:
                logger.warning(
                    "CandidateGenerator: insufficient rules for crossover ({} < 2), skipping",
                    len(iteration_pool)
                )
                return None
            
            def _norm(s: Any) -> str:
                return str(s).strip()

            def _find_rule_by_name_or_id(token: str) -> Optional[RuleWithMeta]:
                t = str(token).strip()
                if not t:
                    return None
                for r in iteration_pool:
                    try:
                        info = getattr(r, "info", {}) or {}
                    except Exception:
                        info = {}
                    rid = None
                    if isinstance(info, dict):
                        gen = info.get("genealogy")
                        if isinstance(gen, dict):
                            rid = gen.get("rule_id")
                    if str(getattr(r, "name", "")) == t:
                        return r
                    if rid and str(rid) == t:
                        return r
                # Case-insensitive name match
                tl = t.lower()
                for r in iteration_pool:
                    if str(getattr(r, "name", "")).lower() == tl:
                        return r
                return None

            def _infer_parent_tokens_from_plan() -> List[str]:
                tokens: List[str] = []
                meta = getattr(plan, "meta", {}) or {}
                if isinstance(meta, dict):
                    for k in ["parent1_id", "parent2_id", "parent1", "parent2", "parent_a", "parent_b"]:
                        if k in meta and meta.get(k):
                            tokens.append(_norm(meta.get(k)))
                # parent_id may be used for targeted crossover; allow comma/semicolon separation
                if getattr(plan, "parent_id", None):
                    raw = _norm(getattr(plan, "parent_id"))
                    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
                    tokens.extend(parts)
                # Heuristic: parse plan.name for known rule names (e.g., 'ATC-SPT_Crossover_MinMakespan')
                try:
                    name = _norm(getattr(plan, "name", ""))
                except Exception:
                    name = ""
                if name:
                    # split by common separators
                    parts = [p for p in re.split(r"[^A-Za-z0-9_-]+", name) if p]
                    # Further split by '-' and '_'
                    subparts: List[str] = []
                    for p in parts:
                        subparts.extend([x for x in p.replace("-", "_").split("_") if x])
                    tokens.extend(subparts)
                # As last resort, scan parent_selection_criteria for explicit names
                if getattr(plan, "parent_selection_criteria", None):
                    crit = _norm(getattr(plan, "parent_selection_criteria"))
                    if crit:
                        # Split by comma/space; keep words
                        tokens.extend([p.strip() for p in re.split(r"[\s,;]+", crit) if p.strip()])
                # Keep order, unique
                seen: set[str] = set()
                out: List[str] = []
                for t in tokens:
                    if not t:
                        continue
                    if t in seen:
                        continue
                    seen.add(t)
                    out.append(t)
                return out

            # Select parents: prefer LLM-specified parents in plan
            parent_candidates: List[RuleWithMeta] = []
            parent_tokens = _infer_parent_tokens_from_plan()
            for tok in parent_tokens:
                r = _find_rule_by_name_or_id(tok)
                if r is None:
                    continue
                if all(rr.name != r.name for rr in parent_candidates):
                    parent_candidates.append(r)
                if len(parent_candidates) >= 2:
                    break

            if len(parent_candidates) >= 2:
                parent1, parent2 = parent_candidates[0], parent_candidates[1]
                logger.info(
                    "CandidateGenerator: selected parents from plan '{}' -> '{}' and '{}'",
                    plan.name,
                    parent1.name,
                    parent2.name,
                )
            else:
                # Fallback to ParentSelector (tournament / criteria-based)
                criteria = None
                if plan.parent_selection_criteria:
                    criteria = {"criteria": plan.parent_selection_criteria}
                parent1, parent2 = self._parent_selector.select_for_crossover(
                    iteration_pool,
                    criteria
                )
                logger.info(
                    "CandidateGenerator: selected parents by fallback selection for plan '{}' -> '{}' and '{}'",
                    plan.name,
                    parent1.name,
                    parent2.name,
                )
            
            logger.info(
                "CandidateGenerator: selected parents for crossover: '{}' and '{}'",
                parent1.name,
                parent2.name
            )
            
            # Apply crossover
            offspring = self._crossover_op.apply([parent1, parent2], context)
            
            if offspring is not None:
                # Mark source as crossover
                offspring.info["source"] = "crossover"
                
                # Ensure genealogy is set
                if "genealogy" not in offspring.info:
                    parent1_gen = parent1.info.get("genealogy", {}).get("generation", 0)
                    parent2_gen = parent2.info.get("genealogy", {}).get("generation", 0)
                    
                    offspring.info["genealogy"] = {
                        "rule_id": offspring.info.get("rule_id", ""),
                        "parent_ids": [
                            parent1.info.get("genealogy", {}).get("rule_id", parent1.name),
                            parent2.info.get("genealogy", {}).get("rule_id", parent2.name)
                        ],
                        "operation": "crossover",
                        "generation": max(parent1_gen, parent2_gen) + 1
                    }
            
            return offspring
        
        except Exception as exc:
            logger.error("CandidateGenerator: crossover failed: {}", exc)
            return None
    
    def _generate_from_mutation(
        self,
        plan: StrategyPlan,
        context: Dict[str, Any]
    ) -> Optional[RuleWithMeta]:
        """Generate candidate from mutation.
        
        Args:
            plan: Strategy plan
            context: Generation context
        
        Returns:
            Generated rule or None if generation fails
        """
        try:
            iteration_pool = context.get("iteration_pool", [])
            
            if len(iteration_pool) < 1:
                logger.warning(
                    "CandidateGenerator: no rules available for mutation, skipping"
                )
                return None
            
            # Select parent
            parent = self._parent_selector.select_for_mutation(
                iteration_pool,
                parent_id=plan.parent_id
            )
            
            logger.info(
                "CandidateGenerator: selected parent for mutation: '{}'",
                parent.name
            )
            
            # Add mutation focus to context if specified
            if plan.mutation_focus:
                context["mutation_focus"] = plan.mutation_focus
            
            # Apply mutation
            offspring = self._mutation_op.apply([parent], context)
            
            if offspring is not None:
                # Mark source as mutation
                offspring.info["source"] = "mutation"
                
                # Ensure genealogy is set
                if "genealogy" not in offspring.info:
                    parent_gen = parent.info.get("genealogy", {}).get("generation", 0)
                    
                    offspring.info["genealogy"] = {
                        "rule_id": offspring.info.get("rule_id", ""),
                        "parent_ids": [
                            parent.info.get("genealogy", {}).get("rule_id", parent.name)
                        ],
                        "operation": "mutation",
                        "generation": parent_gen + 1
                    }
            
            return offspring
        
        except Exception as exc:
            logger.error("CandidateGenerator: mutation failed: {}", exc)
            return None
    
    def _sort_plans(self, plans: List[StrategyPlan]) -> List[StrategyPlan]:
        """Sort plans: generate first, then crossover/mutation.
        
        This ensures that newly generated rules can be used as parents
        for subsequent crossover/mutation operations.
        
        Args:
            plans: List of strategy plans
        
        Returns:
            Sorted list of plans
        """
        generate_plans = []
        crossover_plans = []
        mutation_plans = []
        
        for plan in plans:
            strategy_type = plan.strategy_type.lower()
            if strategy_type == "generate":
                generate_plans.append(plan)
            elif strategy_type == "crossover":
                crossover_plans.append(plan)
            elif strategy_type == "mutation":
                mutation_plans.append(plan)
            else:
                # Unknown type, treat as generate
                logger.warning(
                    "CandidateGenerator: unknown strategy_type '{}', treating as generate",
                    strategy_type
                )
                generate_plans.append(plan)
        
        # Concatenate: generate first, then crossover, then mutation
        sorted_plans = generate_plans + crossover_plans + mutation_plans
        
        logger.debug(
            "CandidateGenerator: sorted {} plans (generate: {}, crossover: {}, mutation: {})",
            len(sorted_plans),
            len(generate_plans),
            len(crossover_plans),
            len(mutation_plans)
        )
        
        return sorted_plans
