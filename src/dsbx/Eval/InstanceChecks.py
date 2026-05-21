from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import TypeAdapter

from dsbx.Gen import InputModel
from dsbx.Sim.Events import (
    Event,
    ArrivalEvent,
    DueDateEvent,
    DueDateChangeEvent,
    BreakdownEvent,
    PreventiveMaintenanceEvent,
    MachineRepairCompletionEvent,
    PriorityChangeEvent,
    OrderCancellationEvent,
    ProcessTimeChangeEvent,
    RouteChangeEvent,
)
from dsbx.Gen.core.feasibility import FeasibilityProjector
from dsbx.Gen.core.validator import InstanceValidator


def _is_finite_number(x: Any) -> bool:
    try:
        v = float(x)
    except Exception:
        return False
    return math.isfinite(v)


def strict_validate_events(
    model: InputModel,
    events: List[Event],
    *,
    max_messages: int = 50,
    allow_unknown_jobs: bool = False,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    errors_truncated = False
    warnings_truncated = False

    def add_error(msg: str) -> None:
        nonlocal errors_truncated
        if len(errors) >= max_messages:
            errors_truncated = True
            return
        errors.append(msg)

    def add_warning(msg: str) -> None:
        nonlocal warnings_truncated
        if len(warnings) >= max_messages:
            warnings_truncated = True
            return
        warnings.append(msg)

    def add_unknown_job(msg: str) -> None:
        if allow_unknown_jobs:
            add_warning(msg)
        else:
            add_error(msg)

    template_families: set[str] = set()
    family_route_groups: Dict[str, List[str]] = {}
    template_route_conflicts: set[str] = set()
    for pt in model.plant.process_templates:
        fam = getattr(pt, "family", None)
        if isinstance(fam, str) and fam:
            template_families.add(fam)
        route = getattr(pt, "route", None)
        if not isinstance(route, list) or not route:
            continue
        groups: List[str] = []
        ok = True
        for step in route:
            g = getattr(step, "machine_group", None)
            if not isinstance(g, str) or not g:
                ok = False
                break
            groups.append(g)
        if not ok:
            continue
        if not isinstance(fam, str) or not fam:
            continue
        existing = family_route_groups.get(fam)
        if existing is None:
            family_route_groups[fam] = groups
        else:
            if len(existing) != len(groups) or any(a != b for a, b in zip(existing, groups)):
                template_route_conflicts.add(fam)

    machine_ids = {m.id for m in model.plant.machines}
    machine_groups = {m.group for m in model.plant.machines}
    group_to_machines: Dict[str, List[str]] = {}
    max_speed_by_group: Dict[str, float] = {}
    machine_id_count: Dict[str, int] = {}
    for m in model.plant.machines:
        machine_id_count[m.id] = machine_id_count.get(m.id, 0) + 1
        group_to_machines.setdefault(m.group, []).append(m.id)
        try:
            sp = float(getattr(m, "speed", 1.0))
        except Exception:
            sp = 1.0
        if not math.isfinite(sp) or sp <= 0:
            add_warning(f"Invalid machine speed for machine_id={m.id}: {getattr(m, 'speed', None)}")
            sp = 1.0
        prev = max_speed_by_group.get(m.group)
        if prev is None or sp > prev:
            max_speed_by_group[m.group] = sp

    dup_mids = sorted([mid for mid, c in machine_id_count.items() if c > 1])
    if dup_mids:
        add_error(f"Duplicate machine ids in InputModel: {dup_mids}")

    clashes = sorted(machine_ids.intersection(machine_groups))
    if clashes:
        add_warning(f"Machine id and group id clash in InputModel: {clashes}")

    if template_route_conflicts:
        add_warning(
            "Process templates for some job families have inconsistent route shapes; "
            f"strict ARRIVAL routing-vs-template checks are skipped for families={sorted(template_route_conflicts)}"
        )

    horizon: Optional[float]
    try:
        horizon = float(getattr(model.scale, "horizon", None))
    except Exception:
        horizon = None
    if horizon is not None and (not math.isfinite(horizon) or horizon <= 0):
        horizon = None

    grid = None
    try:
        grid = float(getattr(getattr(model, "meta", None), "grid", None))
    except Exception:
        grid = None
    if grid is not None and (not math.isfinite(grid) or grid <= 0):
        grid = None

    arrivals: Dict[str, ArrivalEvent] = {}
    arrival_counts: Dict[str, int] = {}
    arrival_time: Dict[str, float] = {}
    arrival_type: Dict[str, str] = {}
    arrival_families: set[str] = set()
    batch_id_by_job: Dict[str, Optional[str]] = {}
    min_proc_time_lb: Dict[str, float] = {}
    route_len: Dict[str, int] = {}
    route_len_lower: Dict[str, int] = {}
    route_len_upper: Dict[str, int] = {}
    due_date_set_seen: set[str] = set()
    due_date_current: Dict[str, float] = {}
    due_date_change_seen: set[str] = set()
    cancel_time: Dict[str, float] = {}

    due_date_set_count: Dict[str, int] = {}
    breakdown_active_until: Dict[str, float] = {}
    breakdown_active_start: Dict[str, float] = {}
    downtime_until_breakdown: Dict[str, float] = {}
    downtime_until_pm: Dict[str, float] = {}

    arrival_ids_all: set[str] = set()
    for ev in events:
        if isinstance(ev, ArrivalEvent):
            jid = getattr(ev, "job_id", None)
            if not isinstance(jid, str) or not jid:
                continue
            arrival_ids_all.add(jid)
            try:
                tt = float(getattr(ev, "time"))
            except Exception:
                tt = None
            if tt is not None and math.isfinite(tt):
                prev_tt = arrival_time.get(jid)
                if prev_tt is None or tt < prev_tt:
                    arrival_time[jid] = tt
                    atype = getattr(ev, "arrival_type", None)
                    if isinstance(atype, str) and atype:
                        arrival_type[jid] = atype
                else:
                    atype = getattr(ev, "arrival_type", None)
                    if isinstance(atype, str) and atype and arrival_type.get(jid) not in (None, atype):
                        add_warning(
                            f"Inconsistent ARRIVAL arrival_type for job_id={jid}: seen={arrival_type.get(jid)} new={atype}"
                        )

    if not events:
        add_warning("Events list is empty.")

    jobs_total = None
    num_machines_cfg = None
    num_job_families_cfg = None
    try:
        jobs_total = int(getattr(getattr(model, "scale", None), "jobs_total", None))
    except Exception:
        jobs_total = None
    try:
        num_machines_cfg = int(getattr(getattr(model, "scale", None), "num_machines", None))
    except Exception:
        num_machines_cfg = None
    try:
        num_job_families_cfg = int(getattr(getattr(model, "scale", None), "num_job_families", None))
    except Exception:
        num_job_families_cfg = None

    if isinstance(jobs_total, int) and jobs_total > 0 and not arrival_ids_all:
        add_error(f"No ARRIVAL events found, but model.scale.jobs_total={jobs_total}")

    if isinstance(jobs_total, int) and jobs_total >= 0 and arrival_ids_all:
        non_wip_arrivals: set[str] = set()
        for ev in events:
            if not isinstance(ev, ArrivalEvent):
                continue
            jid = getattr(ev, "job_id", None)
            if not isinstance(jid, str) or not jid:
                continue
            atype = getattr(ev, "arrival_type", None)
            if atype == "initial_wip":
                continue
            non_wip_arrivals.add(jid)
        if jobs_total > 0:
            num_non_wip = len(non_wip_arrivals)
            if num_non_wip != jobs_total:
                add_warning(
                    f"Number of non-initial ARRIVAL jobs {num_non_wip} does not match model.scale.jobs_total={jobs_total}"
                )

    if isinstance(num_machines_cfg, int) and num_machines_cfg >= 0:
        if num_machines_cfg != len(machine_ids):
            add_error(
                f"model.scale.num_machines={num_machines_cfg} does not match number of machines in plant={len(machine_ids)}"
            )

    prev_t_input: Optional[float] = None
    prev_et_input: Optional[str] = None
    for idx, ev in enumerate(events):
        try:
            tt = float(getattr(ev, "time"))
        except Exception:
            continue
        if not math.isfinite(tt):
            continue
        if prev_t_input is not None and tt < prev_t_input - 1e-12:
            add_warning(
                f"Input events not sorted by time at index={idx}: "
                f"prev_type={prev_et_input} prev_time={prev_t_input:.6g} "
                f"curr_type={getattr(ev, 'event_type', None)} curr_time={tt:.6g}"
            )
            break
        prev_t_input = tt
        prev_et_input = getattr(ev, "event_type", None)

    prev_key_input: Optional[Tuple[float, int]] = None
    prev_et_key_input: Optional[str] = None
    for idx, ev in enumerate(events):
        try:
            tt = float(getattr(ev, "time"))
        except Exception:
            continue
        if not math.isfinite(tt):
            continue
        try:
            pr = int(getattr(ev, "priority", 100))
        except Exception:
            pr = 100
        key = (tt, pr)
        if prev_key_input is not None and key < prev_key_input:
            add_warning(
                f"Input events not sorted by (time, priority) at index={idx}: "
                f"prev_type={prev_et_key_input} prev_key=({prev_key_input[0]:.6g},{prev_key_input[1]}) "
                f"curr_type={getattr(ev, 'event_type', None)} curr_key=({key[0]:.6g},{key[1]})"
            )
            break
        prev_key_input = key
        prev_et_key_input = getattr(ev, "event_type", None)

    try:
        events_sorted = sorted(events, key=lambda e: (float(e.time), getattr(e, "priority", 100)))
        if events_sorted != events:
            add_warning("Events are not sorted by (time, priority); strict checks use sorted order.")
    except Exception:
        events_sorted = list(events)
        add_warning("Events could not be sorted by (time, priority); strict checks use input order.")

    scenarios = getattr(model, "dynamic_scenarios", None)
    try:
        cancellation_rate = float(getattr(scenarios, "cancellation_rate", 0.0) or 0.0)
    except Exception:
        cancellation_rate = 0.0
    try:
        priority_change_rate = float(getattr(scenarios, "priority_change_rate", 0.0) or 0.0)
    except Exception:
        priority_change_rate = 0.0
    try:
        emergency_job_ratio = float(getattr(scenarios, "emergency_job_ratio", 0.0) or 0.0)
    except Exception:
        emergency_job_ratio = 0.0
    try:
        ptime_change_rate = float(getattr(scenarios, "ptime_change_rate", 0.0) or 0.0)
    except Exception:
        ptime_change_rate = 0.0
    try:
        route_change_probability = float(getattr(scenarios, "route_change_probability", 0.0) or 0.0)
    except Exception:
        route_change_probability = 0.0
    try:
        due_date_change_probability = float(getattr(scenarios, "due_date_change_probability", 0.0) or 0.0)
    except Exception:
        due_date_change_probability = 0.0
    try:
        pm_interval = float(getattr(scenarios, "pm_interval", 0.0) or 0.0)
    except Exception:
        pm_interval = 0.0
    try:
        batch_arrival_probability = float(getattr(scenarios, "batch_arrival_probability", 0.0) or 0.0)
    except Exception:
        batch_arrival_probability = 0.0
    try:
        emergency_priority = int(getattr(scenarios, "emergency_priority", -1))
    except Exception:
        emergency_priority = -1
    try:
        normal_priority_change_value = int(getattr(scenarios, "normal_priority_change_value", 0))
    except Exception:
        normal_priority_change_value = 0

    batch_arrival_count = 0
    priority_change_count = 0
    priority_change_emergency_count = 0
    priority_change_normal_count = 0
    cancellation_count = 0
    ptime_change_count = 0
    route_change_count = 0
    due_date_change_count = 0
    pm_count = 0

    emergency_arrival_jobs: set[str] = set()
    emergency_priority_change_jobs: set[str] = set()
    priority_change_by_job: Dict[str, List[Tuple[float, int]]] = {}

    for ev in events_sorted:
        if isinstance(ev, ArrivalEvent):
            atype = getattr(ev, "arrival_type", None)
            bid = getattr(ev, "batch_id", None)
            if atype != "initial_wip" and isinstance(bid, str) and bid:
                batch_arrival_count += 1
            jid = getattr(ev, "job_id", None)
            if isinstance(jid, str) and jid and atype == "emergency":
                emergency_arrival_jobs.add(jid)
        elif isinstance(ev, PriorityChangeEvent):
            priority_change_count += 1
            jid = getattr(ev, "job_id", None)
            try:
                t_ev = float(getattr(ev, "time"))
            except Exception:
                t_ev = float("nan")
            try:
                npv = int(getattr(ev, "new_priority"))
            except Exception:
                npv = normal_priority_change_value
            if isinstance(jid, str) and jid and math.isfinite(t_ev):
                priority_change_by_job.setdefault(jid, []).append((t_ev, npv))
            if npv == emergency_priority:
                priority_change_emergency_count += 1
                if isinstance(jid, str) and jid:
                    emergency_priority_change_jobs.add(jid)
            if npv != emergency_priority:
                priority_change_normal_count += 1
        elif isinstance(ev, OrderCancellationEvent):
            cancellation_count += 1
        elif isinstance(ev, ProcessTimeChangeEvent):
            ptime_change_count += 1
        elif isinstance(ev, RouteChangeEvent):
            route_change_count += 1
        elif isinstance(ev, DueDateChangeEvent):
            due_date_change_count += 1
        elif isinstance(ev, PreventiveMaintenanceEvent):
            pm_count += 1

    if cancellation_rate <= 0.0 + 1e-12 and cancellation_count > 0:
        add_error(
            f"ORDER_CANCELLATION events present but dynamic_scenarios.cancellation_rate={cancellation_rate:.6g}: count={cancellation_count}"
        )
    if ptime_change_rate <= 0.0 + 1e-12 and ptime_change_count > 0:
        add_error(
            f"PTIME_CHANGE events present but dynamic_scenarios.ptime_change_rate={ptime_change_rate:.6g}: count={ptime_change_count}"
        )
    if route_change_probability <= 0.0 + 1e-12 and route_change_count > 0:
        add_error(
            f"ROUTE_CHANGE events present but dynamic_scenarios.route_change_probability={route_change_probability:.6g}: count={route_change_count}"
        )
    if due_date_change_probability <= 0.0 + 1e-12 and due_date_change_count > 0:
        add_error(
            f"DUE_DATE_CHANGE events present but dynamic_scenarios.due_date_change_probability={due_date_change_probability:.6g}: count={due_date_change_count}"
        )
    if pm_interval <= 0.0 + 1e-12 and pm_count > 0:
        add_error(
            f"PREVENTIVE_MAINTENANCE events present but dynamic_scenarios.pm_interval={pm_interval:.6g}: count={pm_count}"
        )
    if batch_arrival_probability <= 0.0 + 1e-12 and batch_arrival_count > 0:
        add_error(
            f"Batch ARRIVAL events present but dynamic_scenarios.batch_arrival_probability={batch_arrival_probability:.6g}: count={batch_arrival_count}"
        )

    if emergency_job_ratio <= 0.0 + 1e-12:
        if emergency_arrival_jobs:
            add_error(
                f"Emergency ARRIVAL events present but dynamic_scenarios.emergency_job_ratio={emergency_job_ratio:.6g}: count={len(emergency_arrival_jobs)}"
            )
        if emergency_priority != normal_priority_change_value and priority_change_emergency_count > 0:
            add_error(
                f"Emergency PRIORITY_CHANGE events present but dynamic_scenarios.emergency_job_ratio={emergency_job_ratio:.6g}: count={priority_change_emergency_count}"
            )

    if priority_change_rate <= 0.0 + 1e-12:
        if emergency_job_ratio <= 0.0 + 1e-12 and priority_change_count > 0:
            add_error(
                f"PRIORITY_CHANGE events present but dynamic_scenarios.priority_change_rate={priority_change_rate:.6g} and emergency_job_ratio={emergency_job_ratio:.6g}: count={priority_change_count}"
            )
        if emergency_job_ratio > 0.0 + 1e-12 and emergency_priority != normal_priority_change_value and priority_change_normal_count > 0:
            add_error(
                f"Non-emergency PRIORITY_CHANGE events present but dynamic_scenarios.priority_change_rate={priority_change_rate:.6g}: count={priority_change_normal_count}"
            )

    if emergency_job_ratio > 0.0 + 1e-12 and emergency_arrival_jobs and emergency_priority != normal_priority_change_value:
        for jid in sorted(emergency_arrival_jobs):
            # Batch-expanded jobs inherit arrival_type but the constructor does not generate
            # matching PRIORITY_CHANGE events for them. Also, even for non-batch jobs,
            # priority changes may be skipped if there is not enough time remaining.
            if isinstance(jid, str) and "-B" in jid:
                continue

            at = arrival_time.get(jid)
            pcs = priority_change_by_job.get(jid, [])
            if not pcs:
                continue

            ok = False
            for (tt, npv) in pcs:
                if at is not None and tt < at - 1e-12:
                    continue
                if npv == emergency_priority:
                    ok = True
                    break
            if not ok:
                add_error(
                    f"Emergency ARRIVAL has PRIORITY_CHANGE but none sets emergency_priority for job_id={jid} (emergency_priority={emergency_priority})"
                )

    if grid is not None and grid > 1e-12:
        # grid-based alignment checks are intentionally disabled; no messages are emitted.
        pass

    key_counts: Dict[Tuple[float, int], int] = {}
    key_types: Dict[Tuple[float, int], List[str]] = {}
    for ev in events_sorted:
        try:
            key = (float(getattr(ev, "time")), int(getattr(ev, "priority", 100)))
        except Exception:
            continue
        key_counts[key] = key_counts.get(key, 0) + 1
        if key_counts[key] <= 5:
            key_types.setdefault(key, []).append(str(getattr(ev, "event_type", None)))

    dup_keys = [(k, c) for (k, c) in key_counts.items() if c > 1]

    for ev in events_sorted:
        et = getattr(ev, "event_type", None)
        t = None
        try:
            t = float(ev.time)
        except Exception:
            pass

        if t is None or not math.isfinite(t):
            add_error(f"Event {et} has non-finite time: {getattr(ev, 'time', None)}")
            continue

        if t is not None and t < 0:
            add_error(f"Event {et} has negative time t={t:.6g}")

        if horizon is not None:
            if t > horizon * 1.5 + 1e-12:
                add_warning(
                    f"Event {et} time far beyond horizon (t={t:.6g} > horizon={horizon:.6g})"
                )
            elif t > horizon * 1.01 + 1e-12:
                add_warning(
                    f"Event {et} time exceeds horizon (t={t:.6g} > horizon={horizon:.6g})"
                )

        if et == "ARRIVAL" and isinstance(ev, ArrivalEvent):
            jid = getattr(ev, "job_id", None)
            if not jid:
                add_error("ARRIVAL missing job_id")
            else:
                arrival_counts[jid] = arrival_counts.get(jid, 0) + 1
                if arrival_counts[jid] > 1:
                    add_error(f"Duplicate ARRIVAL for job_id={jid} (count={arrival_counts[jid]})")
                arrivals.setdefault(jid, ev)
                if t is not None:
                    arrival_time.setdefault(jid, t)
                atype = getattr(ev, "arrival_type", None)
                if isinstance(atype, str) and atype:
                    arrival_type.setdefault(jid, atype)

                bid = getattr(ev, "batch_id", None)
                if bid is not None:
                    if not isinstance(bid, str) or not bid:
                        add_error(f"ARRIVAL invalid batch_id for job_id={jid}: {bid}")
                    else:
                        prev_bid = batch_id_by_job.get(jid)
                        if prev_bid is not None and prev_bid != bid:
                            add_error(f"ARRIVAL inconsistent batch_id for job_id={jid}: {prev_bid} vs {bid}")
                        batch_id_by_job[jid] = bid

            fam = getattr(ev, "job_family", None)
            if not fam:
                add_error(f"ARRIVAL missing job_family for job_id={jid}")
            elif template_families and fam not in template_families:
                add_error(f"ARRIVAL job_family not in process_templates for job_id={jid}: {fam}")
            else:
                if isinstance(fam, str):
                    arrival_families.add(fam)

            routing = getattr(ev, "routing", None)
            pt = getattr(ev, "process_times", None)
            if not isinstance(routing, list) or not routing:
                add_error(f"ARRIVAL missing/invalid routing for job_id={jid}")
            else:
                for g in routing:
                    if not isinstance(g, str) or not g or g not in machine_groups:
                        add_error(f"ARRIVAL routing references invalid machine group for job_id={jid}: {g}")
                        break

            if not isinstance(pt, list) or not pt:
                add_error(f"ARRIVAL missing/invalid process_times for job_id={jid}")
            else:
                for x in pt:
                    if not _is_finite_number(x) or float(x) <= 0:
                        add_error(f"ARRIVAL process_times must be finite and > 0 for job_id={jid}")
                        break
                    if float(x) > 10000:
                        add_warning(f"ARRIVAL unusually large process_time for job_id={jid}: {float(x):.6g}")

            if isinstance(routing, list) and isinstance(pt, list) and routing and pt:
                if len(routing) != len(pt):
                    add_error(
                        f"ARRIVAL routing/process_times length mismatch for job_id={jid}: {len(routing)} vs {len(pt)}"
                    )
                else:
                    rl = len(routing)
                    route_len[jid] = rl
                    route_len_lower[jid] = rl
                    route_len_upper[jid] = rl
                    if isinstance(fam, str) and fam in family_route_groups and fam not in template_route_conflicts:
                        tmpl_route = family_route_groups[fam]
                        if len(tmpl_route) != len(routing) or any(str(g) != str(tg) for g, tg in zip(routing, tmpl_route)):
                            add_error(
                                f"ARRIVAL routing does not match process_templates.route for job_id={jid} family={fam}: "
                                f"routing={list(map(str, routing))} template_route={list(map(str, tmpl_route))}"
                            )
                    try:
                        lb = 0.0
                        for g, x in zip(routing, pt):
                            sp = max_speed_by_group.get(str(g), 1.0)
                            sp = sp if sp > 1e-9 else 1.0
                            lb += float(x) / sp
                        min_proc_time_lb[jid] = float(lb)
                    except Exception:
                        pass

        if et == "BREAKDOWN" and isinstance(ev, BreakdownEvent):
            mid = getattr(ev, "machine_id", None)
            dur = getattr(ev, "duration", None)
            if not isinstance(mid, str) or not mid:
                add_error("BREAKDOWN missing machine_id")
            else:
                mid_is_machine = mid in machine_ids
                mid_is_group = mid in machine_groups
                if not mid_is_machine and not mid_is_group:
                    add_error(f"BREAKDOWN unknown machine_id/group={mid}")
                if mid_is_machine and mid_is_group:
                    add_warning(
                        f"BREAKDOWN machine_id matches both machine and group id: {mid} (treated as machine by simulator)"
                    )
            if not _is_finite_number(dur):
                add_error(f"BREAKDOWN invalid duration for machine_id={mid}: {dur}")
            elif float(dur) < 0:
                add_error(f"BREAKDOWN negative duration for machine_id={mid}: {dur}")
            elif float(dur) == 0:
                add_warning(f"BREAKDOWN zero duration for machine_id={mid}")
            else:
                if isinstance(mid, str) and mid:
                    targets = [mid] if mid in machine_ids else group_to_machines.get(mid, [])
                    for tm in targets:
                        cur = breakdown_active_until.get(tm, -float("inf"))
                        start = t if t is not None else 0.0
                        end = start + float(dur)
                        if horizon is not None and end > horizon * 1.01 + 1e-12:
                            add_warning(
                                f"BREAKDOWN end exceeds horizon for machine_id={tm} (end={end:.6g} > horizon={horizon:.6g})"
                            )
                        prev_dt = max(
                            downtime_until_breakdown.get(tm, -float("inf")),
                            downtime_until_pm.get(tm, -float("inf")),
                        )
                        if prev_dt > -float("inf") and start < prev_dt - 1e-9:
                            add_warning(
                                f"Overlapping downtime events for machine_id={tm} (start={start:.6g} < active_until={prev_dt:.6g})"
                            )
                        cur_end = breakdown_active_until.get(tm)
                        if cur_end is not None and start <= cur_end + 1e-9:
                            s0 = breakdown_active_start.get(tm, start)
                            breakdown_active_start[tm] = min(s0, start)
                            breakdown_active_until[tm] = max(cur_end, end)
                        else:
                            breakdown_active_start[tm] = start
                            breakdown_active_until[tm] = end
                        downtime_until_breakdown[tm] = max(downtime_until_breakdown.get(tm, -float("inf")), breakdown_active_until[tm])

        if et == "PREVENTIVE_MAINTENANCE" and isinstance(ev, PreventiveMaintenanceEvent):
            mid = getattr(ev, "machine_id", None)
            dur = getattr(ev, "duration", None)
            if not isinstance(mid, str) or not mid:
                add_error("PREVENTIVE_MAINTENANCE missing machine_id")
            else:
                mid_is_machine = mid in machine_ids
                mid_is_group = mid in machine_groups
                if not mid_is_machine and not mid_is_group:
                    add_error(f"PREVENTIVE_MAINTENANCE unknown machine_id/group={mid}")
                if mid_is_machine and mid_is_group:
                    add_warning(
                        f"PREVENTIVE_MAINTENANCE machine_id matches both machine and group id: {mid} (treated as machine by simulator)"
                    )
            if not _is_finite_number(dur):
                add_error(f"PREVENTIVE_MAINTENANCE invalid duration for machine_id={mid}: {dur}")
            elif float(dur) < 0:
                add_error(f"PREVENTIVE_MAINTENANCE negative duration for machine_id={mid}: {dur}")
            elif float(dur) == 0:
                add_warning(f"PREVENTIVE_MAINTENANCE zero duration for machine_id={mid}")
            else:
                if isinstance(mid, str) and mid:
                    targets = [mid] if mid in machine_ids else group_to_machines.get(mid, [])
                    for tm in targets:
                        start = t if t is not None else 0.0
                        end = start + float(dur)
                        if horizon is not None and end > horizon * 1.01 + 1e-12:
                            add_warning(
                                f"PREVENTIVE_MAINTENANCE end exceeds horizon for machine_id={tm} (end={end:.6g} > horizon={horizon:.6g})"
                            )
                        prev_dt = max(
                            downtime_until_breakdown.get(tm, -float("inf")),
                            downtime_until_pm.get(tm, -float("inf")),
                        )
                        if prev_dt > -float("inf") and start < prev_dt - 1e-9:
                            add_error(
                                f"Overlapping downtime events for machine_id={tm} (start={start:.6g} < active_until={prev_dt:.6g})"
                            )
                            continue
                        downtime_until_pm[tm] = max(downtime_until_pm.get(tm, -float("inf")), end)

        if et == "REPAIR_COMPLETION" and isinstance(ev, MachineRepairCompletionEvent):
            mid = getattr(ev, "machine_id", None)
            if not isinstance(mid, str) or not mid:
                add_error("REPAIR_COMPLETION missing machine_id")
            elif mid not in machine_ids:
                add_error(f"REPAIR_COMPLETION machine_id must be a concrete machine id, got: {mid}")
            else:
                end = breakdown_active_until.get(mid)
                start = breakdown_active_start.get(mid)
                if end is None or start is None:
                    add_error(f"REPAIR_COMPLETION but no prior BREAKDOWN recorded for machine_id={mid}")
                elif t is not None:
                    if t < start - 1e-12:
                        add_error(
                            f"REPAIR_COMPLETION before BREAKDOWN start for machine_id={mid} (t={t:.6g} < start={start:.6g})"
                        )
                    elif t > end + 1e-12:
                        add_error(
                            f"REPAIR_COMPLETION after BREAKDOWN end for machine_id={mid} (t={t:.6g} > end={end:.6g})"
                        )
                    else:
                        breakdown_active_until[mid] = min(end, t)
                if t is not None and mid in downtime_until_breakdown:
                    downtime_until_breakdown[mid] = min(downtime_until_breakdown.get(mid, t), t)

        jid = getattr(ev, "job_id", None)
        if et == "DUE_DATE_SET" and isinstance(ev, DueDateEvent):
            if not jid:
                add_error("DUE_DATE_SET missing job_id")
            elif jid not in arrival_ids_all:
                add_unknown_job(f"DUE_DATE_SET for unknown job_id={jid}")
            else:
                if jid in due_date_change_seen:
                    add_warning(f"DUE_DATE_SET occurs after DUE_DATE_CHANGE for job_id={jid} (may override prior changes)")
                due_date_set_count[jid] = due_date_set_count.get(jid, 0) + 1
                if due_date_set_count[jid] > 1:
                    add_error(f"Duplicate DUE_DATE_SET for job_id={jid} (count={due_date_set_count[jid]})")
                due_date_set_seen.add(jid)
                at = arrival_time.get(jid)
                if at is None:
                    add_warning(f"DUE_DATE_SET cannot validate ARRIVAL time (missing/invalid ARRIVAL time) for job_id={jid}")
                if t is not None and at is not None and t < at - 1e-12:
                    add_error(f"DUE_DATE_SET before ARRIVAL for job_id={jid} (t={t:.6g} < arrival={at:.6g})")
                if t is not None and at is not None and t > at + 1e-9:
                    add_warning(
                        f"DUE_DATE_SET occurs after ARRIVAL time for job_id={jid} (t={t:.6g} > arrival={at:.6g})"
                    )
                if jid in cancel_time and t is not None and t > cancel_time[jid] + 1e-12:
                    add_warning(f"DUE_DATE_SET after ORDER_CANCELLATION for job_id={jid} (t={t:.6g} > cancel={cancel_time[jid]:.6g})")
                dd = getattr(ev, "due_date", None)
                if not _is_finite_number(dd):
                    add_error(f"DUE_DATE_SET invalid due_date for job_id={jid}: {dd}")
                else:
                    ddv = float(dd)
                    if ddv < t - 1e-12:
                        add_error(
                            f"DUE_DATE_SET due_date earlier than event time for job_id={jid} (due_date={ddv:.6g} < t={t:.6g})"
                        )
                    at = arrival_time.get(jid)
                    if at is not None and ddv < at - 1e-12:
                        add_error(
                            f"DUE_DATE_SET due_date before ARRIVAL for job_id={jid} (due_date={ddv:.6g} < arrival={at:.6g})"
                        )
                    if at is not None and abs(ddv - at) < 1e-6:
                        add_error(f"DUE_DATE_SET due_date equals ARRIVAL time (zero slack) for job_id={jid}")
                    lb = min_proc_time_lb.get(jid)
                    if at is not None and lb is not None:
                        slack = ddv - at
                        eps = max(1e-6, lb * 1e-6)
                        late_set = t is not None and t > at + 1e-9
                        if slack < lb - eps:
                            if late_set:
                                add_error(
                                    f"DUE_DATE_SET slack less than min possible process time for job_id={jid} "
                                    f"(slack={slack:.6g} < min_time_lb={lb:.6g}); DUE_DATE_SET occurs after ARRIVAL, "
                                    f"so feasibility depends on schedule state"
                                )
                            else:
                                add_error(
                                    f"DUE_DATE_SET slack less than min possible process time for job_id={jid} (slack={slack:.6g} < min_time_lb={lb:.6g})"
                                )
                        elif slack < lb * 1.05:
                            add_warning(
                                f"DUE_DATE_SET very tight due_date for job_id={jid} (slack={slack:.6g}, min_time_lb={lb:.6g})"
                            )
                    if horizon is not None and ddv > horizon * 1.5 + 1e-12:
                        add_warning(
                            f"DUE_DATE_SET due_date far beyond horizon for job_id={jid} (due_date={ddv:.6g} > horizon={horizon:.6g})"
                        )
                    due_date_current[jid] = ddv

        if et == "DUE_DATE_CHANGE" and isinstance(ev, DueDateChangeEvent):
            if not jid:
                add_error("DUE_DATE_CHANGE missing job_id")
            elif jid not in arrival_ids_all:
                add_unknown_job(f"DUE_DATE_CHANGE for unknown job_id={jid}")
            else:
                due_date_change_seen.add(jid)
                if jid not in due_date_set_seen and arrival_type.get(jid) != "initial_wip":
                    add_warning(f"DUE_DATE_CHANGE before any DUE_DATE_SET for job_id={jid}")
                at = arrival_time.get(jid)
                if at is None:
                    add_warning(
                        f"DUE_DATE_CHANGE cannot validate ARRIVAL time (missing/invalid ARRIVAL time) for job_id={jid}"
                    )
                if t is not None and at is not None and t < at - 1e-12:
                    add_error(f"DUE_DATE_CHANGE before ARRIVAL for job_id={jid} (t={t:.6g} < arrival={at:.6g})")
                if jid in cancel_time and t is not None and t > cancel_time[jid] + 1e-12:
                    add_warning(f"DUE_DATE_CHANGE after ORDER_CANCELLATION for job_id={jid} (t={t:.6g} > cancel={cancel_time[jid]:.6g})")
                nd = getattr(ev, "new_due_date", None)
                if not _is_finite_number(nd):
                    add_error(f"DUE_DATE_CHANGE invalid new_due_date for job_id={jid}: {nd}")
                else:
                    ndv = float(nd)
                    prev_dd = due_date_current.get(jid)
                    if prev_dd is not None:
                        if abs(ndv - prev_dd) < 1e-9:
                            add_warning(f"DUE_DATE_CHANGE new_due_date equals previous due_date for job_id={jid} (due_date={ndv:.6g})")
                        reason = getattr(ev, "reason", None)
                        if isinstance(reason, str):
                            rlow = reason.lower()
                            if "relax" in rlow and ndv < prev_dd - 1e-9:
                                add_warning(
                                    f"DUE_DATE_CHANGE reason suggests relaxation but due date tightened for job_id={jid} "
                                    f"(prev_due_date={prev_dd:.6g} new_due_date={ndv:.6g} reason={reason})"
                                )
                    if t is not None and float(nd) < t - 1e-12:
                        add_error(
                            f"DUE_DATE_CHANGE new_due_date earlier than event time for job_id={jid} "
                            f"(new_due_date={float(nd):.6g} < t={t:.6g})"
                        )
                    if at is not None and float(nd) < at - 1e-12:
                        add_error(
                            f"DUE_DATE_CHANGE new_due_date before ARRIVAL for job_id={jid} "
                            f"(new_due_date={float(nd):.6g} < arrival={at:.6g})"
                        )
                    lb = min_proc_time_lb.get(jid)
                    if at is not None and lb is not None:
                        slack = float(nd) - at
                        eps = max(1e-6, lb * 1e-6)
                        if slack < lb - eps:
                            add_error(
                                f"DUE_DATE_CHANGE slack less than min possible process time from ARRIVAL for job_id={jid} "
                                f"(slack={slack:.6g} < min_time_lb={lb:.6g}); feasibility may depend on schedule state"
                            )
                        elif slack < lb * 1.05:
                            add_warning(
                                f"DUE_DATE_CHANGE very tight new_due_date for job_id={jid} (slack={slack:.6g}, min_time_lb={lb:.6g})"
                            )
                    if horizon is not None and float(nd) > horizon * 1.5 + 1e-12:
                        add_warning(
                            f"DUE_DATE_CHANGE new_due_date far beyond horizon for job_id={jid} "
                            f"(new_due_date={float(nd):.6g} > horizon={horizon:.6g})"
                        )
                    due_date_current[jid] = ndv

        if et == "PRIORITY_CHANGE" and isinstance(ev, PriorityChangeEvent):
            if not jid:
                add_error("PRIORITY_CHANGE missing job_id")
            elif jid not in arrival_ids_all:
                add_unknown_job(f"PRIORITY_CHANGE for unknown job_id={jid}")
            else:
                at = arrival_time.get(jid)
                if at is None:
                    add_warning(
                        f"PRIORITY_CHANGE cannot validate ARRIVAL time (missing/invalid ARRIVAL time) for job_id={jid}"
                    )
                if t is not None and at is not None and t < at - 1e-12:
                    add_error(f"PRIORITY_CHANGE before ARRIVAL for job_id={jid} (t={t:.6g} < arrival={at:.6g})")
                if jid in cancel_time and t is not None and t > cancel_time[jid] + 1e-12:
                    add_warning(f"PRIORITY_CHANGE after ORDER_CANCELLATION for job_id={jid} (t={t:.6g} > cancel={cancel_time[jid]:.6g})")
                np = getattr(ev, "new_priority", None)
                if not isinstance(np, int):
                    add_error(f"PRIORITY_CHANGE invalid new_priority for job_id={jid}: {np}")

        if et == "ORDER_CANCELLATION" and isinstance(ev, OrderCancellationEvent):
            if not jid:
                add_error("ORDER_CANCELLATION missing job_id")
            elif jid not in arrival_ids_all:
                add_unknown_job(f"ORDER_CANCELLATION for unknown job_id={jid}")
            else:
                if t is not None:
                    if jid in cancel_time:
                        add_error(f"Duplicate ORDER_CANCELLATION for job_id={jid} (t={t:.6g})")
                    cancel_time.setdefault(jid, t)
                at = arrival_time.get(jid)
                if at is None:
                    add_warning(
                        f"ORDER_CANCELLATION cannot validate ARRIVAL time (missing/invalid ARRIVAL time) for job_id={jid}"
                    )
                if t is not None and at is not None and t < at - 1e-12:
                    add_error(f"ORDER_CANCELLATION before ARRIVAL for job_id={jid} (t={t:.6g} < arrival={at:.6g})")

        if et == "PTIME_CHANGE" and isinstance(ev, ProcessTimeChangeEvent):
            if not jid:
                add_error("PTIME_CHANGE missing job_id")
            elif jid not in arrival_ids_all:
                add_unknown_job(f"PTIME_CHANGE for unknown job_id={jid}")
            else:
                at = arrival_time.get(jid)
                if at is None:
                    add_warning(
                        f"PTIME_CHANGE cannot validate ARRIVAL time (missing/invalid ARRIVAL time) for job_id={jid}"
                    )
                if t is not None and at is not None and t < at - 1e-12:
                    add_error(f"PTIME_CHANGE before ARRIVAL for job_id={jid} (t={t:.6g} < arrival={at:.6g})")
                if jid in cancel_time and t is not None and t > cancel_time[jid] + 1e-12:
                    add_warning(f"PTIME_CHANGE after ORDER_CANCELLATION for job_id={jid} (t={t:.6g} > cancel={cancel_time[jid]:.6g})")
                si = getattr(ev, "step_index", None)
                if not isinstance(si, int):
                    add_error(f"PTIME_CHANGE invalid step_index type for job_id={jid}: {si}")
                else:
                    if si < 0:
                        add_error(f"PTIME_CHANGE negative step_index for job_id={jid}: {si}")
                    ru = route_len_upper.get(jid)
                    rl = route_len_lower.get(jid)
                    if ru is not None and si >= ru:
                        add_error(
                            f"PTIME_CHANGE step_index out of range for job_id={jid}: step_index={si} route_len_upper={ru}"
                        )
                    elif ru is None and rl is None:
                        add_error(f"PTIME_CHANGE cannot validate step_index bounds (missing route info) for job_id={jid}")
                npt = getattr(ev, "new_process_time", None)
                if not _is_finite_number(npt) or float(npt) <= 0:
                    add_error(f"PTIME_CHANGE invalid new_process_time for job_id={jid}: {npt}")
                elif float(npt) > 10000:
                    add_warning(f"PTIME_CHANGE unusually large new_process_time for job_id={jid}: {float(npt):.6g}")

        if et == "ROUTE_CHANGE" and isinstance(ev, RouteChangeEvent):
            if not jid:
                add_error("ROUTE_CHANGE missing job_id")
            elif jid not in arrival_ids_all:
                add_unknown_job(f"ROUTE_CHANGE for unknown job_id={jid}")
            else:
                at = arrival_time.get(jid)
                if at is None:
                    add_warning(
                        f"ROUTE_CHANGE cannot validate ARRIVAL time (missing/invalid ARRIVAL time) for job_id={jid}"
                    )
                if t is not None and at is not None and t < at - 1e-12:
                    add_error(f"ROUTE_CHANGE before ARRIVAL for job_id={jid} (t={t:.6g} < arrival={at:.6g})")
                if jid in cancel_time and t is not None and t > cancel_time[jid] + 1e-12:
                    add_warning(f"ROUTE_CHANGE after ORDER_CANCELLATION for job_id={jid} (t={t:.6g} > cancel={cancel_time[jid]:.6g})")
                new_r = getattr(ev, "new_routing", None)
                new_p = getattr(ev, "new_process_times", None)
                if not isinstance(new_r, list) or not new_r:
                    add_error(f"ROUTE_CHANGE missing/invalid new_routing for job_id={jid}")
                if not isinstance(new_p, list) or not new_p:
                    add_error(f"ROUTE_CHANGE missing/invalid new_process_times for job_id={jid}")
                if isinstance(new_r, list) and isinstance(new_p, list) and new_r and new_p:
                    if len(new_r) != len(new_p):
                        add_error(
                            f"ROUTE_CHANGE length mismatch for job_id={jid}: new_routing={len(new_r)} new_process_times={len(new_p)}"
                        )
                    if any((not _is_finite_number(x) or float(x) <= 0) for x in new_p):
                        add_error(f"ROUTE_CHANGE non-positive new_process_times for job_id={jid}")
                    if any((_is_finite_number(x) and float(x) > 10000) for x in new_p):
                        add_warning(f"ROUTE_CHANGE unusually large new_process_times for job_id={jid}")
                    for g in new_r:
                        if not isinstance(g, str) or not g or g not in machine_groups:
                            add_error(f"ROUTE_CHANGE new_routing references invalid machine group for job_id={jid}: {g}")
                            break
                fs = getattr(ev, "from_step", None)
                if fs is not None:
                    if not isinstance(fs, int):
                        add_error(f"ROUTE_CHANGE invalid from_step type for job_id={jid}: {fs}")
                    else:
                        if fs < 0:
                            add_error(f"ROUTE_CHANGE negative from_step for job_id={jid}: {fs}")
                        ru = route_len_upper.get(jid)
                        rl = route_len_lower.get(jid)
                        if ru is not None and fs > ru:
                            add_error(
                                f"ROUTE_CHANGE from_step out of range for job_id={jid}: from_step={fs} route_len_upper={ru}"
                            )
                        elif ru is not None and rl is not None and fs == ru and rl < ru:
                            add_warning(
                                f"ROUTE_CHANGE from_step equals route_len_upper but route length is uncertain for job_id={jid}: "
                                f"from_step={fs} route_len_lower={rl} route_len_upper={ru}"
                            )

                if isinstance(new_r, list) and isinstance(new_p, list) and new_r and new_p and len(new_r) == len(new_p):
                    fs_val = getattr(ev, "from_step", 0)
                    if isinstance(fs_val, int) and fs_val >= 0:
                        old_u = route_len_upper.get(jid)
                        if old_u is None:
                            base = fs_val
                        else:
                            base = max(old_u, fs_val)
                        new_u = base + len(new_r)
                        route_len_upper[jid] = new_u
                        route_len_lower[jid] = fs_val + len(new_r)
                        route_len[jid] = new_u
                        if route_len_lower.get(jid) is not None and route_len_upper.get(jid) is not None:
                            if route_len_lower[jid] > route_len_upper[jid]:
                                add_error(
                                    f"ROUTE_CHANGE produced inconsistent route length bounds for job_id={jid}: "
                                    f"route_len_lower={route_len_lower[jid]} route_len_upper={route_len_upper[jid]}"
                                )

        if hasattr(ev, "machine_id") and getattr(ev, "machine_id") is not None:
            mid = getattr(ev, "machine_id")
            if mid not in machine_ids and mid not in machine_groups:
                add_error(f"Event {et} references non-existent machine_id/group={mid}")

    if isinstance(num_job_families_cfg, int) and num_job_families_cfg >= 0 and arrival_families:
        actual_families = len(arrival_families)
        if actual_families > num_job_families_cfg:
            add_error(
                f"Number of job families in ARRIVAL events ({actual_families}) exceeds model.scale.num_job_families={num_job_families_cfg}"
            )
        elif actual_families < num_job_families_cfg:
            add_warning(
                f"Number of job families in ARRIVAL events ({actual_families}) less than model.scale.num_job_families={num_job_families_cfg}"
            )

    missing_dd_by_type: Dict[str, List[str]] = {}
    for jid in arrivals.keys():
        if jid in due_date_set_seen:
            continue
        atype = arrival_type.get(jid)
        if atype == "initial_wip":
            continue
        key = atype if isinstance(atype, str) and atype else "unknown"
        missing_dd_by_type.setdefault(key, []).append(jid)

    for atype, jids in sorted(missing_dd_by_type.items(), key=lambda x: (x[0], len(x[1]))):
        if not jids:
            continue
        shown = jids[:10]
        add_warning(
            f"No DUE_DATE_SET found for arrival_type={atype}: count={len(jids)} examples={shown}"
        )
        if len(jids) > len(shown):
            add_warning(f"... and {len(jids) - len(shown)} more jobs missing DUE_DATE_SET for arrival_type={atype}")

    batch_to_jobs: Dict[str, List[str]] = {}
    for jid, bid in batch_id_by_job.items():
        if isinstance(bid, str) and bid:
            batch_to_jobs.setdefault(bid, []).append(jid)

    for bid, jids in sorted(batch_to_jobs.items(), key=lambda x: (-len(x[1]), x[0])):
        if len(jids) == 1:
            add_warning(f"Batch has a single job: batch_id={bid} job_id={jids[0]}")
            continue

        times: List[float] = []
        types: set[str] = set()
        for jid in jids:
            at = arrival_time.get(jid)
            if at is not None and math.isfinite(at):
                times.append(at)
            atype = arrival_type.get(jid)
            if isinstance(atype, str) and atype:
                types.add(atype)
        if times:
            t0 = min(times)
            t1 = max(times)
            if t1 - t0 > 1e-9:
                add_error(
                    f"Batch jobs have different arrival times: batch_id={bid} min_time={t0:.6g} max_time={t1:.6g}"
                )
        if len(types) > 1:
            add_error(f"Batch jobs have inconsistent arrival_type: batch_id={bid} arrival_types={sorted(types)}")

    is_valid = len(errors) == 0
    return {
        "is_valid": is_valid,
        "num_errors": len(errors),
        "num_warnings": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "errors_truncated": errors_truncated,
        "warnings_truncated": warnings_truncated,
    }


def load_events_jsonl(path: Path, *, sort_events: bool = True) -> List[Event]:

    adapter: TypeAdapter[Event] = TypeAdapter(Event)
    events: List[Event] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = adapter.validate_json(line)
            events.append(ev)
    if sort_events:
        # Ensure a canonical, deterministic ordering by (time, priority).
        events.sort(key=lambda e: (float(e.time), getattr(e, "priority", 100)))
    return events


def validate_instance(
    model: InputModel,
    events: List[Event],
    *,
    run_feasibility_projector: bool = True,
    run_strict_event_checks: bool = False,
    strict_max_messages: int = 50,
    strict_allow_unknown_jobs: bool = False,
) -> Dict[str, Any]:
    projections: List[str] = []
    if run_feasibility_projector:
        model_copy = model.model_copy(deep=True)
        projector = FeasibilityProjector(model_copy)
        _, projections = projector.check_and_project()

    validator = InstanceValidator(model, events)
    is_valid, base_errors, base_warnings = validator.validate()

    strict_summary: Optional[Dict[str, Any]] = None
    strict_errors: List[str] = []
    strict_warnings: List[str] = []
    if run_strict_event_checks:
        strict_summary = strict_validate_events(
            model,
            events,
            max_messages=strict_max_messages,
            allow_unknown_jobs=strict_allow_unknown_jobs,
        )
        if strict_summary is not None:
            if not strict_summary.get("is_valid", True):
                is_valid = False
            se = strict_summary.get("errors") or []
            sw = strict_summary.get("warnings") or []
            if isinstance(se, list):
                strict_errors = [e for e in se if isinstance(e, str)]
            if isinstance(sw, list):
                strict_warnings = [w for w in sw if isinstance(w, str)]

    errors: List[str] = list(base_errors)
    warnings: List[str] = list(base_warnings)
    errors.extend(strict_errors)
    warnings.extend(strict_warnings)

    return {
        "is_valid": is_valid,
        "num_errors": len(errors),
        "num_warnings": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "feasibility_projections": projections,
        "strict_event_checks": strict_summary,
    }
