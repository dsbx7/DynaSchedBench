from typing import List, Dict, Any, Optional

from loguru import logger

from .config import SType
from dsbx.Agents.utils import LLMClient
from dsbx.Agents.PDRs.rules import compute_job_priority


class Sampler:
    def sample(self, client: LLMClient, prompt: str, s_type: SType, temperature: float, top_p: float, top_k: int, n: int, timeout: float) -> List[str]:
        logger.debug(
            "Sampler.sample: s_type={} n={} temp={} top_p={} top_k={} timeout={}",
            s_type.value,
            n,
            temperature,
            top_p,
            top_k,
            timeout,
        )

        count = max(1, int(n))
        try:
            temp = float(temperature)
        except Exception:
            temp = 0.0
        try:
            p = float(top_p)
        except Exception:
            p = 1.0
        try:
            k = int(top_k)
        except Exception:
            k = 0

        return client.generate(
            prompt,
            n=count,
            temperature=temp,
            top_p=p,
            top_k=k,
            timeout=float(timeout),
        )


def choose_by_env_score(legal_actions: List[Dict[str, Any]], env, rollout_steps: int = 0) -> Optional[Dict[str, Any]]:
    if not legal_actions:
        return None
    best = None
    best_score = None
    for a in legal_actions:
        if rollout_steps and hasattr(env, "quick_rollout_score"):
            s = env.quick_rollout_score(a, steps=rollout_steps)
        else:
            s = env.estimate_action_score(a)
        if best is None or s > best_score:
            best = a
            best_score = s
    logger.debug(
        "choose_by_env_score: selected job_id={} group={} score={}",
        best.get("job_id") if best else None,
        best.get("machine_group") if best else None,
        best_score,
    )
    return best


def choose_by_heuristic(heuristic: str, legal_actions: List[Dict[str, Any]], env) -> Optional[Dict[str, Any]]:
    """Select an action using a simple priority dispatching rule.

    The default implementation supports ``SPT`` and ``MWKR``. It prefers
    ``ready_ops`` from the current observation and, when possible, uses
    ``PDRs.rules.compute_job_priority`` for consistent priority calculation.
    If required fields are missing, it falls back to the environment helpers
    ``get_next_process_time`` and ``get_remaining_work``.
    """

    h = heuristic.upper() if heuristic else "SPT"
    if not legal_actions:
        logger.debug("choose_by_heuristic: no legal actions (heuristic={})", h)
        return None

    obs: Dict[str, Any] = {}
    try:
        if hasattr(env, "get_snapshot"):
            cached = getattr(env, "_last_obs", None)
            if isinstance(cached, dict):
                obs = cached
            else:
                snap_obs = getattr(env, "_observation", None)
                if callable(snap_obs):
                    obs = snap_obs()  # type: ignore[assignment]
        else:
            cached = getattr(env, "_last_obs", None)
            if isinstance(cached, dict):
                obs = cached
    except Exception:
        obs = {}

    ready_ops = obs.get("ready_ops") if isinstance(obs, dict) else None
    if isinstance(ready_ops, list) and ready_ops:
        logger.debug(
            "choose_by_heuristic: using ready_ops-based priority (heuristic={}) for {} actions",
            h,
            len(legal_actions),
        )
        best_action: Optional[Dict[str, Any]] = None
        best_priority: Optional[float] = None
        remain_cache = None
        for a in legal_actions:
            jid = str(a.get("job_id"))
            mg = str(a.get("machine_group"))
            op_index = None
            proc_time = None
            for ro in ready_ops:
                if str(ro.get("job_id")) == jid and str(ro.get("machine_group")) == mg:
                    op_index = int(ro.get("operation", 0))
                    proc_time = float(ro.get("process_time", 0.0))
                    break
            if op_index is None or proc_time is None:
                continue
            try:
                pr = compute_job_priority(h, jid, op_index, proc_time, obs, remain_work_cache=remain_cache, is_emergency=False)
            except Exception:
                continue
            if best_action is None or pr < best_priority:
                best_action = a
                best_priority = pr
        if best_action is not None:
            logger.debug(
                "choose_by_heuristic: selected by ready_ops (heuristic={}) job_id={} group={}",
                h,
                best_action.get("job_id"),
                best_action.get("machine_group"),
            )
            return best_action

    if h == "MWKR":
        mx = None
        best = None
        for a in legal_actions:
            try:
                r = env.get_remaining_work(a["job_id"])  # type: ignore[call-arg]
            except Exception:
                continue
            if mx is None or r > mx:
                mx = r
                best = a
        logger.debug("choose_by_heuristic: MWKR fallback selected job_id={} (remain_work={})", best.get("job_id") if best else None, mx)
        return best

    best = None
    best_pt = None
    for a in legal_actions:
        try:
            pt = env.get_next_process_time(a["job_id"])  # type: ignore[call-arg]
        except Exception:
            continue
        if pt is None:
            continue
        if best is None or pt < best_pt:
            best = a
            best_pt = pt
    return best
