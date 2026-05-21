from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from dsbx.Sim.Snapshot import JobOpSnapshot, JobSnapshot, MachineSnapshot, Snapshot


@dataclass
class _QueueStats:
    count_by_group: Dict[str, int]
    work_by_group: Dict[str, float]
    entries_by_group: Dict[str, List[Dict[str, float]]]
    ready_time_by_group: Dict[str, float]


def _build_queue_stats(snapshot: Snapshot) -> _QueueStats:
    count_by_group: Dict[str, int] = {}
    work_by_group: Dict[str, float] = {}
    entries_by_group: Dict[str, List[Dict[str, float]]] = {}
    ready_time_by_group: Dict[str, float] = {}

    op_by_id: Dict[str, JobOpSnapshot] = {}
    for j in snapshot.jobs:
        for op in j.ops:
            op_by_id[op.op_id] = op

    for m in snapshot.machines:
        g = m.group
        ready_time_by_group[g] = min(ready_time_by_group.get(g, m.available_from), m.available_from)
        q_list = entries_by_group.setdefault(g, [])
        for q in m.queue:
            # Store a shallow copy and enrich with machine_id for potential debugging.
            entry = dict(q)
            entry.setdefault("machine_id", m.machine_id)
            q_list.append(entry)

    for g, q_list in entries_by_group.items():
        count = len(q_list)
        total_work = 0.0
        for q in q_list:
            op_id = str(q.get("op_id", ""))
            op = op_by_id.get(op_id)
            if op is None:
                continue
            try:
                total_work += float(op.remaining_time)
            except Exception:
                continue
        count_by_group[g] = count
        work_by_group[g] = total_work

    return _QueueStats(
        count_by_group=count_by_group,
        work_by_group=work_by_group,
        entries_by_group=entries_by_group,
        ready_time_by_group=ready_time_by_group,
    )


def build_jobshop_attributes(
    snapshot: Snapshot,
    job: JobSnapshot,
    op: JobOpSnapshot,
    machine_group: str,
    queue_stats: _QueueStats | None = None,
) -> Dict[str, float]:
    """Approximate JobShopAttribute values from a DynaSchedBench snapshot.

    Attribute names follow yimei.jss.gp.terminal.JobShopAttribute#getName(), e.g.::
        "t", "NIQ", "WIQ", "MRT", "PT", "NPT", "ORT", "NRT", "WKR",
        "NOR", "WINQ", "NINQ", "FDD", "DD", "W", "AT", "MWT",
        "OWT", "NWT", "rFDD", "rDD", "TIS", "SL".
    """

    snap = snapshot
    t = float(snap.time)

    if queue_stats is None:
        queue_stats = _build_queue_stats(snap)

    g = str(machine_group)
    niq = float(queue_stats.count_by_group.get(g, 0))
    wiq = float(queue_stats.work_by_group.get(g, 0.0))
    mrt = float(queue_stats.ready_time_by_group.get(g, snap.time))

    # Find this operation's arrival_to_queue_time if present.
    ort = float(job.release_time)
    entries = queue_stats.entries_by_group.get(g, [])
    for e in entries:
        if str(e.get("job_id")) == str(job.job_id) and str(e.get("op_id")) == str(op.op_id):
            try:
                ort = float(e.get("arrival_to_queue_time", ort))
            except Exception:
                pass
            break

    owt = t - ort
    mwt = t - mrt

    # Operation-level values
    pt = float(op.proc_time_realized)
    wkr = float(job.remaining_work_content)
    nor = float(max(0, job.total_ops - (op.index + 1)))

    # Next-operation-related attributes
    npt = 0.0
    nrt = t
    winq = 0.0
    ninq = 0.0

    if op.index + 1 < len(job.ops):
        next_op: JobOpSnapshot = job.ops[op.index + 1]
        npt = float(next_op.proc_time_realized)
        next_group = str(next_op.machine_group)
        nrt = float(queue_stats.ready_time_by_group.get(next_group, snap.time))
        ninq = float(queue_stats.count_by_group.get(next_group, 0))
        winq = float(queue_stats.work_by_group.get(next_group, 0.0))

    nwt = nrt - t

    # Due dates and weights
    dd = float(job.due_date)
    fdd = dd  # DynaSchedBench does not distinguish flow due date; align with DD.
    base_w = float(job.weight)
    at = float(job.release_time)

    try:
        raw_priority = float(getattr(job, "priority", 1.0))
    except Exception:
        raw_priority = 1.0
    priority_clamped = max(0.0, min(raw_priority, 5.0))
    priority_factor = 1.0 + 0.2 * (priority_clamped - 1.0)

    try:
        rework_count = int(getattr(op, "rework_count", 0))
    except Exception:
        rework_count = 0
    if rework_count > 0:
        rework_factor = 1.0 + 0.1 * min(rework_count, 3)
    else:
        rework_factor = 1.0

    w = base_w * max(0.1, priority_factor * rework_factor)

    rfdd = fdd - t
    rdd = dd - t

    tis = t - at
    sl = dd - t - wkr

    attrs: Dict[str, float] = {
        "t": t,
        "NIQ": niq,
        "WIQ": wiq,
        "MRT": mrt,
        "MWT": mwt,
        "PT": pt,
        "NPT": npt,
        "ORT": ort,
        "OWT": owt,
        "NRT": nrt,
        "NWT": nwt,
        "WKR": wkr,
        "NOR": nor,
        "WINQ": winq,
        "NINQ": ninq,
        "FDD": fdd,
        "DD": dd,
        "W": w,
        "AT": at,
        "rFDD": rfdd,
        "rDD": rdd,
        "TIS": tis,
        "SL": sl,
    }

    return attrs
