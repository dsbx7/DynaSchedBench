from __future__ import annotations

from typing import Any, Dict, List, Tuple

from pydantic import BaseModel

from .Trajectory import Trajectory


class Violation(BaseModel):
    """Represents a hard-constraint violation detected in a trajectory.
    
    ``type`` is a short identifier such as ``resource_conflict`` or
    ``precedence_violation``. ``details`` carries context such as machine ID,
    job ID, or time interval.
    """

    type: str
    details: Dict[str, Any]


def check_resource_conflicts(traj: Trajectory, *, tol: float = 1e-9) -> List[Violation]:
    """Check that no machine processes two operations at the same time.

    The check uses ``machine.schedule_segments`` from the final snapshot.
    """

    try:
        snap = traj.last_snapshot
    except Exception:
        return []
    violations: List[Violation] = []

    for m in snap.machines:
        segs = sorted(m.schedule_segments, key=lambda s: (s.start, s.end))
        for i in range(len(segs) - 1):
            a = segs[i]
            b = segs[i + 1]
            if a.end > b.start + tol:
                violations.append(
                    Violation(
                        type="resource_conflict",
                        details={
                            "machine_id": m.machine_id,
                            "seg1": a.model_dump(),
                            "seg2": b.model_dump(),
                        },
                    )
                )
    return violations


def check_cancellation_segments(traj: Trajectory, *, tol: float = 1e-9) -> List[Violation]:
    """Check that cancelled jobs do not occupy machine capacity after cancellation.

    If a job has ``cancellation_time`` in the snapshot, no machine segment may
    satisfy ``seg.job_id == job_id`` and ``seg.start >= cancellation_time``.
    Historical segments that started before cancellation are kept as already
    processed work and may still appear in Gantt charts.
    """

    try:
        snap = traj.last_snapshot
    except Exception:
        return []
    violations: List[Violation] = []

    cancel_time_by_job: Dict[str, float] = {}
    for j in snap.jobs:
        if j.cancellation_time is not None:
            cancel_time_by_job[j.job_id] = float(j.cancellation_time)

    if not cancel_time_by_job:
        return []

    for m in snap.machines:
        for seg in m.schedule_segments:
            ct = cancel_time_by_job.get(seg.job_id)
            if ct is None:
                continue
            if seg.start + tol >= ct:
                violations.append(
                    Violation(
                        type="cancelled_job_future_segment",
                        details={
                            "machine_id": m.machine_id,
                            "job_id": seg.job_id,
                            "cancellation_time": ct,
                            "segment": seg.model_dump(),
                        },
                    )
                )

    return violations


def check_precedence(traj: Trajectory, *, tol: float = 1e-9) -> List[Violation]:
    """Check that each job's operations respect technological precedence.

    For each job, operation ``k+1`` must not start before operation ``k`` ends.
    Unfinished operations without ``end_time`` are ignored rather than reported
    as violations.
    """

    try:
        snap = traj.last_snapshot
    except Exception:
        return []
    violations: List[Violation] = []

    for j in snap.jobs:
        ops = sorted(j.ops, key=lambda o: o.index)
        for i in range(len(ops) - 1):
            a = ops[i]
            b = ops[i + 1]
            if a.end_time is None or b.start_time is None:
                continue
            if b.start_time + tol < a.end_time:
                violations.append(
                    Violation(
                        type="precedence_violation",
                        details={
                            "job_id": j.job_id,
                            "op_index": a.index,
                            "op1": a.model_dump(),
                            "op2": b.model_dump(),
                        },
                    )
                )
    return violations


def check_release_times(traj: Trajectory, *, tol: float = 1e-9) -> List[Violation]:
    """Check that no operation starts before its job's release time."""

    try:
        snap = traj.last_snapshot
    except Exception:
        return []
    violations: List[Violation] = []

    for j in snap.jobs:
        for op in j.ops:
            if op.start_time is None:
                continue
            if op.start_time + tol < j.release_time:
                violations.append(
                    Violation(
                        type="release_time_violation",
                        details={
                            "job_id": j.job_id,
                            "op_index": op.index,
                            "release_time": j.release_time,
                            "start_time": op.start_time,
                        },
                    )
                )
    return violations


