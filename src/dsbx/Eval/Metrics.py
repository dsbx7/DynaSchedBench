from __future__ import annotations

from typing import Dict, Any, List, Optional

import numpy as np

from .Trajectory import Trajectory


METRIC_STATIC_KEYS: List[str] = [
    "makespan",
    "total_flow_time",
    "mean_flow_time",
    "avg_flow_time_emergency",
    "avg_flow_time_normal",
    "flow_time_ratio_emergency_vs_normal",
    "total_tardiness",
    "mean_tardiness",
    "num_tardy_jobs",
    "total_weighted_tardiness",
    "throughput",
    "max_wip",
    "mean_wip",
    "max_wip_waiting",
    "mean_wip_waiting",
    "max_wip_processing",
    "mean_wip_processing",
    "num_jobs_total",
    "num_jobs_completed",
    "num_jobs_cancelled",
    "job_completion_ratio",
    "job_cancellation_ratio",
    "ratio_jobs_with_due",
    "final_wip",
    "final_wip_waiting",
    "final_wip_processing",
    "max_queue_length_total",
    "mean_queue_length_total",
    "final_queue_length_total",
    "avg_utilization_global",
    "max_utilization_global",
    "min_utilization_global",
    "utilization_cv_global",
    "mean_num_ops_per_job",
    "mean_work_content_per_job",
]


METRIC_DYNAMIC_KEYS: List[str] = [
    "avg_changed_ops_ratio",
    "avg_start_time_shift",
    "max_start_time_shift",
    "reschedule_steps",
    "reschedule_frequency",
    "schedule_edit_intensity",
]


METRIC_ALL_KEYS: List[str] = METRIC_STATIC_KEYS + METRIC_DYNAMIC_KEYS


