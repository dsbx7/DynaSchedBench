from __future__ import annotations

import json
from typing import Any, Dict, Optional, List

from loguru import logger

from dsbx.Agents.utils import LLMClient

from .config import LLMCoderConfig
from .rules import RuleWithMeta
from .agentic import StrategyPlan
from .compile import compile_optimized_priority


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
                logger.error(f"LLM priority function raised error: {e}")
            elif not self._suppressed:
                self._suppressed = True
                logger.warning(
                    "LLM priority function error repeated; suppressing further errors for this rule (seen={})",
                    self._error_count,
                )
            if self._error_count >= 20 and not self._disabled:
                self._disabled = True
                logger.warning(
                    "LLM priority function disabled after {} errors (last_error={})",
                    self._error_count,
                    str(e),
                )
            return 0.0
        try:
            return float(v)
        except Exception as e:
            self._error_count += 1
            if self._log_count < 3:
                self._log_count += 1
                logger.error(f"LLM priority function returned non-float value: {e}")
            elif not self._suppressed:
                self._suppressed = True
                logger.warning(
                    "LLM priority function returned invalid values repeatedly; suppressing further errors for this rule (seen={})",
                    self._error_count,
                )
            if self._error_count >= 20 and not self._disabled:
                self._disabled = True
                logger.warning(
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
            "- You may only use pure Python standard operators and the 'math' module (which is already imported).\n"
            "- Do NOT import any other modules, do NOT access network, filesystem or randomness, and do NOT print anything.\n"
            "- Do NOT include any explanations or comments in the generated code.\n\n"
            "Output format:\n"
            "- You must reply with a single JSON object of the form {\"code\": \"def optimized_priority(...): ...\"}.\n"
            "- Do NOT wrap the code in markdown fences.\n\n"
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
            f"Your goal is to strictly improve or at least match its performance on metrics such as {focus_text}.\n\n"
            "Design intent for this candidate rule:\n"
            f"- Strategy name: {plan.name}\n"
            f"- Strategy description: {plan.description}\n"
            f"- Focus metrics: {focus_text}\n"
            f"- Additional constraints (JSON): {constraints_json}\n\n"
            "Constraints:\n"
            "- You may only use pure Python standard operators and the 'math' module (which is already imported).\n"
            "- Do NOT import any other modules, do NOT access network, filesystem or randomness, and do NOT print anything.\n"
            "- Do NOT include any explanations or comments in the generated code.\n\n"
            "Output format:\n"
            "- You must reply with a single JSON object of the form {\"code\": \"def optimized_priority(...): ...\"}.\n"
            "- Do NOT wrap the code in markdown fences.\n\n"
            f"STATE_PROFILE = {sp}\nSTATE_PROFILE_WINDOW = {spw}\nACTION_SAMPLE = {ac}\n"
        )

    def _parse_and_compile(self, raw: str) -> Optional[RuleWithMeta]:
        try:
            obj = json.loads(raw)
        except Exception:
            logger.error("LLMCoder: failed to parse JSON from LLM output")
            return None
        code = obj.get("code") or obj.get("python_code")
        if not isinstance(code, str):
            logger.error("LLMCoder: JSON does not contain a 'code' string field")
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
            logger.error(f"LLMCoder: failed to exec generated code: {e}")
            return None
        rule = _FunctionPriorityRule(fn)
        name = str(obj.get("name") or "llm_optimized_priority")
        info = {"raw": raw, "code": code}
        logger.debug(
            "LLMCoder: compiled optimized_priority function into PriorityRule named '{}'",
            name,
        )
        return RuleWithMeta(rule=rule, name=name, info=info)


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
