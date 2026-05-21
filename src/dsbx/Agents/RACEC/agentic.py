from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from dsbx.Agents.utils import LLMClient
from dsbx.Eval.Metrics import METRIC_ALL_KEYS
from .config import LLMCoderConfig
from .feedback import FeedbackHistory, IterationFeedback
from .rules import RuleWithMeta
from .sandbox_eval import EvalResult
from .baseline_heuristics import BaselineHeuristicLibrary


_VALID_METRICS_SET = {str(x) for x in METRIC_ALL_KEYS}


def _sanitize_focus_metrics(raw: Any, *, fallback_metric: str) -> List[str]:
    focus: List[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                focus.append(item.strip())
            elif isinstance(item, (int, float)):
                focus.append(str(item))
    elif isinstance(raw, str):
        parts = [p.strip() for p in raw.replace(";", ",").split(",")]
        focus.extend([p for p in parts if p])
    filtered: List[str] = []
    seen: set[str] = set()
    for m in focus:
        if not m:
            continue
        if m not in _VALID_METRICS_SET:
            continue
        if m in seen:
            continue
        seen.add(m)
        filtered.append(m)
    if not filtered:
        return [str(fallback_metric)]
    return filtered


def _extract_json_object(text: str) -> str:
    s = str(text).strip()
    if s.startswith("```"):
        idx = s.find("\n")
        if idx != -1:
            s = s[idx + 1 :]
    if s.rstrip().endswith("```"):
        s = s.rstrip()
        end_idx = s.rfind("```")
        if end_idx != -1:
            s = s[:end_idx].rstrip()
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start : end + 1]
    return s


@dataclass
class StrategyPlan:
    name: str
    description: str
    focus_metrics: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
    # Evolutionary operator fields
    strategy_type: str = "generate"  # One of: "generate", "crossover", "mutation"
    parent_selection_criteria: Optional[str] = None  # e.g., "high_fitness", "diverse", "specific_id"
    parent_id: Optional[str] = None  # Specific parent rule ID for mutation or targeted crossover
    mutation_focus: Optional[str] = None  # Focus area for mutation, e.g., "priority_weights", "machine_selection"

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "name": self.name,
            "description": self.description,
            "focus_metrics": list(self.focus_metrics),
            "constraints": dict(self.constraints),
            "meta": dict(self.meta),
            "strategy_type": self.strategy_type,
        }
        # Include optional fields only if they are set
        if self.parent_selection_criteria is not None:
            result["parent_selection_criteria"] = self.parent_selection_criteria
        if self.parent_id is not None:
            result["parent_id"] = self.parent_id
        if self.mutation_focus is not None:
            result["mutation_focus"] = self.mutation_focus
        return result


@dataclass
class CriticFeedback:
    candidate_index: int
    candidate_name: str
    verdict: str
    reason: str = ""
    suggested_changes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidateRecord:
    index: int
    rule: RuleWithMeta
    plan: Optional[StrategyPlan] = None
    iteration: int = 0
    eval_result: Optional[EvalResult] = None
    feedback: Optional[CriticFeedback] = None


@dataclass
class CriticResult:
    continue_iterations: bool
    feedbacks: List[CriticFeedback] = field(default_factory=list)


@dataclass
class TaskMemory:
    candidates: List[CandidateRecord] = field(default_factory=list)
    best_candidate_index: Optional[int] = None
    iteration: int = 0

    def add_candidates(self, records: List[CandidateRecord]) -> None:
        self.candidates.extend(records)

    def update_best_by_score(self, scores: Dict[int, float]) -> Optional[CandidateRecord]:
        best_idx: Optional[int] = None
        best_score = float("-inf")
        for rec in self.candidates:
            idx = rec.index
            s = scores.get(idx)
            if s is None:
                continue
            if s > best_score:
                best_score = s
                best_idx = idx
        self.best_candidate_index = best_idx
        if best_idx is None:
            return None
        for rec in self.candidates:
            if rec.index == best_idx:
                return rec
        return None