def check_job_machine_consistency(traj: Trajectory) -> List[Violation]:
    """Check consistency between machine schedule segments and job operations.

    The check has two directions. Forward checks ensure every scheduled
    ``job_id`` exists in the job list and every scheduled ``op_id`` exists in
    the corresponding ``job.ops`` while skipping special segments such as
    ``__DOWNTIME__``. Reverse checks ensure any operation with ``start_time`` or
    ``end_time`` appears in at least one machine schedule segment.
    """

    try:
        snap = traj.last_snapshot
    except Exception:
        return []

    violations: List[Violation] = []

    job_by_id: Dict[str, Any] = {j.job_id: j for j in snap.jobs}
    segs_by_job_op: Dict[Tuple[str, str], List[Any]] = {}

    for m in snap.machines:
        for seg in m.schedule_segments:
            if seg.job_id.startswith("__"):
                continue

            key = (seg.job_id, seg.op_id)
            segs_by_job_op.setdefault(key, []).append(seg)

            job = job_by_id.get(seg.job_id)
            if job is None:
                violations.append(
                    Violation(
                        type="missing_job_for_segment",
                        details={
                            "machine_id": m.machine_id,
                            "segment": seg.model_dump(),
                        },
                    )
                )
                continue

            op = None
            for o in job.ops:
                if o.op_id == seg.op_id:
                    op = o
                    break

            if op is None:
                violations.append(
                    Violation(
                        type="missing_op_for_segment",
                        details={
                            "machine_id": m.machine_id,
                            "job_id": seg.job_id,
                            "op_id": seg.op_id,
                            "segment": seg.model_dump(),
                            "job_ops": [o.op_id for o in job.ops],
                        },
                    )
                )

    for job in snap.jobs:
        for op in job.ops:
            if op.start_time is None and op.end_time is None:
                continue

            key = (job.job_id, op.op_id)
            segs = segs_by_job_op.get(key, [])
            if not segs:
                violations.append(
                    Violation(
                        type="missing_segment_for_op",
                        details={
                            "job_id": job.job_id,
                            "op_id": op.op_id,
                            "op_index": op.index,
                            "start_time": op.start_time,
                            "end_time": op.end_time,
                        },
                    )
                )

    return violations


def check_job_route_consistency(traj: Trajectory) -> List[Violation]:
    """Check that job.ops is consistent with static process templates when applicable.

    When ``plant.process_templates`` exist and no route-change event occurred,
    each job is checked against its template: operation count must match route
    length, operation indices must be contiguous from ``0`` to ``n-1``, machine
    groups must match, and nominal processing times must match template means
    within a tiny floating-point tolerance.
    """

    try:
        snap = traj.last_snapshot
    except Exception:
        return []

    violations: List[Violation] = []

    try:
        route_change_count = snap.system_stats.event_counters.get("route_change", 0)
    except Exception:
        route_change_count = 0

    plant = snap.plant or {}
    templates = plant.get("process_templates") or []
    if not templates:
        return []

    if route_change_count:
        return []

    tpl_by_family: Dict[str, Any] = {}
    for tpl in templates:
        family = tpl.get("family")
        if isinstance(family, str):
            tpl_by_family[family] = tpl

    for j in snap.jobs:
        tpl = tpl_by_family.get(j.family)
        if tpl is None:
            continue

        route = tpl.get("route") or []
        route_len = len(route)

        if j.total_ops != route_len or len(j.ops) != route_len:
            violations.append(
                Violation(
                    type="job_route_mismatch",
                    details={
                        "job_id": j.job_id,
                        "family": j.family,
                        "total_ops": j.total_ops,
                        "num_ops_snapshot": len(j.ops),
                        "num_ops_template": route_len,
                    },
                )
            )

        index_set = {op.index for op in j.ops}
        if index_set and (min(index_set) != 0 or max(index_set) != len(index_set) - 1 or len(index_set) != len(j.ops)):
            violations.append(
                Violation(
                    type="job_op_index_mismatch",
                    details={
                        "job_id": j.job_id,
                        "family": j.family,
                        "indices": sorted(index_set),
                        "expected_range": [0, max(index_set)],
                    },
                )
            )

        ops_by_index = {op.index: op for op in j.ops}
        for idx, step in enumerate(route):
            op = ops_by_index.get(idx)
            if op is None:
                continue

            tpl_group = step.get("machine_group")
            if isinstance(tpl_group, str) and op.machine_group != tpl_group:
                violations.append(
                    Violation(
                        type="job_op_machine_group_mismatch",
                        details={
                            "job_id": j.job_id,
                            "op_index": idx,
                            "expected_group": tpl_group,
                            "actual_group": op.machine_group,
                        },
                    )
                )

            proc_spec = step.get("process_time") or {}
            mean_nominal = proc_spec.get("mean")
            if isinstance(mean_nominal, (int, float)):
                try:
                    if abs(op.proc_time_nominal - float(mean_nominal)) > 1e-6:
                        violations.append(
                            Violation(
                                type="job_op_proc_time_mismatch",
                                details={
                                    "job_id": j.job_id,
                                    "op_index": idx,
                                    "expected_mean": float(mean_nominal),
                                    "actual_nominal": op.proc_time_nominal,
                                },
                            )
                        )
                except Exception:
                    continue

    return violations