def compute_static_metrics(traj: Trajectory, start_time: float = 0.0) -> Dict[str, float]:
    """Compute static, end-of-run metrics from a trajectory.

    The calculation mainly uses job data from the final snapshot, including
    completion time, arrival time, and due date.
    """

    try:
        snap = traj.last_snapshot
    except Exception:
        # Empty trajectory (no snapshots available)
        return {}
    jobs = snap.jobs
    if not jobs:
        return {}

    completion_times: List[float] = []
    flow_times: List[float] = []
    flow_times_emergency: List[float] = []
    flow_times_normal: List[float] = []
    tardiness_list: List[float] = []
    weighted_tardiness_list: List[float] = []

    horizon = float(getattr(snap, "horizon", 0.0))

    emergency_threshold: Optional[float] = None
    dyn_cfg = getattr(snap, "dynamic_scenarios", None) or {}
    if isinstance(dyn_cfg, dict):
        val = dyn_cfg.get("emergency_priority")
        try:
            emergency_threshold = float(val)
        except (TypeError, ValueError):
            emergency_threshold = None

    for j in jobs:
        if j.completion_time is not None:
            c = float(j.completion_time)
        else:
            c = float(snap.time)
        completion_times.append(c)

        flow = c - float(j.release_time)
        flow_times.append(flow)

        is_emergency = False
        if emergency_threshold is not None:
            try:
                is_emergency = float(getattr(j, "priority", 0.0)) <= emergency_threshold
            except (TypeError, ValueError):
                is_emergency = False
        if is_emergency:
            flow_times_emergency.append(flow)
        else:
            flow_times_normal.append(flow)

        has_due_date = False
        if horizon > 0.0:
            try:
                cur_dd = float(j.due_date)
                if cur_dd < horizon - 1e-9:
                    has_due_date = True
            except (TypeError, ValueError):
                has_due_date = False

            if not has_due_date and hasattr(j, "initial_due_date"):
                try:
                    init_dd = float(j.initial_due_date)
                    has_due_date = init_dd < horizon - 1e-9
                except (TypeError, ValueError):
                    has_due_date = False

        if has_due_date:
            tard = max(0.0, c - float(j.due_date))
            tardiness_list.append(tard)

            base_w = float(j.weight or 1.0)
            w = base_w
            if is_emergency:
                w = 10.0 * base_w
            weighted_tardiness_list.append(w * tard)

    makespan = max(completion_times) if completion_times else float(snap.time)
    total_flow_time = float(sum(flow_times))
    mean_flow_time = total_flow_time / len(flow_times) if flow_times else 0.0

    avg_flow_time_emergency = float(sum(flow_times_emergency) / len(flow_times_emergency)) if flow_times_emergency else 0.0
    avg_flow_time_normal = float(sum(flow_times_normal) / len(flow_times_normal)) if flow_times_normal else 0.0
    if avg_flow_time_normal > 0.0 and avg_flow_time_emergency > 0.0:
        flow_time_ratio = float(avg_flow_time_emergency / avg_flow_time_normal)
    else:
        flow_time_ratio = 0.0

    total_tardiness = float(sum(tardiness_list))
    num_jobs_with_due = float(len(tardiness_list))
    mean_tardiness = total_tardiness / num_jobs_with_due if num_jobs_with_due > 0 else 0.0
    num_tardy_jobs = float(sum(1 for t in tardiness_list if t > 1e-9))

    total_weighted_tardiness = float(sum(weighted_tardiness_list))

    num_completed = float(sum(1 for j in jobs if j.status == "completed"))
    min_release = min(float(j.release_time) for j in jobs) if jobs else 0.0
    horizon = max(float(snap.time) - min_release, 1e-9)
    throughput = num_completed / horizon

    wip_values: List[float] = []
    wip_waiting_values: List[float] = []
    wip_processing_values: List[float] = []
    queue_values: List[float] = []

    use_summary = bool(
        getattr(traj, "_file_path", None) is not None
        and getattr(traj, "_mode", "full") == "summary"
        and hasattr(traj, "iter_summaries")
    )

    if use_summary:
        for rec in traj.iter_summaries():  # type: ignore[attr-defined]
            t = float(rec.get("time", 0.0))
            if t < float(start_time):
                continue
            wip_waiting = float(rec.get("wip_waiting", 0.0))
            wip_processing = float(rec.get("wip_processing", 0.0))
            wip = wip_waiting + wip_processing
            qlen = float(rec.get("queue_total", 0.0))
            wip_values.append(float(wip))
            wip_waiting_values.append(float(wip_waiting))
            wip_processing_values.append(float(wip_processing))
            queue_values.append(float(qlen))
    else:
        for step in traj.iter_steps():
            s = step.snapshot
            if float(getattr(s, "time", 0.0)) < float(start_time):
                continue
            wip_waiting = sum(1 for j in s.jobs if j.status == "waiting")
            wip_processing = sum(1 for j in s.jobs if j.status == "processing")
            wip = wip_waiting + wip_processing
            qlen = sum(len(m.queue) for m in s.machines)
            wip_values.append(float(wip))
            wip_waiting_values.append(float(wip_waiting))
            wip_processing_values.append(float(wip_processing))
            queue_values.append(float(qlen))

    max_wip = max(wip_values) if wip_values else 0.0
    mean_wip = float(np.mean(wip_values)) if wip_values else 0.0

    max_wip_waiting = max(wip_waiting_values) if wip_waiting_values else 0.0
    mean_wip_waiting = float(np.mean(wip_waiting_values)) if wip_waiting_values else 0.0

    max_wip_processing = max(wip_processing_values) if wip_processing_values else 0.0
    mean_wip_processing = float(np.mean(wip_processing_values)) if wip_processing_values else 0.0

    max_queue_len = max(queue_values) if queue_values else 0.0
    mean_queue_len = float(np.mean(queue_values)) if queue_values else 0.0
    final_queue_len = queue_values[-1] if queue_values else 0.0

    num_jobs_total = float(len(jobs))
    num_jobs_completed = float(sum(1 for j in jobs if j.status == "completed"))
    num_jobs_cancelled = float(sum(1 for j in jobs if j.status == "cancelled"))
    job_completion_ratio = num_jobs_completed / max(1.0, num_jobs_total)
    job_cancellation_ratio = num_jobs_cancelled / max(1.0, num_jobs_total)
    final_wip_waiting = float(sum(1 for j in jobs if j.status == "waiting"))
    final_wip_processing = float(sum(1 for j in jobs if j.status == "processing"))
    final_wip = final_wip_waiting + final_wip_processing

    utils = list(snap.system_stats.utilization_by_machine.values()) if hasattr(snap, "system_stats") else []
    if utils:
        avg_util = float(np.mean(utils))
        max_util = float(np.max(utils))
        min_util = float(np.min(utils))
        util_cv = float(np.std(utils) / avg_util) if avg_util > 0 and len(utils) >= 2 else 0.0
    else:
        avg_util = 0.0
        max_util = 0.0
        min_util = 0.0
        util_cv = 0.0

    num_ops_per_job = [float(j.total_ops) for j in jobs]
    work_content_per_job = [float(j.total_work_content) for j in jobs]
    mean_num_ops_per_job = float(np.mean(num_ops_per_job)) if num_ops_per_job else 0.0
    mean_work_content_per_job = float(np.mean(work_content_per_job)) if work_content_per_job else 0.0

    metrics: Dict[str, float] = {
        "makespan": float(makespan),
        "total_flow_time": total_flow_time,
        "mean_flow_time": mean_flow_time,
        "avg_flow_time_emergency": avg_flow_time_emergency,
        "avg_flow_time_normal": avg_flow_time_normal,
        "flow_time_ratio_emergency_vs_normal": flow_time_ratio,
        "total_tardiness": total_tardiness,
        "mean_tardiness": mean_tardiness,
        "num_tardy_jobs": num_tardy_jobs,
        "total_weighted_tardiness": total_weighted_tardiness,
        "throughput": float(throughput),
        "max_wip": float(max_wip),
        "mean_wip": float(mean_wip),
        "max_wip_waiting": float(max_wip_waiting),
        "mean_wip_waiting": float(mean_wip_waiting),
        "max_wip_processing": float(max_wip_processing),
        "mean_wip_processing": float(mean_wip_processing),
    }

    metrics.update(
        {
            "num_jobs_total": num_jobs_total,
            "num_jobs_completed": num_jobs_completed,
            "num_jobs_cancelled": num_jobs_cancelled,
            "job_completion_ratio": job_completion_ratio,
            "job_cancellation_ratio": job_cancellation_ratio,
            "ratio_jobs_with_due": num_jobs_with_due / max(1.0, num_jobs_total),
            "final_wip": final_wip,
            "final_wip_waiting": final_wip_waiting,
            "final_wip_processing": final_wip_processing,
            "max_queue_length_total": float(max_queue_len),
            "mean_queue_length_total": float(mean_queue_len),
            "final_queue_length_total": float(final_queue_len),
            "avg_utilization_global": avg_util,
            "max_utilization_global": max_util,
            "min_utilization_global": min_util,
            "utilization_cv_global": util_cv,
            "mean_num_ops_per_job": mean_num_ops_per_job,
            "mean_work_content_per_job": mean_work_content_per_job,
        }
    )

    return metrics