class PlannerAgent:
    def __init__(self, llm_client: LLMClient, cfg: LLMCoderConfig) -> None:
        self._client = llm_client
        self._cfg = cfg

    def _format_feedback_for_prompt(self, feedback_list: List[IterationFeedback]) -> str:
        """Format feedback history for inclusion in planning prompt.
        
        Args:
            feedback_list: List of recent feedback entries
            
        Returns:
            Formatted string describing feedback from previous iterations
        """
        if not feedback_list:
            return ""
        
        lines = ["Previous iteration feedback:"]
        for fb in feedback_list:
            lines.append(f"- Iteration {fb.iteration}, Candidate '{fb.candidate_name}':")
            lines.append(f"  Verdict: {fb.verdict}")
            lines.append(f"  Reason: {fb.reason}")
            if fb.metrics:
                metrics_str = ", ".join([f"{k}={v:.4f}" for k, v in fb.metrics.items() if v is not None])
                if metrics_str:  # Only add if there are non-None metrics
                    lines.append(f"  Metrics: {metrics_str}")
            if fb.suggested_changes:
                lines.append(f"  Suggested changes: {json.dumps(fb.suggested_changes)}")
        
        return "\n".join(lines)

    def plan_strategies(
        self,
        model_summary: Dict[str, Any],
        obs_example: Dict[str, Any],
        baseline_name: str,
        history: Optional[Dict[str, Any]] = None,
        feedback_history: Optional[FeedbackHistory] = None,
        objective_metric: Optional[str] = None,
        baseline_code: Optional[str] = None,
        repository_rules_info: Optional[Dict[str, Any]] = None,
        similar_rules_info: Optional[Dict[str, Any]] = None,
    ) -> List[StrategyPlan]:
        max_plans = int(getattr(self._cfg, "agentic_max_plans", 1))
        if max_plans <= 0:
            max_plans = 1
        metric_main = (
            str(objective_metric)
            if objective_metric is not None
            else str(getattr(self._cfg, "objective_metric", "makespan"))
        )

        # Backward compatibility: older callers used similar_rules_info
        if repository_rules_info is None and similar_rules_info is not None:
            repository_rules_info = similar_rules_info
        objective_mode = str(getattr(self._cfg, "objective_mode", "min"))
        valid_metrics_text = ", ".join([str(x) for x in METRIC_ALL_KEYS])
        obs_payload = obs_example if isinstance(obs_example, dict) else {}
        state_profile = (
            obs_payload.get("state_profile") if isinstance(obs_payload.get("state_profile"), dict) else obs_payload
        )
        state_profile_window = (
            obs_payload.get("state_profile_window") if isinstance(obs_payload.get("state_profile_window"), dict) else {}
        )
        action_sample = obs_payload.get("action_sample") if isinstance(obs_payload.get("action_sample"), list) else []
        
        # Format feedback from previous iterations
        feedback_summary = ""
        if feedback_history is not None and feedback_history:
            recent_feedback = feedback_history.get_recent(5)
            if recent_feedback:
                feedback_summary = self._format_feedback_for_prompt(recent_feedback)
        
        payload: Dict[str, Any] = {
            "state_profile": state_profile,
            "state_profile_window": state_profile_window,
            "action_sample": action_sample,
            "baseline_name": baseline_name,
            "history": history or {},
            "max_plans": max_plans,
            "objective_metric": metric_main,
            "objective_mode": objective_mode,
        }
        prompt = (
            "You are an expert production scheduler for dynamic job shops.\n"
            "You must propose dispatching strategy plans (high-level ideas, not code).\n\n"
            "High-level scheduling objectives:\n"
            "- Keep overall completion time (makespan) and total/average flow time small.\n"
            "- Minimize tardy jobs and their total/weighted tardiness, and avoid unnecessary job cancellations.\n"
            "- Maintain high but well-balanced machine utilization, avoiding extreme queues or severely overloaded bottlenecks.\n"
            "- Avoid excessive rescheduling and large, unnecessary shifts of planned start times unless reacting to important disturbances.\n\n"
            "Environment and interface (DynaSchedBench single-agent environment):\n"
            "- The observation dict `obs` has keys such as 'time', 'ready_ops', 'machines', 'emergency_jobs', 'down_machines'.\n"
            "- Each element in obs['ready_ops'] represents an operation with fields: job_id, operation (op index), machine_group, process_time, "
            "remaining_work, remaining_ops, flexibility, priority.\n"
            "- obs['machines'] maps machine_id to the time when the machine becomes available (smaller means earlier availability).\n"
            "- Each scheduling action has the form action = {\"job_id\": <int>, \"machine_group\": <str>, \"machine_id\": <str>, \"machine_candidates\": <list>}.\n\n"
        )
        
        # Include current baseline strategy code
        if baseline_code:
            prompt += (
                f"Current Baseline Strategy Implementation ('{baseline_name}'):\n"
                "The following is the Python implementation of the current baseline strategy that you should try to improve upon.\n"
                "Study this implementation to understand the current approach, then propose plans that can enhance or extend it.\n\n"
                f"```python\n{baseline_code}\n```\n\n"
            )
        elif baseline_name:
            # Fallback: try to get code from BaselineHeuristicLibrary
            fallback_code = BaselineHeuristicLibrary.get_heuristic_code(baseline_name)
            if fallback_code:
                prompt += (
                    f"Current Baseline Strategy Implementation ('{baseline_name}'):\n"
                    "The following is the Python implementation of the current baseline strategy that you should try to improve upon.\n"
                    "Study this implementation to understand the current approach, then propose plans that can enhance or extend it.\n\n"
                    f"```python\n{fallback_code}\n```\n\n"
                )
        
        # Include feedback summary if available
        if feedback_summary:
            prompt += (
                "Feedback from previous iterations:\n"
                f"{feedback_summary}\n\n"
                "Please consider this feedback when proposing new strategy plans. "
                "Learn from rejected candidates and build upon successful patterns.\n\n"
            )
        
        # Include repository information for evolutionary strategies
        if repository_rules_info and isinstance(repository_rules_info, dict):
            count = repository_rules_info.get("count", 0)
            avg_fitness = repository_rules_info.get("avg_fitness", 0.0)
            top_strategies = repository_rules_info.get("top_strategies", [])
            diversity = repository_rules_info.get("diversity", 0.0)
            
            if count > 0:
                prompt += (
                    "Available Parent Rules in Repository:\n"
                    f"- Count: {count} rules similar to current instance\n"
                    f"- Average fitness: {avg_fitness if avg_fitness is not None else 0.0:.4f}\n"
                )
                if top_strategies:
                    strategies_str = ", ".join([f"'{s}'" for s in top_strategies[:5]])
                    prompt += f"- Top strategies: {strategies_str}\n"
                prompt += f"- Population diversity: {diversity if diversity is not None else 0.5:.4f}\n\n"
                
                # Add detailed rule summaries if available
                all_rules = repository_rules_info.get("all_rules", [])
                if all_rules:
                    from .rule_summarizer import format_rules_for_prompt, create_parent_selection_guidance
                    
                    # Format rules (limit to top 10, no code snippets to save tokens)
                    rules_summary = format_rules_for_prompt(
                        all_rules,
                        max_rules=10,
                        include_code_snippets=False,
                        sort_by_fitness=True
                    )
                    
                    prompt += (
                        "Detailed Rule Summaries (Top 10 by Fitness):\n"
                        f"{rules_summary}\n"
                    )
                    
                    # Add parent selection guidance
                    guidance = create_parent_selection_guidance(all_rules, max_suggestions=3)
                    if guidance:
                        prompt += (
                            "Parent Selection Guidance:\n"
                            f"{guidance}\n\n"
                        )
                
                prompt += (
                    "Strategy Types:\n"
                    "You can now propose three types of strategies:\n"
                    "1. 'generate': Create new rule from scratch using LLM (always available)\n"
                    "2. 'crossover': Combine features from 2 parent rules (available when repository has >= 2 rules)\n"
                    "   - Use 'parent_selection_criteria' to specify desired parent characteristics (e.g., 'high_fitness', 'complementary_features', 'different_generations')\n"
                    "   - The system will select 2 distinct parents based on your criteria\n"
                    "   - You can also specify specific rule names to use as parents\n"
                    "3. 'mutation': Modify an existing parent rule (available when repository has >= 1 rule)\n"
                    "   - Optionally use 'parent_id' to specify a specific rule to mutate (use rule name or ID from summaries above)\n"
                    "   - Use 'mutation_focus' to describe what aspect to modify (e.g., 'slack_time_calculation', 'emergency_handling', 'machine_selection')\n\n"
                    
                    "Guidelines for Strategy Selection:\n"
                    "- Use 'generate' when exploring new approaches or when repository is small\n"
                    "- Use 'crossover' when combining complementary strategies (e.g., critical-path + emergency handling)\n"
                    "  * Look for rules with different feature sets that could complement each other\n"
                    "  * Consider combining high-fitness rules from different generations\n"
                    "  * You can specify which rules to use as parents by their names\n"
                    "- Use 'mutation' when fine-tuning a promising strategy from the repository\n"
                    "  * Target high-fitness rules for incremental improvements\n"
                    "  * Focus mutations on specific aspects (e.g., weight adjustments, threshold tuning)\n"
                    "- You can propose a mix of strategy types in a single iteration\n"
                    "- When proposing crossover/mutation, reference specific rules from the summaries above\n"
                    "- The LLM will decide which rules to use based on your criteria and the available rules\n\n"
                )
        
        prompt += (
            "Your task:\n"
            "- Propose up to max_plans strategy plans that can improve or match the baseline.\n"
            "- Each plan should describe how to prioritize actions at decision points in high-level terms.\n"
            f"- Plans should focus on improving metric '{metric_main}' (objective_mode='{objective_mode}'), and may reference additional metrics when useful.\n"
            "- If you include focus_metrics, they must be chosen from the valid metric keys list below.\n\n"
            f"Valid metric keys: {valid_metrics_text}\n\n"
            "Output format:\n"
            "- You must reply with a single JSON object only.\n"
            "- The object must contain a field 'plans' which is a list of objects.\n"
            "- Each plan object must contain: 'name' (string), 'description' (string), 'focus_metrics' (list of strings), and 'constraints' (object).\n"
            "- Each plan object must also contain: 'strategy_type' (string: 'generate', 'crossover', or 'mutation').\n"
            "- For 'crossover' plans, optionally include 'parent_selection_criteria' (string describing desired parent characteristics).\n"
            "- For 'mutation' plans, optionally include 'parent_id' (string: specific rule name or ID) and 'mutation_focus' (string describing what to modify).\n"
            "- Do not include any text outside JSON.\n\n"
            "Provided context (JSON object named CONTEXT):\n"
            "- 'state_profile': compressed summary of the current scheduling state, including statistics over 'ready_ops', 'machines', and 'dynamic_summary' (with counts such as 'down_machines', 'emergency_jobs', and event-type counts in 'event_counters_top').\n"
            "- 'state_profile_window': windowed summary over recent decision points, with 'window_size', 'sampled' (time-series samples of 'scalars' at different times), and 'scalar_stats' (min/max/mean/std/p50/p90 for each scalar key).\n"
            "- 'action_sample': small sample of current legal actions with fields like 'job_id', 'machine_group', 'machine_candidates_total', 'machine_candidates', 'process_time', 'remaining_work', 'remaining_ops', 'flexibility', 'priority', and optional 'baseline_score' from the baseline rule.\n"
            "- 'baseline_name': name of the heuristic baseline rule you should try to match or improve.\n"
            "- 'history': optional summary of recent planning and evaluation outcomes (may be empty).\n"
            "- 'max_plans': maximum number of strategy plans you are allowed to output.\n"
            "- 'objective_metric': primary optimization metric (one of the valid metric keys listed above).\n"
            "- 'objective_mode': whether the objective metric should be minimized or maximized (e.g., 'min' or 'max').\n\n"
            f"CONTEXT = {json.dumps(payload, ensure_ascii=False)}\n"
        )
        logger.debug(
            "PlannerAgent DEBUG: full prompt:\n{}\n<<END_PROMPT>>",
            prompt,
        )
        max_prompt_preview = 500
        prompt_preview = prompt[:max_prompt_preview]
        if len(prompt) > max_prompt_preview:
            prompt_preview = prompt_preview + "..."
        logger.info(
            "PlannerAgent: prompt preview (first {} chars):\n{}",
            max_prompt_preview,
            prompt_preview,
        )
        max_attempts = 2
        attempt = 0
        prompt_current = prompt

        # Build a whitelist of valid parent identifiers exposed to the LLM.
        # If the LLM proposes a parent_id outside this set, we drop it and
        # fallback to fitness-based parent selection.
        allowed_parent_ids: set[str] = set()
        try:
            if isinstance(repository_rules_info, dict):
                all_rules = repository_rules_info.get("all_rules", [])
                if isinstance(all_rules, list):
                    for r in all_rules:
                        if not isinstance(r, dict):
                            continue
                        rn = r.get("name")
                        rid = r.get("rule_id")
                        if isinstance(rn, str) and rn:
                            allowed_parent_ids.add(rn)
                        if isinstance(rid, str) and rid:
                            allowed_parent_ids.add(rid)
        except Exception:
            allowed_parent_ids = set()
        while attempt < max_attempts:
            outs = self._client.generate(
                prompt_current,
                n=1,
                temperature=float(getattr(self._cfg, "planner_temperature", 0.2)),
                top_p=self._cfg.llm_top_p,
                top_k=self._cfg.llm_top_k,
                timeout=self._cfg.llm_timeout,
                response_format={"type": "json_object"},
            )
            if not outs:
                return []
            raw = outs[0]
            max_raw_preview = 500
            raw_preview = raw[:max_raw_preview]
            if len(raw) > max_raw_preview:
                raw_preview = raw_preview + "..."
            logger.info(
                "PlannerAgent: first raw LLM output preview (attempt {}/{}; first {} chars):\n{}",
                attempt + 1,
                max_attempts,
                max_raw_preview,
                raw_preview,
            )
            logger.debug(
                "PlannerAgent DEBUG: full raw LLM output (attempt {}):\n{}\n<<END_OUTPUT>>",
                attempt + 1,
                raw,
            )
            try:
                obj = json.loads(raw)
            except Exception:
                try:
                    cleaned = _extract_json_object(raw)
                    obj = json.loads(cleaned)
                except Exception:
                    logger.error("PlannerAgent: failed to parse JSON from LLM output (attempt {} of {})", attempt + 1, max_attempts)
                    attempt += 1
                    if attempt >= max_attempts:
                        return []
                    prompt_current = (
                        prompt
                        + "\n\nThe previous response could not be parsed as JSON or did not match the required schema. "
                        + "You MUST now respond with a single valid JSON object exactly of the form "
                        + "{\"plans\": [{\"name\": \"...\", \"description\": \"...\", \"focus_metrics\": [\"...\"], \"constraints\": {...}}]} "
                        + "with no extra text, comments, or markdown fences."
                    )
                    continue
            plans_obj = obj.get("plans")
            if not isinstance(plans_obj, list):
                logger.error("PlannerAgent: JSON does not contain a 'plans' list (attempt {} of {})", attempt + 1, max_attempts)
                attempt += 1
                if attempt >= max_attempts:
                    return []
                prompt_current = (
                    prompt
                    + "\n\nThe previous response did not contain a valid 'plans' list. "
                    + "You MUST now respond with a single valid JSON object exactly of the form "
                    + "{\"plans\": [{\"name\": \"...\", \"description\": \"...\", \"focus_metrics\": [\"...\"], \"constraints\": {...}}]} "
                    + "with no extra text, comments, or markdown fences."
                )
                continue
            plans: List[StrategyPlan] = []
            for p in plans_obj:
                if not isinstance(p, dict):
                    continue
                name = p.get("name")
                desc = p.get("description")
                if not isinstance(name, str) or not isinstance(desc, str):
                    continue
                focus = _sanitize_focus_metrics(
                    p.get("focus_metrics"),
                    fallback_metric=metric_main,
                )
                constraints = p.get("constraints") or {}
                meta: Dict[str, Any] = {}
                if not isinstance(constraints, dict):
                    constraints = {}
                
                # Parse evolutionary operator fields
                strategy_type = str(p.get("strategy_type", "generate")).strip().lower()
                
                # Validate strategy_type
                valid_strategy_types = {"generate", "crossover", "mutation"}
                if strategy_type not in valid_strategy_types:
                    logger.warning(
                        "PlannerAgent: invalid strategy_type '{}', defaulting to 'generate'",
                        strategy_type
                    )
                    strategy_type = "generate"
                
                # Parse optional fields
                parent_selection_criteria = p.get("parent_selection_criteria")
                if parent_selection_criteria is not None:
                    parent_selection_criteria = str(parent_selection_criteria)
                
                parent_id = p.get("parent_id")
                if parent_id is not None:
                    parent_id = str(parent_id)

                if (
                    parent_id
                    and strategy_type == "mutation"
                    and allowed_parent_ids
                    and parent_id not in allowed_parent_ids
                ):
                    logger.debug(
                        "PlannerAgent: dropping unknown parent_id '{}' (not in repository summaries); falling back to fitness-based selection",
                        parent_id,
                    )
                    parent_id = None
                
                mutation_focus = p.get("mutation_focus")
                if mutation_focus is not None:
                    mutation_focus = str(mutation_focus)
                
                plan = StrategyPlan(
                    name=str(name),
                    description=str(desc),
                    focus_metrics=list(focus),
                    constraints=dict(constraints),
                    meta=meta,
                    strategy_type=strategy_type,
                    parent_selection_criteria=parent_selection_criteria,
                    parent_id=parent_id,
                    mutation_focus=mutation_focus,
                )
                plans.append(plan)
                if len(plans) >= max_plans:
                    break
            return plans


