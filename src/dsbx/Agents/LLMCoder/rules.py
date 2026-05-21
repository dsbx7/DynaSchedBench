from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional, Protocol

from loguru import logger


class PriorityRule(Protocol):
    def __call__(self, obs: Dict[str, Any], action: Dict[str, Any], env: Any) -> float:  # pragma: no cover - protocol
        ...


@dataclass
class RuleWithMeta:
    rule: PriorityRule
    name: str = "rule"
    version: int = 0
    info: Dict[str, Any] = field(default_factory=dict)


class RuleManager:
    """Thread-safe manager for the currently active scheduling rule."""

    def __init__(self, fallback_rule: PriorityRule, name: str = "fallback") -> None:
        self._lock = Lock()
        self._current = RuleWithMeta(rule=fallback_rule, name=name, version=0, info={})
        self._fallback = self._current

    def reset_to_fallback(self) -> None:
        with self._lock:
            self._current = self._fallback

    def get_active_rule(self) -> RuleWithMeta:
        with self._lock:
            return self._current

    def update_rule(self, new_rule: RuleWithMeta) -> None:
        with self._lock:
            ver = self._current.version + 1
            self._current = RuleWithMeta(rule=new_rule.rule, name=new_rule.name, version=ver, info=dict(new_rule.info))

    @property
    def current_name(self) -> str:
        with self._lock:
            return self._current.name


class SPTPriorityRule:
    """Priority rule corresponding to the SPT heuristic.
    
    Larger return values mean higher priority, so the score is ``-process_time``.
    """

    def __call__(self, obs: Dict[str, Any], action: Dict[str, Any], env: Any) -> float:
        job_id = str(action.get("job_id"))
        ready_ops: List[Dict[str, Any]] = obs.get("ready_ops", []) or []
        pt = None
        for ro in ready_ops:
            if str(ro.get("job_id")) == job_id:
                try:
                    v = float(ro.get("process_time", 0.0))
                except Exception:
                    v = 0.0
                pt = v if pt is None or v < pt else pt
        if pt is None:
            pt = 0.0
        return -float(pt)


