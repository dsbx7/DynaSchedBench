from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from dsbx.Env import DynaSchedEnv


@dataclass
class ToolRuntimeContext:
    """Runtime context passed to LLMScheduler tools.

    For now this only carries the environment and the current pruned
    action list. It can be extended later (e.g. to include obs) without
    changing the public tool schemas.
    """

    env: DynaSchedEnv
    pruned_actions: List[Dict[str, Any]]


# Signature for a concrete tool implementation.
ToolImpl = Callable[[Dict[str, Any], ToolRuntimeContext], str]


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI tools-compatible format)
# ---------------------------------------------------------------------------

SIMULATE_ACTION_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "simulate_action",
        "description": (
            "Run a short rollout for an action and estimate its completion time. "
            "This is a local lookahead tool, not a full simulation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "integer",
                    "description": (
                        "The ActionID (1-based index into the current pruned "
                        "action table)."
                    ),
                    "minimum": 1,
                },
                "steps": {
                    "type": "integer",
                    "description": (
                        "Optional rollout horizon in decision steps. If omitted, "
                        "a default of 1 step is used."
                    ),
                    "minimum": 1,
                },
            },
            "required": ["action_id"],
            "additionalProperties": False,
        },
    },
}

INSPECT_ACTION_DETAILS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "inspect_action_details",
        "description": (
            "Inspect the local, structural, and global-evidence information for "
            "a given action_id in the current decision table. Does NOT expose any "
            "design priors (targets or dynamics configuration)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "integer",
                    "description": (
                        "The ActionID (1-based index into the current pruned "
                        "action table)."
                    ),
                    "minimum": 1,
                },
            },
            "required": ["action_id"],
            "additionalProperties": False,
        },
    },
}


# ---------------------------------------------------------------------------
# Tool registry and dispatcher
# ---------------------------------------------------------------------------

_TOOL_IMPLS: Dict[str, ToolImpl] = {}


def register_tool(name: str, func: ToolImpl) -> None:
    _TOOL_IMPLS[name] = func


def execute_tool_call(
    name: str,
    arguments: Dict[str, Any],
    ctx: ToolRuntimeContext,
) -> Optional[str]:
    """Execute a single tool call on behalf of the policy.

    Returns a human-readable observation string that can be appended to
    the prompt, or None if the tool is unknown or fails.
    """

    impl = _TOOL_IMPLS.get(name)
    if impl is None:
        logger.warning("LLMScheduler.tools: unknown tool name '{}'", name)
        return None
    try:
        return impl(arguments, ctx)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("LLMScheduler.tools: tool '{}' failed: {}", name, exc)
        return None


# ---------------------------------------------------------------------------
# Concrete tool implementations
# ---------------------------------------------------------------------------


def _impl_simulate_action(args: Dict[str, Any], ctx: ToolRuntimeContext) -> str:
    """Implementation of the simulate_action tool.

    It mirrors the legacy behaviour used in LLMPolicy._decide_o1_tool_use:
    perform a short rollout via env.quick_rollout_score and convert the
    score into an estimated completion time T = -score.
    """

    raw_aid = args.get("action_id")
    try:
        aid = int(raw_aid)
    except Exception:
        return (
            f"Observation: simulate_action({raw_aid}) => invalid action_id; "
            "must be an integer within the current ActionID range."
        )

    if not (1 <= aid <= len(ctx.pruned_actions)):
        return (
            f"Observation: simulate_action({aid}) => invalid action_id; "
            "out of range for the current ActionID column."
        )

    # Optional steps argument; default to 1 to preserve previous semantics.
    steps_raw = args.get("steps", 1)
    try:
        steps = int(steps_raw)
    except Exception:
        steps = 1
    if steps <= 0:
        steps = 1

    action = ctx.pruned_actions[aid - 1]

    sim_score: Optional[float] = None
    if hasattr(ctx.env, "quick_rollout_score"):
        try:
            sim_score = float(ctx.env.quick_rollout_score(action, steps=steps))
        except Exception as exc:
            logger.warning(
                "LLMScheduler.tools: quick_rollout_score for action_id={} failed: {}",
                aid,
                exc,
            )
            sim_score = None

    est_T: Optional[float] = None
    if sim_score is not None:
        try:
            est_T = -float(sim_score)
        except Exception:
            est_T = None

    if est_T is not None:
        if steps == 1:
            return (
                f"Observation: simulate_action({aid}) => estimated finish time "
                f"T={est_T:.3f}. (Smaller T is better.)"
            )
        return (
            f"Observation: simulate_action({aid}, steps={steps}) => estimated finish "
            f"time T={est_T:.3f}. (Smaller T is better.)"
        )

    return (
        f"Observation: simulate_action({aid}) => simulation result unavailable or "
        "failed."
    )