def check_completion_stats_consistency(traj: Trajectory) -> List[Violation]:
    """Basic consistency checks between job-level completion data and system stats.

    This check does not require all jobs to finish. It verifies that
    ``num_jobs_total``, completed count, and cancelled count agree with the job
    list and each job's ``completion_time`` or ``cancellation_time``; completed
    jobs have a completion time compatible with their final completed
    operation; and ``system_stats.wip_count`` approximately matches the number
    of active jobs.
    """

    try:
        snap = traj.last_snapshot
    except Exception:
        return []

    violations: List[Violation] = []

    stats = snap.system_stats

    try:
        if stats.num_jobs_total != len(snap.jobs):
            violations.append(
                Violation(
                    type="num_jobs_total_mismatch",
                    details={
                        "num_jobs_total": stats.num_jobs_total,
                        "num_jobs_in_snapshot": len(snap.jobs),
                    },
                )
            )
    except Exception:
        pass

    completed_jobs = [j for j in snap.jobs if j.completion_time is not None]
    cancelled_jobs = [j for j in snap.jobs if j.cancellation_time is not None]

    try:
        if stats.num_jobs_completed != len(completed_jobs):
            violations.append(
                Violation(
                    type="num_jobs_completed_mismatch",
                    details={
                        "num_jobs_completed": stats.num_jobs_completed,
                        "completed_in_snapshot": len(completed_jobs),
                    },
                )
            )
        if stats.num_jobs_cancelled != len(cancelled_jobs):
            violations.append(
                Violation(
                    type="num_jobs_cancelled_mismatch",
                    details={
                        "num_jobs_cancelled": stats.num_jobs_cancelled,
                        "cancelled_in_snapshot": len(cancelled_jobs),
                    },
                )
            )
    except Exception:
        pass

    for j in completed_jobs:
        if j.completion_time is None:
            continue

        unfinished_ops = [op.op_id for op in j.ops if op.end_time is None]
        if unfinished_ops:
            violations.append(
                Violation(
                    type="completed_job_with_unfinished_ops",
                    details={
                        "job_id": j.job_id,
                        "completion_time": j.completion_time,
                        "unfinished_ops": unfinished_ops,
                    },
                )
            )
            continue

        try:
            last_end = max(float(op.end_time) for op in j.ops if op.end_time is not None)
        except ValueError:
            continue

        if last_end > j.completion_time + 1e-9:
            violations.append(
                Violation(
                    type="completion_time_before_last_op_end",
                    details={
                        "job_id": j.job_id,
                        "completion_time": j.completion_time,
                        "last_op_end": last_end,
                    },
                )
            )

    active_jobs = [
        j
        for j in snap.jobs
        if j.completion_time is None and j.cancellation_time is None
    ]

    try:
        if stats.wip_count != len(active_jobs):
            violations.append(
                Violation(
                    type="wip_count_mismatch",
                    details={
                        "wip_count": stats.wip_count,
                        "active_jobs": len(active_jobs),
                    },
                )
            )
    except Exception:
        pass

    return violations


def run_all_checks(traj: Trajectory) -> List[Violation]:
    """Run all built-in hard-constraint checks and return the union of violations."""

    violations: List[Violation] = []
    violations.extend(check_resource_conflicts(traj))
    violations.extend(check_cancellation_segments(traj))
    violations.extend(check_precedence(traj))
    violations.extend(check_release_times(traj))
    violations.extend(check_job_machine_consistency(traj))
    violations.extend(check_job_route_consistency(traj))
    violations.extend(check_completion_stats_consistency(traj))
    return violations