class CriticAgent:
    def __init__(self, llm_client: LLMClient, cfg: LLMCoderConfig) -> None:
        self._client = llm_client
        self._cfg = cfg

    def analyze(
        self,
        baseline_name: str,
        model_summary: Dict[str, Any],
        candidate_summaries: List[Dict[str, Any]],
        history: Optional[Dict[str, Any]] = None,
        feedback_history: Optional[FeedbackHistory] = None,
        objective_metric: Optional[str] = None,
    ) -> CriticResult:
        if not candidate_summaries:
            return CriticResult(continue_iterations=False, feedbacks=[])
        eval_accepted_by_index: Dict[int, bool] = {}
        for c in candidate_summaries:
            if not isinstance(c, dict):
                continue
            idx = c.get("index")
            if not isinstance(idx, int):
                continue
            ev = c.get("eval")
            if isinstance(ev, dict):
                eval_accepted_by_index[idx] = bool(ev.get("accepted", False))
        metric_main = (
            str(objective_metric)
            if objective_metric is not None
            else str(getattr(self._cfg, "objective_metric", "makespan"))
        )
        objective_mode = str(getattr(self._cfg, "objective_mode", "min"))
        payload: Dict[str, Any] = {
            "baseline_name": baseline_name,
            "model_summary": model_summary,
            "candidates": candidate_summaries,
            "history": history or {},
            "objective_metric": metric_main,
            "objective_mode": objective_mode,
        }
        prompt = (
            "You are a critical evaluator for dynamic scheduling rules in a dynamic job shop.\n\n"
            "High-level scheduling objectives:\n"
            "- Keep overall completion time (makespan) and total/average flow time small.\n"
            "- Minimize tardy jobs and their total/weighted tardiness, and avoid unnecessary job cancellations.\n"
            "- Maintain high but well-balanced machine utilization, avoiding extreme queues or severely overloaded bottlenecks.\n"
            "- Avoid excessive rescheduling and large, unnecessary shifts of planned start times unless reacting to important disturbances.\n\n"
            "Environment and interface (DynaSchedBench single-agent environment):\n"
            "- The observation dict `obs` has keys such as 'time', 'ready_ops', 'machines', 'emergency_jobs', 'down_machines'.\n"
            "- Each element in obs['ready_ops'] represents an operation with fields: job_id, operation (op index), machine_group, process_time, "
            "remaining_work, remaining_ops, flexibility, priority.\n"
            "- obs['machines'] maps machine_id to the time when the machine becomes available (smaller means earlier availability).\n"
            "- Each scheduling action has the form action = {\"job_id\": <int>, \"machine_group\": <str>, \"machine_id\": <str>, \"machine_candidates\": <list>}.\n\n"
            "Your task:\n"
            "- You will receive several candidate dispatching rules and their sandbox evaluation results compared to a baseline rule.\n"
            "- The primary objective metric is given in CONTEXT (objective_metric, objective_mode).\n"
            "- Decide whether each candidate should be accepted, rejected, or refined, and whether the search should continue.\n"
            "- **CRITICAL**: For candidates that need refinement, provide SPECIFIC, ACTIONABLE feedback that the planner can use to generate better strategies.\n\n"
            "Important constraints:\n"
            "- You MUST treat candidate.eval.accepted (sandbox evaluation result) as authoritative.\n"
            "- You MUST output verdict='accept' ONLY IF candidate.eval.accepted is true.\n"
            "- If candidate.eval.accepted is false but the candidate looks promising, output verdict='refine' and provide suggested_changes.\n\n"
            "Providing Actionable Feedback:\n"
            "When verdict='refine', your suggested_changes MUST include SPECIFIC guidance:\n"
            "1. **strategy_insights**: What aspects of the strategy worked well or poorly?\n"
            "   - Example: 'The rule prioritizes short jobs well but ignores machine utilization balance'\n"
            "   - Example: 'Critical path awareness helps but needs better handling of bottleneck machines'\n"
            "2. **concrete_improvements**: Specific changes to make in the next iteration\n"
            "   - Example: 'Add machine utilization factor: prefer machines with lower queue length'\n"
            "   - Example: 'Increase weight on remaining_work from 0.3 to 0.5-0.6'\n"
            "   - Example: 'Add emergency job detection: boost priority by 2x when job has emergency flag'\n"
            "3. **feature_suggestions**: Specific features or factors to add/remove/adjust\n"
            "   - Example: 'Add: machine_available_time / current_time ratio'\n"
            "   - Example: 'Remove: operation_index (not helping)'\n"
            "   - Example: 'Adjust: process_time weight from 0.2 to 0.4'\n"
            "4. **avoid_patterns**: What NOT to do based on observed failures\n"
            "   - Example: 'Avoid: pure FIFO ordering - leads to poor makespan'\n"
            "   - Example: 'Avoid: ignoring machine_group flexibility - causes bottlenecks'\n\n"
            "Examples of GOOD vs BAD feedback:\n"
            "❌ BAD: 'Increase exploration by adopting a blended approach' (too vague)\n"
            "✅ GOOD: 'Add blended score: 0.6 * remaining_work + 0.4 * (1/process_time) to prioritize both work completion and fast jobs'\n\n"
            "❌ BAD: 'Experiment with machine_group prioritization' (unclear what to do)\n"
            "✅ GOOD: 'When multiple machine_groups available, prefer group with lowest average queue length (sum of waiting jobs)'\n\n"
            "❌ BAD: 'Apply similar hybridization' (not specific)\n"
            "✅ GOOD: 'Combine SPT (shortest processing time) with remaining_ops: score = -process_time + 2.0 * remaining_ops'\n\n"
            "Iteration control:\n"
            "- You should be OPTIMISTIC about continuing iterations to explore more possibilities.\n"
            "- You MUST output continue_iterations = false ONLY IF one of the following holds:\n"
            "  (1) CONTEXT.history.remaining_iterations <= 0 (no more iterations available), OR\n"
            "  (2) CONTEXT.history.accepted_count > 0 AND CONTEXT.history.best_relative_improvement >= CONTEXT.history.agentic_min_relative_improvement (already found a good enough candidate), OR\n"
            "  (3) You are absolutely certain that further exploration is completely hopeless (e.g., all candidates are extremely poor and show no potential for improvement).\n"
            "- Otherwise, you SHOULD output continue_iterations = true to give the planner more chances to find better strategies.\n"
            "- The improvement requirement is: best_relative_improvement >= agentic_min_relative_improvement (when objective_mode='min', larger relative_improvement is better).\n"
            "- Remember: Each iteration is an opportunity to learn from feedback and generate better candidates. Don't give up too early!\n\n"
            "Output format:\n"
            "- You must reply with a single JSON object only.\n"
            "- The object must contain: 'continue_iterations' (boolean) and 'feedback' (list of objects).\n"
            "- Each feedback object must contain:\n"
            "  * 'index' (int): candidate index\n"
            "  * 'candidate_name' (string): candidate name\n"
            "  * 'verdict' (string): one of ['accept', 'reject', 'refine']\n"
            "  * 'reason' (string): brief explanation of verdict\n"
            "  * 'suggested_changes' (object): MUST include these fields when verdict='refine':\n"
            "    - 'strategy_insights' (string): what worked/didn't work\n"
            "    - 'concrete_improvements' (list of strings): specific actionable changes\n"
            "    - 'feature_suggestions' (list of strings): specific features to add/remove/adjust\n"
            "    - 'avoid_patterns' (list of strings): what patterns to avoid\n"
            "- Do not include any text outside JSON.\n\n"
            f"CONTEXT = {json.dumps(payload, ensure_ascii=False)}\n"
        )
        logger.debug(
            "CriticAgent DEBUG: full prompt:\n{}\n<<END_PROMPT>>",
            prompt,
        )
        max_prompt_preview = 500
        prompt_preview = prompt[:max_prompt_preview]
        if len(prompt) > max_prompt_preview:
            prompt_preview = prompt_preview + "..."
        logger.info(
            "CriticAgent: prompt preview (first {} chars):\n{}",
            max_prompt_preview,
            prompt_preview,
        )
        max_attempts = 2
        attempt = 0
        prompt_current = prompt
        while attempt < max_attempts:
            outs = self._client.generate(
                prompt_current,
                n=1,
                temperature=float(getattr(self._cfg, "critic_temperature", 0.0)),
                top_p=self._cfg.llm_top_p,
                top_k=self._cfg.llm_top_k,
                timeout=self._cfg.llm_timeout,
            )
            if not outs:
                return CriticResult(continue_iterations=False, feedbacks=[])
            raw = outs[0]
            max_raw_preview = 500
            raw_preview = raw[:max_raw_preview]
            if len(raw) > max_raw_preview:
                raw_preview = raw_preview + "..."
            logger.info(
                "CriticAgent: first raw LLM output preview (attempt {}/{}; first {} chars):\n{}",
                attempt + 1,
                max_attempts,
                max_raw_preview,
                raw_preview,
            )
            logger.debug(
                "CriticAgent DEBUG: full raw LLM output (attempt {}):\n{}\n<<END_OUTPUT>>",
                attempt + 1,
                raw,
            )
            try:
                obj = json.loads(raw)
            except Exception:
                logger.error("CriticAgent: failed to parse JSON from LLM output (attempt {} of {})", attempt + 1, max_attempts)
                attempt += 1
                if attempt >= max_attempts:
                    return CriticResult(continue_iterations=False, feedbacks=[])
                prompt_current = (
                    prompt
                    + "\n\nThe previous response could not be parsed as JSON or did not match the required schema. "
                    + "You MUST now respond with a single valid JSON object exactly of the form "
                    + "{\"continue_iterations\": true_or_false, \"feedback\": [{\"index\": 0, \"candidate_name\": \"...\", \"verdict\": \"accept|reject|refine\", \"reason\": \"...\", \"suggested_changes\": {...}}]} "
                    + "with no extra text, comments, or markdown fences."
                )
                continue
            cont = obj.get("continue_iterations")
            continue_iterations = bool(cont) if isinstance(cont, bool) else False
            fb_list = obj.get("feedback")
            feedbacks: List[CriticFeedback] = []
            if isinstance(fb_list, list):
                for fb in fb_list:
                    if not isinstance(fb, dict):
                        continue
                    idx = fb.get("index")
                    name = fb.get("candidate_name")
                    verdict = fb.get("verdict")
                    reason = fb.get("reason") or ""
                    suggested = fb.get("suggested_changes") or {}
                    if not isinstance(idx, int):
                        continue
                    if not isinstance(name, str):
                        name = ""
                    if not isinstance(verdict, str):
                        verdict = ""
                    if not isinstance(reason, str):
                        reason = str(reason)
                    if not isinstance(suggested, dict):
                        suggested = {}
                    v_norm = verdict.strip().lower()
                    if v_norm == "accept" and not eval_accepted_by_index.get(idx, False):
                        logger.warning(
                            "CriticAgent: overriding verdict=accept to verdict=refine because sandbox eval accepted=false (index={}, candidate_name={})",
                            idx,
                            name,
                        )
                        verdict = "refine"
                        reason = (reason + " | ").strip() + "Overridden: sandbox eval accepted=false, so verdict cannot be accept."
                    feedbacks.append(
                        CriticFeedback(
                            candidate_index=idx,
                            candidate_name=name,
                            verdict=verdict,
                            reason=reason,
                            suggested_changes=dict(suggested),
                        )
                    )
            
            # Populate feedback history if provided
            if feedback_history is not None:
                current_iteration = history.get("iteration", 0) if history else 0
                for fb in feedbacks:
                    # Extract metrics from candidate_summaries
                    metrics: Dict[str, float] = {}
                    for c in candidate_summaries:
                        if isinstance(c, dict) and c.get("index") == fb.candidate_index:
                            eval_data = c.get("eval")
                            if isinstance(eval_data, dict):
                                metrics_data = eval_data.get("metrics")
                                if isinstance(metrics_data, dict):
                                    # Extract numeric metrics
                                    for key, value in metrics_data.items():
                                        if isinstance(value, (int, float)):
                                            metrics[key] = float(value)
                            break
                    
                    # Create and add IterationFeedback
                    iteration_feedback = IterationFeedback(
                        iteration=current_iteration,
                        candidate_name=fb.candidate_name,
                        verdict=fb.verdict,
                        reason=fb.reason,
                        suggested_changes=fb.suggested_changes,
                        metrics=metrics,
                    )
                    feedback_history.add_feedback(iteration_feedback)
            
            return CriticResult(continue_iterations=continue_iterations, feedbacks=feedbacks)