def _impl_inspect_action_details(args: Dict[str, Any], ctx: ToolRuntimeContext) -> str:
    raw_aid = args.get("action_id")
    try:
        aid = int(raw_aid)
    except Exception:
        return (
            f"Observation: inspect_action_details({raw_aid}) => invalid action_id; "
            "must be an integer within the current ActionID range."
        )

    if not (1 <= aid <= len(ctx.pruned_actions)):
        return (
            f"Observation: inspect_action_details({aid}) => invalid action_id; "
            "out of range for the current ActionID column."
        )

    action = ctx.pruned_actions[aid - 1]

    try:
        snap = ctx.env.get_snapshot()
    except Exception:
        return (
            f"Observation: inspect_action_details({aid}) => snapshot unavailable; "
            "environment does not expose a valid snapshot."
        )

    try:
        stats = getattr(snap, "system_stats", None)
    except Exception:
        stats = None

    try:
        horizon = float(getattr(snap, "horizon", 0.0))
    except Exception:
        horizon = 0.0

    now: float
    try:
        now = float(getattr(snap, "time", 0.0))
    except Exception:
        now = 0.0

    job_id = str(action.get("job_id"))
    group = str(action.get("machine_group"))
    mid = action.get("machine_id")
    mid_str = str(mid) if mid is not None else None

    obs = getattr(ctx.env, "_last_obs", None)
    ready_index: Dict[tuple[str, str], Dict[str, Any]] = {}
    emergency_jobs_set = set()
    if isinstance(obs, dict):
        ready_ops = obs.get("ready_ops")
        if isinstance(ready_ops, list):
            for r in ready_ops:
                if not isinstance(r, dict):
                    continue
                jid = r.get("job_id")
                grp = r.get("machine_group")
                if jid is None or grp is None:
                    continue
                ready_index[(str(jid), str(grp))] = r
        dyn = obs.get("dynamic_summary")
        if isinstance(dyn, dict):
            try:
                emergency_jobs_set = {str(x) for x in (dyn.get("emergency_jobs") or [])}
            except Exception:
                emergency_jobs_set = set()

    op_idx: Optional[int] = None
    total_ops: Optional[int] = None
    progress: Optional[float] = None
    priority: Optional[float] = None
    due_date: Optional[float] = None
    remaining_work: Optional[float] = None
    slack: Optional[float] = None

    info = ready_index.get((job_id, group)) or {}
    op_raw = info.get("operation")
    if op_raw is not None:
        try:
            op_idx = int(op_raw)
        except Exception:
            op_idx = None

    if emergency_jobs_set:
        priority = -1.0 if job_id in emergency_jobs_set else 0.0
    else:
        pr_raw = info.get("priority")
        if pr_raw is not None:
            try:
                priority = float(pr_raw)
            except Exception:
                priority = None

    try:
        jobs = getattr(snap, "jobs", []) or []
    except Exception:
        jobs = []

    job_obj: Optional[Any] = None
    for j in jobs:
        try:
            if str(getattr(j, "job_id", "")) == job_id:
                job_obj = j
                break
        except Exception:
            continue

    if job_obj is not None:
        if op_idx is None:
            try:
                op_idx = int(getattr(job_obj, "current_op_index", 0))
            except Exception:
                op_idx = None
        try:
            total_ops = int(getattr(job_obj, "total_ops", 0))
        except Exception:
            total_ops = None
        if op_idx is not None and total_ops is not None and total_ops > 0:
            try:
                progress = (float(op_idx) + 1.0) / float(total_ops)
            except Exception:
                progress = None

        due_candidate: Optional[float] = None
        has_due_date = False
        try:
            cur_dd = float(getattr(job_obj, "due_date", 0.0))
            if horizon > 0.0:
                if cur_dd < horizon - 1e-9:
                    due_candidate = cur_dd
                    has_due_date = True
            else:
                due_candidate = cur_dd
                has_due_date = True
        except Exception:
            due_candidate = None
            has_due_date = False

        if not has_due_date:
            try:
                init_dd = float(getattr(job_obj, "initial_due_date", 0.0))
                if horizon > 0.0:
                    if init_dd < horizon - 1e-9:
                        due_candidate = init_dd
                        has_due_date = True
                else:
                    due_candidate = init_dd
                    has_due_date = True
            except Exception:
                pass

        due_date = due_candidate if has_due_date else None

        rem_raw = info.get("remaining_work")
        if rem_raw is not None:
            try:
                remaining_work = float(rem_raw)
            except Exception:
                remaining_work = None
        if remaining_work is None:
            try:
                remaining_work = float(getattr(job_obj, "remaining_work_content", 0.0))
            except Exception:
                remaining_work = None
        if due_date is not None and remaining_work is not None:
            try:
                slack = due_date - now - remaining_work
            except Exception:
                slack = None

    queue_len: Optional[int] = None
    target = mid_str if mid_str is not None else group
    try:
        if target:
            queue_len = int(ctx.env.get_machine_queue_length(str(target)))
    except Exception:
        queue_len = None
    if queue_len is None and stats is not None:
        try:
            if mid_str is not None:
                by_m = getattr(stats, "queue_length_by_machine", {}) or {}
                if str(target) in by_m:
                    queue_len = int(by_m[str(target)])
            else:
                by_g = getattr(stats, "queue_length_by_group", {}) or {}
                if group in by_g:
                    queue_len = int(by_g[group])
        except Exception:
            queue_len = None

    bottleneck_score: Optional[float] = None
    system_utilization: Optional[float] = None
    next_group_load: Optional[int] = None

    try:
        bn_map = getattr(ctx.env, "static_bottlenecks", {}) or {}
        if isinstance(bn_map, dict):
            raw_bn = bn_map.get(group)
            if raw_bn is not None:
                try:
                    bottleneck_score = float(raw_bn)
                except Exception:
                    bottleneck_score = None
        elif isinstance(bn_map, (list, set)):
            bottleneck_score = 1.0 if group in bn_map else 0.0
    except Exception:
        bottleneck_score = None

    if stats is not None:
        try:
            util_by_machine = getattr(stats, "utilization_by_machine", {}) or {}
            vals: List[float] = []
            for v in util_by_machine.values():
                try:
                    vals.append(float(v))
                except Exception:
                    continue
            if vals:
                system_utilization = sum(vals) / float(len(vals))
        except Exception:
            system_utilization = None
        try:
            qlg = getattr(stats, "queue_length_by_group", {}) or {}
            if isinstance(qlg, dict) and group in qlg:
                next_group_load = int(qlg[group])
        except Exception:
            next_group_load = None

    jobs_arrived: Optional[int] = None
    jobs_completed: Optional[int] = None
    jobs_cancelled: Optional[int] = None
    wip_count: Optional[int] = None
    event_counts_str = "{}"

    if stats is not None:
        try:
            jobs_arrived = int(getattr(stats, "num_jobs_arrived", 0))
        except Exception:
            jobs_arrived = None
        try:
            jobs_completed = int(getattr(stats, "num_jobs_completed", 0))
        except Exception:
            jobs_completed = None
        try:
            jobs_cancelled = int(getattr(stats, "num_jobs_cancelled", 0))
        except Exception:
            jobs_cancelled = None
        try:
            wip_count = int(getattr(stats, "wip_count", 0))
        except Exception:
            wip_count = None

        try:
            counters = getattr(stats, "event_counters", {}) or {}
        except Exception:
            counters = {}
        keys = [
            "arrival",
            "cancellation",
            "breakdown",
            "pm",
            "priority_change",
            "ptime_change",
            "route_change",
            "due_date_change",
        ]
        parts: List[str] = []
        for k in keys:
            try:
                v = int(counters.get(k, 0))
            except Exception:
                v = 0
            parts.append(f"{k}={v}")
        event_counts_str = "{" + ", ".join(parts) + "}"

    def _fmt(v: Optional[float]) -> str:
        try:
            if v is None:
                return "NA"
            return f"{float(v):.3f}"
        except Exception:
            return "NA"

    op_repr = "NA"
    if op_idx is not None and total_ops is not None and total_ops > 0:
        op_repr = f"{op_idx}/{total_ops}"

    lines: List[str] = []
    lines.append(f"Observation: inspect_action_details({aid}) =>")
    lines.append("- Local:")
    lines.append(f"  Job = {job_id}")
    lines.append(f"  OpIdx = {op_repr}")
    lines.append(f"  Group = {group}")
    if queue_len is not None:
        lines.append(f"  QueueLen = {queue_len}")
    else:
        lines.append("  QueueLen = NA")
    lines.append(f"  Priority = {_fmt(priority)}")
    lines.append(f"  Slack = {_fmt(slack)}")
    lines.append(f"  Progress = {_fmt(progress)}")

    lines.append("- Structural:")
    lines.append(f"  BottleneckScore(Group={group}) = {_fmt(bottleneck_score)}")
    lines.append(f"  SystemUtilization = {_fmt(system_utilization)}")
    if next_group_load is not None:
        lines.append(f"  NextGroupLoad(Group={group}) = {next_group_load}")
    else:
        lines.append(f"  NextGroupLoad(Group={group}) = NA")

    lines.append("- GlobalEvidence:")
    if jobs_arrived is not None:
        lines.append(f"  JobsArrived = {jobs_arrived}")
    if jobs_completed is not None:
        lines.append(f"  JobsCompleted = {jobs_completed}")
    if jobs_cancelled is not None:
        lines.append(f"  JobsCancelled = {jobs_cancelled}")
    if wip_count is not None:
        lines.append(f"  WIP = {wip_count}")
    lines.append(f"  EventCounts = {event_counts_str}")
    lines.append(
        "(Use this information to reassess the urgency and structural impact of this action, "
        "without relying on any design priors.)",
    )

    return "\n".join(lines)


def _register_all_tools() -> None:
    register_tool("simulate_action", _impl_simulate_action)
    register_tool("inspect_action_details", _impl_inspect_action_details)


_register_all_tools()
