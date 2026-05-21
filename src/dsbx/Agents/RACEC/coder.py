from __future__ import annotations

import json
from typing import Any, Dict, Optional, List

from loguru import logger

from dsbx.Agents.utils import LLMClient

from .config import LLMCoderConfig
from .rules import RuleWithMeta
from .agentic import StrategyPlan
from .compile import compile_optimized_priority
from .baseline_heuristics import BaselineHeuristicLibrary


def _strip_code_fences(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return s
    if s.startswith("```"):
        parts = s.split("\n")
        if parts:
            parts = parts[1:]
        s2 = "\n".join(parts)
        if "```" in s2:
            s2 = s2.rsplit("```", 1)[0]
        return s2.strip()
    return s


def _extract_first_json_object(text: str) -> Optional[str]:
    s = str(text or "")
    start = s.find("{")
    if start < 0:
        return None

    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def _sanitize_generated_code_for_compile(code: str) -> str:
    s = _strip_code_fences(code)
    lines = s.splitlines()
    while lines and lines[-1].strip() in ("}", "```"):
        lines.pop()
    s = "\n".join(lines).strip()
    # Common failure mode: stray trailing quote makes Python code invalid
    if s.endswith('"') and s.count('"') % 2 == 1:
        s = s[:-1]
    if s.startswith('"') and s.endswith('"') and "def optimized_priority" in s:
        s = s[1:-1]
    return s.strip()


_SANDBOX_HARD_CONSTRAINTS_TEXT = (
    "Sandbox executability hard constraints (must follow exactly):\n"
    "- Output code must define ONLY: def optimized_priority(obs, action, env) -> float\n"
    "  * You may optionally include: import math\n"
    "  * Do not include any other top-level statements.\n"
    "- Allowed helpers available at runtime: _safe_float, _find_ready_op, math\n"
    "- Allowed builtins: abs, min, max, sum, len, ord, chr, float, int, str, range, enumerate, sorted, zip, "
    "isinstance, set, list, dict, tuple, all, any, bool, round, getattr, hasattr, Exception\n"
    "- Forbidden: any imports except math; file/network/system access; eval/exec/compile/open/input/print; randomness\n"
    "If you violate these constraints, the code will be rejected and discarded (a retry may be triggered).\n\n"
)


class _FunctionPriorityRule:
    def __init__(self, fn):
        self._fn = fn
        self._error_count = 0
        self._log_count = 0
        self._suppressed = False
        self._disabled = False

    def is_disabled(self) -> bool:
        return bool(self._disabled)

    def __call__(self, obs: Dict[str, Any], action: Dict[str, Any], env: Any) -> float:
        if self._disabled:
            return 0.0
        try:
            v = self._fn(obs, action, env)
        except Exception as e:  # pragma: no cover - defensive path
            self._error_count += 1
            if self._log_count < 3:
                self._log_count += 1
                logger.debug(f"LLM priority function raised error: {e}")
            elif not self._suppressed:
                self._suppressed = True
                logger.info(
                    "LLM priority function error repeated; suppressing further errors for this rule (seen={})",
                    self._error_count,
                )
            if self._error_count >= 20 and not self._disabled:
                self._disabled = True
                logger.info(
                    "LLM priority function disabled after {} errors (last_error={})",
                    self._error_count,
                    str(e),
                )
            return 0.0
        if v is None:
            return 0.0
        try:
            return float(v)
        except Exception as e:
            self._error_count += 1
            if self._log_count < 3:
                self._log_count += 1
                logger.debug(f"LLM priority function returned non-float value: {e}")
            elif not self._suppressed:
                self._suppressed = True
                logger.info(
                    "LLM priority function returned invalid values repeatedly; suppressing further errors for this rule (seen={})",
                    self._error_count,
                )
            if self._error_count >= 20 and not self._disabled:
                self._disabled = True
                logger.info(
                    "LLM priority function disabled after {} errors (last_error={})",
                    self._error_count,
                    str(e),
                )
            return 0.0


class LLMCoder:
    def __init__(self, llm_client: LLMClient, cfg: LLMCoderConfig) -> None:
        self.client = llm_client
        self.cfg = cfg

    def build_candidates(
        self,
        model_summary: Dict[str, Any],
        obs_example: Dict[str, Any],
        baseline_name: str,
        objective_metric: Optional[str] = None,
    ) -> List[RuleWithMeta]:
        logger.info(
            "LLMCoder: building candidate rules for baseline '{}'",
            baseline_name,
        )
        metric_main = str(objective_metric) if objective_metric is not None else str(self.cfg.objective_metric)
        default_plan = StrategyPlan(
            name=f"baseline_guided_{baseline_name}",
            description=(
                "Improve or match the baseline dispatching rule by combining process time, "
                "due date and queue-related features without relying on external state."
            ),
            focus_metrics=[metric_main],
            constraints={},
            meta={"source": "default_plan"},
        )
        return self.build_candidates_from_plans(
            model_summary=model_summary,
            obs_example=obs_example,
            baseline_name=baseline_name,
            plans=[default_plan],
            objective_metric=objective_metric,
        )

    def build_candidate_rule(
        self,
        model_summary: Dict[str, Any],
        obs_example: Dict[str, Any],
        baseline_name: str,
        objective_metric: Optional[str] = None,
    ) -> Optional[RuleWithMeta]:
        candidates = self.build_candidates(model_summary, obs_example, baseline_name, objective_metric=objective_metric)
        if not candidates:
            return None
        return candidates[0]

    def build_candidates_from_plans(
        self,
        model_summary: Dict[str, Any],
        obs_example: Dict[str, Any],
        baseline_name: str,
        plans: List[StrategyPlan],
        objective_metric: Optional[str] = None,
    ) -> List[RuleWithMeta]:
        if not plans:
            return self.build_candidates(model_summary, obs_example, baseline_name, objective_metric=objective_metric)
        total_n = max(1, int(self.cfg.n_candidates))
        num_plans = max(1, len(plans))
        base_per_plan = max(1, total_n // num_plans)
        extra = max(0, total_n - base_per_plan * num_plans)
        all_candidates: List[RuleWithMeta] = []
        for idx, plan in enumerate(plans):
            k = base_per_plan + (1 if idx < extra else 0)
            prompt_base = self._build_prompt_for_plan(
                model_summary,
                obs_example,
                baseline_name,
                plan,
                objective_metric=objective_metric,
            )
            logger.debug(
                "LLMCoder DEBUG: full prompt for plan '{}':\n{}\n<<END_PROMPT>>",
                plan.name,
                prompt_base,
            )
            max_prompt_preview = 500
            prompt_preview = prompt_base[:max_prompt_preview]
            if len(prompt_base) > max_prompt_preview:
                prompt_preview = prompt_preview + "..."
            logger.info(
                "LLMCoder: plan '{}' prompt preview (first {} chars):\n{}",
                plan.name,
                max_prompt_preview,
                prompt_preview,
            )

            max_attempts = 2
            attempt = 0
            prompt_current = prompt_base
            while attempt < max_attempts:
                outs = self.client.generate(
                    prompt_current,
                    n=max(1, k),
                    temperature=self.cfg.llm_temperature,
                    top_p=self.cfg.llm_top_p,
                    top_k=self.cfg.llm_top_k,
                    timeout=self.cfg.llm_timeout,
                    response_format={"type": "json_object"},
                )
                logger.info(
                    "LLMCoder: plan '{}' LLM generate call (attempt {}/{}) completed, received {} raw outputs",
                    plan.name,
                    attempt + 1,
                    max_attempts,
                    len(outs),
                )
                if outs:
                    first_raw = outs[0]
                    max_raw_preview = 500
                    raw_preview = first_raw[:max_raw_preview]
                    if len(first_raw) > max_raw_preview:
                        raw_preview = raw_preview + "..."
                    logger.info(
                        "LLMCoder: plan '{}' first raw output preview (first {} chars):\n{}",
                        plan.name,
                        max_raw_preview,
                        raw_preview,
                    )
                any_success = False
                for i, raw in enumerate(outs):
                    logger.debug(
                        "LLMCoder DEBUG: full raw output #{} for plan '{}':\n{}\n<<END_OUTPUT>>",
                        i,
                        plan.name,
                        raw,
                    )
                    rule = self._parse_and_compile(raw)
                    if rule is None:
                        continue
                    any_success = True
                    info = dict(rule.info)
                    code_str = info.get("code") or ""
                    complexity = _analyze_code_complexity(str(code_str))
                    info["complexity"] = complexity
                    try:
                        logger.debug(
                            "LLMCoder: candidate from plan '{}' complexity stats: score={:.3f}, lines={}, ifs={}, loops={}, bool_ops={}, math_calls={}",
                            plan.name,
                            float(complexity.get("complexity_score", 0.0)),
                            complexity.get("num_non_empty_lines", 0),
                            complexity.get("num_ifs", 0),
                            complexity.get("num_loops", 0),
                            complexity.get("num_bool_ops", 0),
                            complexity.get("num_math_calls", 0),
                        )
                    except Exception:
                        pass
                    try:
                        info["plan"] = plan.to_dict()
                    except Exception:
                        info["plan"] = {"name": plan.name, "description": plan.description}
                    rule.info = info
                    all_candidates.append(rule)
                if any_success:
                    break
                attempt += 1
                if attempt >= max_attempts:
                    logger.warning(
                        "LLMCoder: all raw outputs for plan '{}' failed JSON parsing after {} attempts",
                        plan.name,
                        max_attempts,
                    )
                    break
                prompt_current = (
                    prompt_base
                    + "\n\nThe previous response could not be parsed as JSON. "
                    + "You MUST now respond with a single valid JSON object exactly of the form "
                    + '{"code": "def optimized_priority(...): ..."} with no extra text, comments, or markdown fences.'
                )
        if not all_candidates:
            logger.warning("LLMCoder: no valid candidate rule could be compiled from LLM outputs")
        return all_candidates

    def _format_baseline_examples(self, heuristics: List[tuple[str, str]]) -> str:
        """Format baseline heuristics for prompt inclusion.
        
        Args:
            heuristics: List of (name, code) tuples for baseline heuristics
            
        Returns:
            Formatted string with baseline heuristic implementations
        """
        if not heuristics:
            return ""
        
        sections = []
        for name, code in heuristics:
            sections.append(
                f"### {name} Heuristic\n"
                f"```python\n{code}\n```\n"
            )
        return "\n".join(sections)
    
    def _build_crossover_instructions(self, plan: StrategyPlan) -> str:
        """Build crossover-specific instructions for prompt.
        
        Args:
            plan: Strategy plan with crossover details
            
        Returns:
            Formatted crossover instructions
        """
        instructions = (
            "Your task (CROSSOVER STRATEGY):\n"
            "- You are performing a CROSSOVER operation to combine features from parent rules.\n"
            "- Implement a Python function with the exact signature:\n"
            "  def optimized_priority(obs, action, env) -> float:\n"
            "    ...\n"
            "- The function must return a float priority score where higher values indicate better actions.\n"
            + _SANDBOX_HARD_CONSTRAINTS_TEXT
            + "- CROSSOVER GUIDANCE:\n"
            "  * Combine complementary features from both parent rules\n"
            "  * Preserve the best-performing aspects of each parent\n"
            "  * Create novel combinations that may outperform either parent\n"
            "  * Balance complexity - avoid simply concatenating all parent logic\n"
            "  * Consider weighted combinations or conditional logic to merge parent strategies\n\n"
        )
        
        # Add parent rule information if available in plan meta
        parent_info = plan.meta.get("parent_rules", [])
        if parent_info:
            instructions += "Parent Rules for Crossover:\n"
            for i, parent in enumerate(parent_info, 1):
                parent_code = parent.get("code", "")
                parent_fitness = parent.get("fitness", "unknown")
                instructions += (
                    f"Parent {i} (fitness: {parent_fitness}):\n"
                    f"```python\n{parent_code}\n```\n\n"
                )
        
        return instructions
    
    def _build_mutation_instructions(self, plan: StrategyPlan) -> str:
        """Build mutation-specific instructions for prompt.
        
        Args:
            plan: Strategy plan with mutation details
            
        Returns:
            Formatted mutation instructions
        """
        mutation_focus = getattr(plan, "mutation_focus", None) or "general improvement"
        
        instructions = (
            "Your task (MUTATION STRATEGY):\n"
            "- You are performing a MUTATION operation to improve an existing rule.\n"
            "- Implement a Python function with the exact signature:\n"
            "  def optimized_priority(obs, action, env) -> float:\n"
            "    ...\n"
            "- The function must return a float priority score where higher values indicate better actions.\n"
            + _SANDBOX_HARD_CONSTRAINTS_TEXT
            + "- MUTATION GUIDANCE:\n"
            "  * Start from the parent rule's logic and make targeted improvements\n"
            "  * Adjust weights, thresholds, or feature combinations\n"
            "  * Add new features or remove underperforming ones\n"
            "  * Simplify overly complex logic or add sophistication where needed\n"
            f"  * Focus area for this mutation: {mutation_focus}\n"
            "  * Keep the core strategy but refine the details\n\n"
        )
        
        # Add parent rule information if available in plan meta
        parent_info = plan.meta.get("parent_rules", [])
        if parent_info and len(parent_info) > 0:
            parent = parent_info[0]
            parent_code = parent.get("code", "")
            parent_fitness = parent.get("fitness", "unknown")
            instructions += (
                f"Parent Rule to Mutate (fitness: {parent_fitness}):\n"
                f"```python\n{parent_code}\n```\n\n"
            )
        
        return instructions

    def _build_prompt(self, model_summary: Dict[str, Any], obs_example: Dict[str, Any], baseline_name: str) -> str:
        ms = json.dumps(model_summary, ensure_ascii=False)
        payload = obs_example if isinstance(obs_example, dict) else {}
        state_profile = payload.get("state_profile") if isinstance(payload.get("state_profile"), dict) else payload
        state_profile_window = (
            payload.get("state_profile_window") if isinstance(payload.get("state_profile_window"), dict) else {}
        )
        action_sample = payload.get("action_sample") if isinstance(payload.get("action_sample"), list) else []
        sp = json.dumps(state_profile, ensure_ascii=False)
        spw = json.dumps(state_profile_window, ensure_ascii=False)
        ac = json.dumps(action_sample, ensure_ascii=False)
        return (
            "You are an expert production scheduler for dynamic job shops.\n"
            "You must design a dispatching priority function that chooses good actions at each decision point.\n\n"
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
            "- Each scheduling action has the form action = {\"job_id\": <int>, \"machine_group\": <str>, \"machine_id\": <str>, \"machine_candidates\": <list>}.\n"
            "- At each decision point we expand every ready operation over all its candidate machines, evaluate optimized_priority(obs, action, env) for every (job, machine) candidate action, and choose the one with the highest score.\n\n"
            "Provided context samples:\n"
            "- STATE_PROFILE is a compressed summary of the current state (statistics over ready_ops, machines, and dynamic events).\n"
            "- STATE_PROFILE_WINDOW is a windowed / distributional summary over recent decision points.\n"
            "- ACTION_SAMPLE is a list of up to 30 sampled legal actions at the current decision point.\n"
            "- Prefer features that are robust across STATE_PROFILE_WINDOW rather than brittle thresholds tied to a single snapshot.\n\n"
            "Your task:\n"
            "- Implement a Python function with the exact signature:\n"
            "  def optimized_priority(obs, action, env) -> float:\n"
            "    ...\n"
            "- The function must return a float priority score where higher values indicate better actions.\n"
            f"- The current baseline dispatching rule is '{baseline_name}'. "
            "Your goal is to strictly improve or at least match its performance on metrics such as total_weighted_tardiness.\n\n"
            "Constraints:\n"
            + _SANDBOX_HARD_CONSTRAINTS_TEXT
            + "- Do NOT include any explanations or comments in the generated code.\n\n"
            "Output format:\n"
            "- You must reply with exactly ONE valid JSON object and NOTHING else.\n"
            "- The response must start with '{' and end with '}'.\n"
            "- Required schema: {\"code\": \"def optimized_priority(...): ...\"}.\n"
            "- Do NOT wrap the code in markdown fences (no ```).\n"
            "- Do NOT output any additional keys, explanation, comments, or extra text before/after the JSON.\n\n"
            f"STATE_PROFILE = {sp}\nSTATE_PROFILE_WINDOW = {spw}\nACTION_SAMPLE = {ac}\n"
        )

    def _build_prompt_for_plan(
        self,
        model_summary: Dict[str, Any],
        obs_example: Dict[str, Any],
        baseline_name: str,
        plan: StrategyPlan,
        objective_metric: Optional[str] = None,
    ) -> str:
        ms = json.dumps(model_summary, ensure_ascii=False)
        payload = obs_example if isinstance(obs_example, dict) else {}
        state_profile = payload.get("state_profile") if isinstance(payload.get("state_profile"), dict) else payload
        state_profile_window = (
            payload.get("state_profile_window") if isinstance(payload.get("state_profile_window"), dict) else {}
        )
        action_sample = payload.get("action_sample") if isinstance(payload.get("action_sample"), list) else []
        sp = json.dumps(state_profile, ensure_ascii=False)
        spw = json.dumps(state_profile_window, ensure_ascii=False)
        ac = json.dumps(action_sample, ensure_ascii=False)
        metric_main = str(objective_metric) if objective_metric is not None else str(self.cfg.objective_metric)
        focus_list = [str(m) for m in (plan.focus_metrics or []) if str(m)]
        if metric_main and metric_main not in focus_list:
            focus_list = [metric_main] + focus_list
        if not focus_list:
            focus_list = [metric_main]
        focus_text = ", ".join(focus_list)
        constraints_json = json.dumps(plan.constraints or {}, ensure_ascii=False)
        
        # Get strategy type from plan
        strategy_type = getattr(plan, "strategy_type", "generate")
        
        # Get relevant baseline implementations (reduce for evolutionary strategies)
        baseline_examples = ""
        if self.cfg.include_baseline_implementations:
            # For evolutionary strategies, reduce baseline examples to focus on parent code
            max_examples = 1 if strategy_type in ["crossover", "mutation"] else self.cfg.max_baseline_examples
            heuristics = BaselineHeuristicLibrary.get_relevant_heuristics(
                baseline_name,
                max_count=max_examples
            )
            if heuristics:
                baseline_examples = self._format_baseline_examples(heuristics)
        
        # Build the prompt with baseline examples section
        prompt = (
            "You are an expert production scheduler for dynamic job shops.\n"
            "You must design a dispatching priority function that chooses good actions at each decision point.\n\n"
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
            "- Each scheduling action has the form action = {\"job_id\": <int>, \"machine_group\": <str>, \"machine_id\": <str>, \"machine_candidates\": <list>}.\n"
            "- At each decision point we expand every ready operation over all its candidate machines, evaluate optimized_priority(obs, action, env) for every (job, machine) candidate action, and choose the one with the highest score.\n\n"
            "Provided context samples:\n"
            "- STATE_PROFILE is a compressed summary of the current state (statistics over ready_ops, machines, and dynamic events).\n"
            "- STATE_PROFILE_WINDOW is a windowed / distributional summary over recent decision points.\n"
            "- ACTION_SAMPLE is a list of up to 30 sampled legal actions at the current decision point.\n"
            "- Prefer features that are robust across STATE_PROFILE_WINDOW rather than brittle thresholds tied to a single snapshot.\n\n"
        )
        
        # Add baseline heuristic examples section if available (reduced for evolutionary strategies)
        if baseline_examples:
            prompt += (
                "Reference Baseline Heuristic Implementations:\n"
                "The following are well-established scheduling heuristics that you can learn from and adapt.\n"
                "These implementations show common patterns and techniques for priority calculation.\n\n"
                f"{baseline_examples}\n"
            )
        
        # Add strategy-specific instructions
        if strategy_type == "crossover":
            prompt += self._build_crossover_instructions(plan)
        elif strategy_type == "mutation":
            prompt += self._build_mutation_instructions(plan)
        else:
            # Default generate strategy
            prompt += (
                "Your task:\n"
                "- Implement a Python function with the exact signature:\n"
                "  def optimized_priority(obs, action, env) -> float:\n"
                "    ...\n"
                "- The function must return a float priority score where higher values indicate better actions.\n"
                f"- The current baseline dispatching rule is '{baseline_name}'. "
                f"Your goal is to strictly improve or at least match its performance on metrics such as {focus_text}.\n\n"
            )
        
        prompt += (
            "Design intent for this candidate rule:\n"
            f"- Strategy name: {plan.name}\n"
            f"- Strategy type: {strategy_type}\n"
            f"- Strategy description: {plan.description}\n"
            f"- Focus metrics: {focus_text}\n"
            f"- Additional constraints (JSON): {constraints_json}\n\n"
            "Constraints:\n"
            + _SANDBOX_HARD_CONSTRAINTS_TEXT
            + "- Do NOT include any explanations or comments in the generated code.\n\n"
            "Output format:\n"
            "- You must reply with exactly ONE valid JSON object and NOTHING else.\n"
            "- The response must start with '{' and end with '}'.\n"
            "- Required schema: {\"code\": \"def optimized_priority(...): ...\"}.\n"
            "- Do NOT wrap the code in markdown fences (no ```).\n"
            "- Do NOT output any additional keys, explanation, comments, or extra text before/after the JSON.\n\n"
            f"STATE_PROFILE = {sp}\nSTATE_PROFILE_WINDOW = {spw}\nACTION_SAMPLE = {ac}\n"
        )
        
        return prompt

    def _parse_and_compile(self, raw: str) -> Optional[RuleWithMeta]:
        obj: Any
        raw_text = str(raw or "")
        parsed = False
        for candidate in (
            raw_text,
            _strip_code_fences(raw_text),
        ):
            try:
                obj = json.loads(candidate)
                parsed = True
                break
            except Exception:
                pass
        if not parsed:
            cleaned = _strip_code_fences(raw_text)
            json_str = _extract_first_json_object(cleaned)
            if json_str:
                try:
                    obj = json.loads(json_str)
                    parsed = True
                    # Guard: extracted JSON might be a dict literal from inside Python code
                    # (e.g. action examples), not the intended LLM response schema.
                    if isinstance(obj, dict):
                        extracted_code = obj.get("code") or obj.get("python_code")
                        if not isinstance(extracted_code, str):
                            for v in obj.values():
                                if not isinstance(v, str):
                                    continue
                                cand = _strip_code_fences(v).strip()
                                if "def optimized_priority" in cand:
                                    extracted_code = cand
                                    break
                        if not isinstance(extracted_code, str) or not extracted_code.strip():
                            parsed = False
                except Exception:
                    parsed = False
        if not parsed:
            cleaned = _strip_code_fences(raw_text)
            if "def optimized_priority" in cleaned:
                obj = {"code": cleaned.strip()}
                parsed = True
        if not parsed:
            logger.warning("LLMCoder: failed to parse JSON from LLM output")
            return None
        code = None
        if isinstance(obj, dict):
            code = obj.get("code") or obj.get("python_code")
            if not isinstance(code, str):
                for v in obj.values():
                    if not isinstance(v, str):
                        continue
                    cand = _strip_code_fences(v).strip()
                    if "def optimized_priority" in cand:
                        code = cand
                        break
        if not isinstance(code, str) or not code.strip():
            logger.warning("LLMCoder: JSON does not contain a usable 'code' string field")
            return None
        max_chars = max(1024, int(self.cfg.max_code_chars))
        if len(code) > max_chars:
            logger.debug(
                "LLMCoder: generated code too long ({} chars), truncating to {} chars",
                len(code),
                max_chars,
            )
            code = code[:max_chars]
        logger.debug(
            "LLMCoder DEBUG: generated code candidate before exec:\n{}\n<<END_CODE>>",
            code,
        )
        try:
            fn = compile_optimized_priority(code)
        except Exception as e:
            code2 = _sanitize_generated_code_for_compile(code)
            if code2 != code:
                try:
                    fn = compile_optimized_priority(code2)
                    code = code2
                except Exception:
                    logger.error(f"LLMCoder: failed to exec generated code: {e}")
                    return None
            else:
                logger.error(f"LLMCoder: failed to exec generated code: {e}")
                return None
        rule = _FunctionPriorityRule(fn)
        
        # Get name from LLM response or use default
        llm_name = obj.get("name")
        if llm_name and isinstance(llm_name, str):
            name = str(llm_name)
        else:
            name = "llm_optimized_priority"
        
        info = {
            "raw": raw,
            "code": code,
            "strategy_type": "generate"  # Default strategy type for LLM-generated rules
        }
        
        # Create RuleWithMeta with temporary name
        rule_with_meta = RuleWithMeta(rule=rule, name=name, info=info)
        
        # Generate unique name based on strategy type
        from .repository import generate_unique_rule_name
        unique_name = generate_unique_rule_name(rule_with_meta)
        rule_with_meta.name = unique_name
        
        logger.debug(
            "LLMCoder: compiled optimized_priority function into PriorityRule named '{}'",
            unique_name,
        )
        return rule_with_meta


def _analyze_code_complexity(code: str) -> Dict[str, Any]:
    lines = code.splitlines()
    num_lines = 0
    num_non_empty_lines = 0
    num_ifs = 0
    num_loops = 0
    num_comparisons = 0
    num_bool_ops = 0
    num_math_calls = 0
    for line in lines:
        num_lines += 1
        stripped = line.strip()
        if stripped:
            num_non_empty_lines += 1
        lower = stripped.lower()
        if "if " in lower or lower.startswith("if"):
            num_ifs += 1
        if "for " in lower or lower.startswith("for"):
            num_loops += 1
        if "while " in lower or lower.startswith("while"):
            num_loops += 1
        if "==" in line or "!=" in line or ">=" in line or "<=" in line or ">" in line or "<" in line:
            num_comparisons += 1
        if " and " in lower or " or " in lower:
            num_bool_ops += 1
        if "math." in line:
            num_math_calls += 1
    total_chars = len(code)
    structural_complexity = num_ifs + num_loops + num_bool_ops
    complexity_score = float(num_non_empty_lines + structural_complexity + num_math_calls)
    return {
        "num_lines": num_lines,
        "num_non_empty_lines": num_non_empty_lines,
        "num_ifs": num_ifs,
        "num_loops": num_loops,
        "num_comparisons": num_comparisons,
        "num_bool_ops": num_bool_ops,
        "num_math_calls": num_math_calls,
        "total_chars": total_chars,
        "structural_complexity": structural_complexity,
        "complexity_score": complexity_score,
    }