def choose_action_by_rule(
    rule: PriorityRule,
    obs: Dict[str, Any],
    legal_actions: List[Dict[str, Any]],
    env: Any,
    *,
    log_candidate_actions: bool = False,
    log_candidate_actions_max: int = 50,
    rule_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not legal_actions:
        return None
    
    is_disabled = getattr(rule, "is_disabled", None)
    if callable(is_disabled):
        try:
            if bool(is_disabled()):
                return legal_actions[0]
        except Exception:
            pass

    expanded_pairs: List[tuple[Dict[str, Any], Dict[str, Any]]] = []
    for base in legal_actions:
        machines = list(base.get("machine_candidates") or [])
        if not machines:
            expanded_pairs.append((base, base))
            continue
        base_no_mid = dict(base)
        base_no_mid.pop("machine_id", None)
        for m_id in machines:
            a = dict(base_no_mid)
            a["machine_id"] = m_id
            a["machine_candidates"] = machines
            expanded_pairs.append((a, base_no_mid))

    if len(expanded_pairs) == 1:
        return expanded_pairs[0][0]

    def _find_ready_op(job_id: str, machine_group: str) -> Dict[str, Any]:
        ready_ops: List[Dict[str, Any]] = obs.get("ready_ops", []) or []
        fallback: Optional[Dict[str, Any]] = None
        for ro in ready_ops:
            if str(ro.get("job_id")) != job_id:
                continue
            if fallback is None:
                fallback = ro
            if machine_group and str(ro.get("machine_group")) == machine_group:
                return ro
        return fallback or {}

    best_action: Optional[Dict[str, Any]] = None
    best_base_action: Optional[Dict[str, Any]] = None
    best_score = float("-inf")
    scored: List[Dict[str, Any]] = []
    num_scoring_errors = 0
    base_scores: Dict[tuple[str, str, tuple[Any, ...]], List[float]] = {}
    base_action_by_key: Dict[tuple[str, str, tuple[Any, ...]], Dict[str, Any]] = {}

    for a, base_action in expanded_pairs:
        job_id = str(a.get("job_id"))
        mg = str(a.get("machine_group"))
        machines_tuple = tuple(a.get("machine_candidates") or [])
        base_key = (job_id, mg, machines_tuple)
        ro = _find_ready_op(job_id, mg)
        try:
            s = float(rule(obs, a, env))
        except Exception as exc:
            num_scoring_errors += 1
            if log_candidate_actions:
                scored.append(
                    {
                        "job_id": job_id,
                        "machine_group": mg,
                        "machine_id": a.get("machine_id"),
                        "machine_candidates": a.get("machine_candidates"),
                        "process_time": ro.get("process_time"),
                        "remaining_work": ro.get("remaining_work"),
                        "remaining_ops": ro.get("remaining_ops"),
                        "flexibility": ro.get("flexibility"),
                        "priority": ro.get("priority"),
                        "score": None,
                        "error": repr(exc),
                    }
                )
            continue

        base_scores.setdefault(base_key, []).append(float(s))
        base_action_by_key.setdefault(base_key, base_action)

        if log_candidate_actions:
            scored.append(
                {
                    "job_id": job_id,
                    "machine_group": mg,
                    "machine_id": a.get("machine_id"),
                    "machine_candidates": a.get("machine_candidates"),
                    "process_time": ro.get("process_time"),
                    "remaining_work": ro.get("remaining_work"),
                    "remaining_ops": ro.get("remaining_ops"),
                    "flexibility": ro.get("flexibility"),
                    "priority": ro.get("priority"),
                    "score": s,
                    "error": None,
                }
            )
        if s > best_score:
            best_score = s
            best_action = a
            best_base_action = base_action

    if log_candidate_actions:
        valid_scored = [x for x in scored if isinstance(x.get("score"), (int, float))]
        error_scored = [x for x in scored if x.get("score") is None]
        valid_scored.sort(key=lambda x: float(x.get("score", float("-inf"))), reverse=True)
        max_n = int(log_candidate_actions_max)
        if max_n <= 0:
            max_n = len(valid_scored)
        display = valid_scored[:max_n]
        rn = rule_name or getattr(rule, "__name__", None) or rule.__class__.__name__
        lines: List[str] = []
        for i, item in enumerate(display):
            lines.append(
                "#{:02d} job_id={} mg={} m_id={} machines={} pt={} rem_work={} rem_ops={} flex={} priority={} score={:.6f}".format(
                    i,
                    item.get("job_id"),
                    item.get("machine_group"),
                    item.get("machine_id"),
                    item.get("machine_candidates"),
                    item.get("process_time"),
                    item.get("remaining_work"),
                    item.get("remaining_ops"),
                    item.get("flexibility"),
                    item.get("priority"),
                    float(item.get("score", 0.0)),
                )
            )
        if len(valid_scored) > max_n:
            lines.append("... truncated {} scored actions".format(len(valid_scored) - max_n))
        if error_scored:
            lines.append("... {} actions failed scoring".format(len(error_scored)))
        logger.info(
            "choose_action_by_rule: rule='{}' n_legal={} n_scored={} best_score={:.6f}\n{}",
            rn,
            len(legal_actions),
            len(valid_scored),
            float(best_score) if best_action is not None else float("nan"),
            "\n".join(lines),
        )
    if best_action is None:
        return legal_actions[0]

    try:
        job_id = str(best_action.get("job_id"))
        mg = str(best_action.get("machine_group"))
        machines_tuple = tuple(best_action.get("machine_candidates") or [])
        base_key = (job_id, mg, machines_tuple)
        scores_here = base_scores.get(base_key) or []
        if len(scores_here) >= 2:
            s_max = max(scores_here)
            s_min = min(scores_here)
            if abs(s_max - s_min) <= 1e-12:
                if best_base_action is not None:
                    return best_base_action
    except Exception:
        pass

    return best_action
