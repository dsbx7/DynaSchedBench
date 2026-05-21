from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from dsbx.Agents.utils import LLMClient
from dsbx.Eval.Metrics import METRIC_ALL_KEYS
from .config import LLMCoderConfig
from .rules import RuleWithMeta
from .sandbox_eval import EvalResult


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "focus_metrics": list(self.focus_metrics),
            "constraints": dict(self.constraints),
            "meta": dict(self.meta),
        }


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

    def plan_strategies(
        self,
        model_summary: Dict[str, Any],
        obs_example: Dict[str, Any],
        baseline_name: str,
        history: Optional[Dict[str, Any]] = None,
        objective_metric: Optional[str] = None,
    ) -> List[StrategyPlan]:
        max_plans = int(getattr(self._cfg, "agentic_max_plans", 1))
        if max_plans <= 0:
            max_plans = 1
        metric_main = (
            str(objective_metric)
            if objective_metric is not None
            else str(getattr(self._cfg, "objective_metric", "makespan"))
        )
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
        while attempt < max_attempts:
            outs = self._client.generate(
                prompt_current,
                n=1,
                temperature=float(getattr(self._cfg, "planner_temperature", 0.2)),
                top_p=self._cfg.llm_top_p,
                top_k=self._cfg.llm_top_k,
                timeout=self._cfg.llm_timeout,
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
                plan = StrategyPlan(
                    name=str(name),
                    description=str(desc),
                    focus_metrics=list(focus),
                    constraints=dict(constraints),
                    meta=meta,
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
            "- Decide whether each candidate should be accepted, rejected, or refined, and whether the search should continue.\n\n"
            "Important constraints:\n"
            "- You MUST treat candidate.eval.accepted (sandbox evaluation result) as authoritative.\n"
            "- You MUST output verdict='accept' ONLY IF candidate.eval.accepted is true.\n"
            "- If candidate.eval.accepted is false but the candidate looks promising, output verdict='refine' and provide suggested_changes.\n\n"
            "Iteration control:\n"
            "- You MUST be conservative about continuing. Default to continue_iterations = false.\n"
            "- You may set continue_iterations = true ONLY IF all of the following hold:\n"
            "  (1) CONTEXT.history.remaining_iterations > 0, AND\n"
            "  (2) There is no accepted candidate that meets the improvement requirement, AND\n"
            "  (3) You believe more exploration is likely to help.\n"
            "- The improvement requirement is: best_relative_improvement >= agentic_min_relative_improvement (when objective_mode='min', larger relative_improvement is better).\n"
            "- If CONTEXT.history.remaining_iterations <= 0, you MUST output continue_iterations = false.\n"
            "- If CONTEXT.history.accepted_count > 0 and CONTEXT.history.best_relative_improvement is not null and CONTEXT.history.best_relative_improvement >= CONTEXT.history.agentic_min_relative_improvement, you MUST output continue_iterations = false.\n\n"
            "Output format:\n"
            "- You must reply with a single JSON object only.\n"
            "- The object must contain: 'continue_iterations' (boolean) and 'feedback' (list of objects).\n"
            "- Each feedback object must contain: 'index' (int), 'candidate_name' (string), 'verdict' (string in ['accept','reject','refine']), "
            "'reason' (string), and 'suggested_changes' (object, can be empty).\n"
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
            return CriticResult(continue_iterations=continue_iterations, feedbacks=feedbacks)