def compute_dynamic_metrics(traj: Trajectory, start_time: float = 0.0) -> Dict[str, float]:
    """Compute dynamic / stability-related metrics from a trajectory.

    The calculation uses ``stability_stats`` and dispatch counts across all
    snapshots.
    """

    changed_ratios: List[float] = []
    avg_shifts: List[float] = []
    max_shifts: List[float] = []
    reschedule_steps = 0

    has_seen_first = False
    num_decision_points = 0

    use_summary = bool(
        getattr(traj, "_file_path", None) is not None
        and getattr(traj, "_mode", "full") == "summary"
        and hasattr(traj, "iter_summaries")
    )

    if use_summary:
        for rec in traj.iter_summaries():  # type: ignore[attr-defined]
            if not has_seen_first:
                has_seen_first = True
                continue

            t = float(rec.get("time", 0.0))
            if t < float(start_time):
                continue

            num_decision_points += 1
            changed_ratios.append(float(rec.get("changed_ops_ratio", 0.0)))
            avg_shifts.append(float(rec.get("avg_start_time_shift", 0.0)))
            max_shifts.append(float(rec.get("max_start_time_shift", 0.0)))

            has_decision = bool(rec.get("has_decision", False))
            action_info = rec.get("action")
            if has_decision or action_info:
                reschedule_steps += 1
    else:
        for step in traj.iter_steps():
            if not has_seen_first:
                has_seen_first = True
                continue

            s = step.snapshot
            if float(getattr(s, "time", 0.0)) < float(start_time):
                continue

            num_decision_points += 1
            st = step.snapshot.stability_stats
            changed_ratios.append(float(st.changed_ops_ratio))
            avg_shifts.append(float(st.avg_start_time_shift))
            max_shifts.append(float(st.max_start_time_shift))
            if step.action is not None:
                reschedule_steps += 1

    if not changed_ratios or num_decision_points == 0:
        return {
            "avg_changed_ops_ratio": 0.0,
            "avg_start_time_shift": 0.0,
            "max_start_time_shift": 0.0,
            "reschedule_steps": 0.0,
            "reschedule_frequency": 0.0,
            "schedule_edit_intensity": 0.0,
        }

    last_time = float(traj.last_snapshot.time)
    effective_horizon = max(last_time - float(start_time), 1e-9)
    num_decision_points = max(1, num_decision_points)

    return {
        "avg_changed_ops_ratio": float(np.mean(changed_ratios)) if changed_ratios else 0.0,
        "avg_start_time_shift": float(np.mean(avg_shifts)) if avg_shifts else 0.0,
        "max_start_time_shift": float(max(max_shifts)) if max_shifts else 0.0,
        "reschedule_steps": float(reschedule_steps),
        "reschedule_frequency": float(reschedule_steps) / effective_horizon,
        "schedule_edit_intensity": float(reschedule_steps) / float(num_decision_points),
    }


def evaluate_trajectory(traj: Trajectory, start_time: float = 0.0) -> Dict[str, float]:
    """High-level entry point: compute a consolidated metric dictionary."""

    metrics: Dict[str, float] = {}
    metrics.update(compute_static_metrics(traj, start_time=start_time))
    metrics.update(compute_dynamic_metrics(traj, start_time=start_time))
    return metrics
