from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import random

from .config import CognitiveConfig, InfoLevel
from dsbx.Agents.PDRs.rules import (
    JobSelectionRule,
    MachineSelectionRule,
    compute_job_priority,
    precompute_remaining_work,
)


def _build_ready_index(obs: Dict[str, Any]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    ready = obs.get("ready_ops") or []
    index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in ready:
        jid = r.get("job_id")
        group = r.get("machine_group")
        if jid is None or group is None:
            continue
        key = (str(jid), str(group))
        index[key] = r
    return index


def _act_key(action: Dict[str, Any]) -> Tuple[str, str]:
    return str(action.get("job_id")), str(action.get("machine_group"))


def _get_proc_time(
    a: Dict[str, Any],
    ready_index: Dict[Tuple[str, str], Dict[str, Any]],
    *,
    strict: bool,
) -> float:
    key = _act_key(a)
    info = ready_index.get(key) or {}
    v = info.get("process_time")
    try:
        return float(v)
    except Exception:
        if strict:
            raise ValueError(f"Missing/invalid process_time for action key={key}: {v}")
        return 0.0


try:
    _JOB_RULE_NAMES = {r.value.upper() for r in JobSelectionRule}
    _MACHINE_RULE_NAMES = {r.value.upper() for r in MachineSelectionRule}
except Exception:
    _JOB_RULE_NAMES = {
        "SPT",
        "LPT",
        "MWKR",
        "LWKR",
        "MOPNR",
        "LOPNR",
        "FIFO",
        "LIFO",
    }
    _MACHINE_RULE_NAMES = {"LIT", "LWL", "SPT"}

_PDR_COMBOS: List[str] = []
for _jr in sorted(_JOB_RULE_NAMES):
    for _mr in sorted(_MACHINE_RULE_NAMES):
        _PDR_COMBOS.append(f"{_jr}+{_mr}")


@dataclass
class EncodedActions:
    pruned_actions: List[Dict[str, Any]]
    headers: List[str]
    rows: List[List[str]]
    info_level: InfoLevel
    sampling_summary: str = ""
    pdr_rules_used: List[str] = None  # type: ignore[assignment]
    total_legal_actions: int = 0
    max_candidate_actions: int = 0


class ObservationEncoder:
    def __init__(self, cfg: CognitiveConfig) -> None:
        self.cfg = cfg
        self._last_sampling_meta: Dict[str, Any] = {}
        self._pdr_jobs_dict: Dict[str, Any] = {}
        self._pdr_remain_cache: Optional[Dict[Tuple[str, int], float]] = None

    def _score_action_pdr(
        self,
        rule: str,
        action: Dict[str, Any],
        ready_index: Dict[Tuple[str, str], Dict[str, Any]],
    ) -> float:
        jid, group = _act_key(action)
        info = ready_index.get((jid, group)) or {}
        try:
            pt = float(info.get("process_time", 0.0))
        except Exception:
            pt = 0.0
        try:
            op_idx = int(info.get("operation", 0))
        except Exception:
            op_idx = 0
        rem_raw = info.get("remaining_work")
        try:
            rem = float(rem_raw) if rem_raw is not None else None
        except Exception:
            rem = None

        r = (rule or "SPT").upper()
        if "+" in r:
            job_rule = r.split("+", 1)[0].strip()
        else:
            job_rule = r

        if self._pdr_jobs_dict:
            try:
                if job_rule in _JOB_RULE_NAMES:
                    pr_val = compute_job_priority(
                        rule=job_rule,
                        job_id=jid,
                        op_index=op_idx,
                        proc_time=pt,
                        obs={"jobs": self._pdr_jobs_dict},
                        remain_work_cache=self._pdr_remain_cache,
                        is_emergency=False,
                    )
                    return float(pr_val)
            except Exception:
                pass

        if job_rule == "LPT":
            return -pt
        if job_rule == "MWKR":
            if rem is None:
                return float("inf")
            return -rem
        if job_rule == "LWKR":
            if rem is None:
                return float("inf")
            return rem
        return pt

    def _select_top_k_by_rule(
        self,
        rule: str,
        actions: List[Dict[str, Any]],
        ready_index: Dict[Tuple[str, str], Dict[str, Any]],
        k: int,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        if k <= 0 or not actions:
            return [], list(actions)
        scored: List[Tuple[float, int]] = []
        for idx, a in enumerate(actions):
            try:
                score = self._score_action_pdr(rule, a, ready_index)
            except Exception:
                continue
            scored.append((score, idx))
        if not scored:
            return [], list(actions)
        scored.sort(key=lambda x: x[0])
        chosen_idx = {i for _, i in scored[: min(k, len(scored))]}
        selected: List[Dict[str, Any]] = []
        remaining: List[Dict[str, Any]] = []
        for idx, a in enumerate(actions):
            if idx in chosen_idx:
                selected.append(a)
            else:
                remaining.append(a)
        return selected, remaining

    def prune_candidates(
        self,
        obs: Dict[str, Any],
        legal_actions: List[Dict[str, Any]],
        env: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        if not legal_actions:
            self._last_sampling_meta = {}
            return []

        actions = list(legal_actions)
        total = len(actions)
        max_cand_raw = getattr(self.cfg, "max_candidate_actions", 0)
        try:
            max_cand = int(max_cand_raw)
        except Exception:
            max_cand = 0
        if max_cand <= 0 or total <= max_cand:
            self._last_sampling_meta = {
                "sampling_summary": "",
                "pdr_rules_used": [],
                "total_legal_actions": total,
                "max_candidate_actions": max_cand,
            }
            return actions

        L = max_cand
        if L <= 0:
            L = total
        if L > total:
            L = total

        ready_index = _build_ready_index(obs)

        indices = list(range(total))
        random.shuffle(indices)

        half_rand = L // 2
        rand_idx = indices[:half_rand]
        rand_set = set(rand_idx)
        random_part = [actions[i] for i in rand_idx]

        remaining_indices = [i for i in indices if i not in rand_set]
        remaining_actions = [actions[i] for i in remaining_indices]

        pdr_total = L - len(random_part)
        if pdr_total <= 0 or not remaining_actions:
            selected = random_part
            self._last_sampling_meta = {
                "sampling_summary": "",
                "pdr_rules_used": [],
                "total_legal_actions": total,
                "max_candidate_actions": max_cand,
            }
            return selected

        self._pdr_jobs_dict = {}
        self._pdr_remain_cache = None
        if env is not None and hasattr(env, "get_snapshot"):
            try:
                snap = env.get_snapshot()
                jobs_dict: Dict[str, Any] = {}
                for j in getattr(snap, "jobs", []) or []:
                    jid_snap = str(getattr(j, "job_id", ""))
                    if not jid_snap:
                        continue
                    ops_info: List[Dict[str, Any]] = []
                    for op in getattr(j, "ops", []) or []:
                        try:
                            idx_val = int(getattr(op, "index", 0))
                        except Exception:
                            idx_val = 0
                        mg_val = getattr(op, "machine_group", None)
                        ops_info.append(
                            {
                                "index": idx_val,
                                "machine_group": str(mg_val) if mg_val is not None else "",
                                "proc_time_nominal": float(
                                    getattr(op, "proc_time_nominal", 0.0)
                                ),
                                "proc_time_realized": float(
                                    getattr(
                                        op,
                                        "proc_time_realized",
                                        getattr(op, "proc_time_nominal", 0.0),
                                    )
                                ),
                            }
                        )
                    jobs_dict[jid_snap] = {
                        "release_time": float(getattr(j, "release_time", 0.0)),
                        "due_date": float(getattr(j, "due_date", 0.0)),
                        "total_ops": int(
                            getattr(j, "total_ops", len(ops_info))
                        ),
                        "total_work_content": float(
                            getattr(j, "total_work_content", 0.0)
                        ),
                        "remaining_work_content": float(
                            getattr(j, "remaining_work_content", 0.0)
                        ),
                        "priority": float(getattr(j, "priority", 0.0)),
                        "ops": ops_info,
                        "current_op_index": int(
                            getattr(j, "current_op_index", 0)
                        ),
                    }
                if jobs_dict:
                    self._pdr_jobs_dict = jobs_dict
                    try:
                        self._pdr_remain_cache = precompute_remaining_work(jobs_dict)
                    except Exception:
                        self._pdr_remain_cache = None
            except Exception:
                self._pdr_jobs_dict = {}
                self._pdr_remain_cache = None

        pdr_pool = list(_PDR_COMBOS)
        try:
            if len(pdr_pool) >= 2:
                rule1, rule2 = random.sample(pdr_pool, 2)
            elif len(pdr_pool) == 1:
                rule1 = rule2 = pdr_pool[0]
            else:
                rule1, rule2 = "SPT+LIT", "MWKR+LIT"
        except Exception:
            rule1, rule2 = "SPT+LIT", "MWKR+LIT"

        pdr1_n = pdr_total // 2
        pdr2_n = pdr_total - pdr1_n

        pdr1_actions, rem_after_1 = self._select_top_k_by_rule(rule1, remaining_actions, ready_index, pdr1_n)
        pdr2_actions, _ = self._select_top_k_by_rule(rule2, rem_after_1, ready_index, pdr2_n)

        selected = random_part + pdr1_actions + pdr2_actions
        if len(selected) > L:
            selected = selected[:L]

        summary = (
            f"Base candidate set (job+group decisions before expanding machines) truncated: "
            f"{total} base legal actions -> {len(selected)} base candidates. "
            f"Roughly {len(random_part)} were sampled uniformly at random, then the remaining base "
            f"slots were filled by two PDR-style priority rules ({rule1}, {rule2}) without duplicates. "
            f"The markdown table below may contain more rows because each base candidate can expand "
            f"into multiple machine-level options."
        )
        self._last_sampling_meta = {
            "sampling_summary": summary,
            "pdr_rules_used": [rule1, rule2],
            "total_legal_actions": total,
            "max_candidate_actions": max_cand,
        }
        return selected

    def encode(
        self,
        obs: Dict[str, Any],
        legal_actions: List[Dict[str, Any]],
        env: Optional[Any] = None,
    ) -> EncodedActions:
        ready_index = _build_ready_index(obs)
        base_pruned = self.prune_candidates(obs, legal_actions, env=env)
        strict_features = bool(getattr(self.cfg, "strict_features", True))
        level = self.cfg.info_level

        select_machine = bool(getattr(self.cfg, "select_machine", False))

        pruned: List[Dict[str, Any]] = []
        if select_machine:
            for a in base_pruned:
                cands = a.get("machine_candidates") or []
                if not cands:
                    pruned.append(dict(a))
                    continue
                for mid in cands:
                    b = dict(a)
                    b["machine_id"] = mid
                    pruned.append(b)
        else:
            pruned = base_pruned

        t_now = 0.0
        try:
            t_now = float(obs.get("time", 0.0))
        except Exception:
            t_now = 0.0

        dyn = obs.get("dynamic_summary") or {}
        down_machines: set[str] = set()
        emergency_jobs_set: set[str] = set()
        if isinstance(dyn, dict):
            try:
                dm = dyn.get("down_machines") or []
                down_machines = {str(x) for x in dm}
            except Exception:
                down_machines = set()
            try:
                ej = dyn.get("emergency_jobs") or []
                emergency_jobs_set = {str(x) for x in ej}
            except Exception:
                emergency_jobs_set = set()

        machines = obs.get("machines") or {}

        snapshot = None
        job_map: Dict[str, Any] = {}
        system_stats = None
        util_by_machine: Dict[str, float] = {}
        queue_len_by_group: Dict[str, int] = {}
        system_utilization: Optional[float] = None
        horizon: float = 0.0
        if env is not None and hasattr(env, "get_snapshot"):
            try:
                snapshot = env.get_snapshot()
            except Exception:
                snapshot = None
        if snapshot is not None:
            try:
                horizon = float(getattr(snapshot, "horizon", 0.0))
            except Exception:
                horizon = 0.0
            try:
                for j in getattr(snapshot, "jobs", []) or []:
                    jid = str(getattr(j, "job_id", ""))
                    if jid:
                        job_map[jid] = j
            except Exception:
                job_map = {}
            try:
                system_stats = getattr(snapshot, "system_stats", None)
                if system_stats is not None:
                    util_by_machine = dict(getattr(system_stats, "utilization_by_machine", {}) or {})
                    queue_len_by_group = dict(getattr(system_stats, "queue_length_by_group", {}) or {})
            except Exception:
                system_stats = None
                util_by_machine = {}
                queue_len_by_group = {}
        try:
            vals = [float(v) for v in util_by_machine.values()]
            if vals:
                system_utilization = sum(vals) / float(len(vals))
        except Exception:
            system_utilization = None

        headers: List[str] = [
            "ActionID",
            "Job",
            "OpIdx",
            "Group",
        ]
        if select_machine:
            headers.append("Machine")
        headers.append("ProcTime")
        headers.extend([
            "MachineStatus",
            "AvailableFrom",
        ])
        if level in (InfoLevel.LEVEL_2_STATISTICAL, InfoLevel.LEVEL_3_STRUCTURAL):
            headers.extend([
                "QueueLen",
                "Priority",
                "Slack",
                "Progress",
            ])
        if level is InfoLevel.LEVEL_3_STRUCTURAL:
            headers.extend([
                "BottleneckScore",
                "SystemUtilization",
                "NextGroupLoad",
            ])

        rows: List[List[str]] = []
        for idx, a in enumerate(pruned):
            jid, group = _act_key(a)
            info = ready_index.get((jid, group)) or {}
            op_idx = info.get("operation")
            pt = _get_proc_time(a, ready_index, strict=strict_features)
            base: List[str] = [
                str(idx + 1),
                jid,
                str(op_idx) if op_idx is not None else "",
                group,
            ]
            if select_machine:
                mid_val = a.get("machine_id")
                base.append(str(mid_val) if mid_val is not None else "")
            base.append(f"{pt:.3f}")

            status = ""
            avail_from_val: Optional[float] = None
            if select_machine:
                mid_val = a.get("machine_id")
                if mid_val is not None:
                    mid_str = str(mid_val)
                    if mid_str in down_machines:
                        status = "DOWN"
                    else:
                        raw_avail: Optional[float] = None
                        try:
                            v = machines.get(mid_str)
                        except Exception:
                            v = None
                        if v is not None:
                            try:
                                raw_avail = float(v)
                            except Exception:
                                raw_avail = None

                        if raw_avail is not None:
                            # Earliest feasible start at this decision point:
                            # cannot start before either the machine is free
                            # or the current decision time.
                            avail_from_val = max(raw_avail, t_now)
                            if avail_from_val <= t_now + 1e-9:
                                status = "IDLE"
                            else:
                                status = "BUSY"
                        else:
                            status = ""
            else:
                cands = a.get("machine_candidates") or []
                cand_times: List[float] = []
                num_down = 0
                for m in cands:
                    m_str = str(m)
                    if m_str in down_machines:
                        num_down += 1
                    try:
                        v = machines.get(m_str)
                    except Exception:
                        v = None
                    if v is not None:
                        try:
                            raw = float(v)
                        except Exception:
                            continue
                        cand_times.append(max(raw, t_now))
                if cands:
                    if num_down == len(cands):
                        status = "DOWN"
                    else:
                        any_idle = False
                        for v_eff in cand_times:
                            if v_eff <= t_now + 1e-9:
                                any_idle = True
                                break
                        status = "IDLE" if any_idle else "BUSY"
                    if cand_times:
                        try:
                            avail_from_val = min(cand_times)
                        except Exception:
                            avail_from_val = None
            base.append(status)
            base.append(f"{avail_from_val:.3f}" if avail_from_val is not None else "")

            qlen_val: Optional[int] = None
            prio_val: Optional[float] = None
            slack_val: Optional[float] = None
            progress_val: Optional[float] = None

            if level in (InfoLevel.LEVEL_2_STATISTICAL, InfoLevel.LEVEL_3_STRUCTURAL):
                target = None
                if select_machine:
                    target = a.get("machine_id")
                if target is None:
                    target = group
                if env is not None and hasattr(env, "get_machine_queue_length") and target is not None:
                    try:
                        qlen_val = int(env.get_machine_queue_length(str(target)))
                    except Exception:
                        qlen_val = None
                if qlen_val is None and system_stats is not None:
                    try:
                        if select_machine and target is not None:
                            by_m = getattr(system_stats, "queue_length_by_machine", {}) or {}
                            if str(target) in by_m:
                                qlen_val = int(by_m[str(target)])
                        else:
                            by_g = getattr(system_stats, "queue_length_by_group", {}) or {}
                            if group in by_g:
                                qlen_val = int(by_g[group])
                    except Exception:
                        qlen_val = None

                if emergency_jobs_set:
                    is_emergency = jid in emergency_jobs_set
                    prio_val = -1.0 if is_emergency else 0.0
                else:
                    pr_raw = info.get("priority")
                    if pr_raw is not None:
                        try:
                            prio_val = float(pr_raw)
                        except Exception:
                            prio_val = None

                job = job_map.get(jid)
                if job is not None:
                    has_due_date = False
                    due: Optional[float] = None
                    if horizon > 0.0:
                        try:
                            cur_dd_attr = getattr(job, "due_date", None)
                            if cur_dd_attr is not None:
                                cur_dd = float(cur_dd_attr)
                                if cur_dd < horizon - 1e-9:
                                    due = cur_dd
                                    has_due_date = True
                        except Exception:
                            if strict_features:
                                raise ValueError(f"Missing/invalid due_date for job_id={jid}")
                            has_due_date = False

                        if not has_due_date and hasattr(job, "initial_due_date"):
                            try:
                                init_dd = float(getattr(job, "initial_due_date"))
                                if init_dd < horizon - 1e-9:
                                    due = init_dd
                                    has_due_date = True
                            except Exception:
                                if strict_features:
                                    raise ValueError(f"Missing/invalid initial_due_date for job_id={jid}")
                                has_due_date = False
                    else:
                        try:
                            cur_dd_attr = getattr(job, "due_date", None)
                            if cur_dd_attr is not None:
                                due = float(cur_dd_attr)
                                has_due_date = True
                        except Exception:
                            if strict_features:
                                raise ValueError(f"Missing/invalid due_date for job_id={jid}")
                            has_due_date = False

                    rem_work = info.get("remaining_work")
                    if rem_work is None:
                        try:
                            rem_work = float(getattr(job, "remaining_work_content", 0.0))
                        except Exception:
                            if strict_features:
                                raise ValueError(f"Missing/invalid remaining_work_content for job_id={jid}")
                            rem_work = None
                    else:
                        try:
                            rem_work = float(rem_work)
                        except Exception:
                            if strict_features:
                                raise ValueError(f"Missing/invalid remaining_work for job_id={jid}")
                            rem_work = None
                    if has_due_date and due is not None and rem_work is not None:
                        try:
                            slack_val = float(due) - float(t_now) - float(rem_work)
                        except Exception:
                            slack_val = None

                    if op_idx is None:
                        try:
                            op_idx = int(getattr(job, "current_op_index", 0))
                        except Exception:
                            op_idx = None
                    try:
                        total_ops = int(getattr(job, "total_ops", 0))
                    except Exception:
                        total_ops = 0
                    try:
                        if op_idx is not None and total_ops > 0:
                            progress_val = float(int(op_idx) + 1) / float(total_ops)
                    except Exception:
                        progress_val = None

                base.extend([
                    str(qlen_val) if qlen_val is not None else "",
                    f"{prio_val:.0f}" if prio_val is not None else "",
                    f"{slack_val:.3f}" if slack_val is not None else "",
                    f"{progress_val:.3f}" if progress_val is not None else "",
                ])

            if level is InfoLevel.LEVEL_3_STRUCTURAL:
                bottleneck = ""
                sys_util_str = ""
                next_group_load = ""

                if env is not None and hasattr(env, "static_bottlenecks"):
                    sb = getattr(env, "static_bottlenecks")
                    if isinstance(sb, dict):
                        score = sb.get(group)
                        if score is not None:
                            try:
                                bottleneck = f"{float(score):.3f}"
                            except Exception:
                                bottleneck = ""
                    elif isinstance(sb, (list, set)):
                        bottleneck = "1" if group in sb else "0"

                if system_utilization is not None:
                    try:
                        sys_util_str = f"{float(system_utilization):.3f}"
                    except Exception:
                        sys_util_str = ""

                if queue_len_by_group:
                    try:
                        if group in queue_len_by_group:
                            next_group_load = str(int(queue_len_by_group[group]))
                    except Exception:
                        next_group_load = ""

                base.extend([
                    bottleneck,
                    sys_util_str,
                    next_group_load,
                ])

            rows.append(base)

        sampling_meta = getattr(self, "_last_sampling_meta", {}) or {}
        sampling_summary = str(sampling_meta.get("sampling_summary", ""))
        pdr_rules_used = sampling_meta.get("pdr_rules_used") or []
        total_legal_actions = int(sampling_meta.get("total_legal_actions", len(legal_actions)))
        max_candidate_actions = 0
        try:
            max_candidate_actions = int(
                sampling_meta.get(
                    "max_candidate_actions",
                    getattr(self.cfg, "max_candidate_actions", 0),
                )
            )
        except Exception:
            max_candidate_actions = 0

        return EncodedActions(
            pruned_actions=pruned,
            headers=headers,
            rows=rows,
            info_level=level,
            sampling_summary=sampling_summary,
            pdr_rules_used=list(pdr_rules_used),
            total_legal_actions=total_legal_actions,
            max_candidate_actions=max_candidate_actions,
        )
