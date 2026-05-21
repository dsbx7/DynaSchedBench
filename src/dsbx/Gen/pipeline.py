"""Generation pipeline helpers for dsbx."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Iterator
from loguru import logger
import numpy as np
import pandas as pd
import itertools
import urllib.request

from dsbx import __version__
from dsbx.Gen.io.dsl import load_input_model
from dsbx.Gen.io.export import Exporter
from dsbx.Gen.io.visualization import plot_instance_space
from dsbx.Gen.core.seed import SeedManager
from dsbx.Gen.core.feasibility import FeasibilityProjector
from dsbx.Gen.core.constructor import FastPathConstructor
from dsbx.Gen.core.metrics_engine import MetricsEngine
from dsbx.Gen.core.calibrator import Calibrator
from dsbx.Gen.core.moo_calibrator_v3 import MOOCalibratorV3, PYMOO_AVAILABLE
from dsbx.Gen.core.hybrid_calibrator import HybridCalibrator
from dsbx.Gen.core.range_advisor import RangeAdvisor
from dsbx.Gen.core.validator import InstanceValidator
from dsbx.Gen.models.inputs import InputModel
from dsbx.Gen.models.metrics import FinalReportData
from dsbx.Gen.models.events import (
    ArrivalEvent,
    DueDateEvent,
    PriorityChangeEvent,
    OrderCancellationEvent,
    ProcessTimeChangeEvent,
    RouteChangeEvent,
    DueDateChangeEvent,
    BreakdownEvent,
    PreventiveMaintenanceEvent,
    MachineRepairCompletionEvent,
)

def _expand_batch_parameters(model: InputModel) -> Iterator[InputModel]:
    """
    Expands a model with batchable fields (lists) into an iterator of single-instance models.
    It creates a Cartesian product of all list-based parameters.
    """
    param_grid = {}
    
    # Identify fields in `targets` that are lists and need expansion.
    for field_name, value in model.targets.model_dump().items():
        if isinstance(value, list) and field_name != 'rho_bottleneck':
            param_grid[field_name] = value

    if not param_grid:
        # If no lists are found, just yield the original model once.
        yield model
        return

    # Create all combinations of parameters (Cartesian product).
    keys, values = zip(*param_grid.items())
    param_combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]
    
    logger.info(f"Batch mode: Found {len(param_combinations)} parameter combinations to generate.")

    for i, combo in enumerate(param_combinations):
        # Create a deep copy of the model to modify for this specific instance.
        instance_model = model.model_copy(deep=True)
        # Apply the specific parameter combination.
        for key, val in combo.items():
            setattr(instance_model.targets, key, val)
        # Assign a unique, deterministic seed to each instance for reproducibility.
        instance_model.meta.seed = model.meta.seed + i
        yield instance_model

def _repair_due_dates(model: InputModel, events):
    """Repair due dates to avoid severe physical-constraint violations.

    For each job with both an arrival and a due-date event, enforce
    ``due_date >= arrival_time + total_process_time`` with a small safety margin.
    This removes hard errors such as due dates before arrival and slack shorter
    than total process time. The due date is not additionally clamped to the
    horizon; validators still warn about extremely distant due dates.
    """

    arrivals = {e.job_id: e for e in events if isinstance(e, ArrivalEvent)}
    fixes = 0

    for dd in [e for e in events if isinstance(e, DueDateEvent)]:
        arrival = arrivals.get(dd.job_id)
        if arrival is None:
            continue

        proc_times = getattr(arrival, "process_times", None) or []
        if not proc_times:
            continue

        total_proc = float(sum(proc_times))
        if total_proc <= 0.0:
            continue

        min_due = float(arrival.time + total_proc * 1.05)
        if dd.due_date < min_due:
            dd.due_date = min_due
            fixes += 1

    if fixes > 0:
        logger.debug(f"[DueDateRepair] Adjusted {fixes} due dates to enforce slack >= total_process_time")

    return events


def _ensure_due_date_set_for_all_arrivals(model: InputModel, events):
    ddt_raw = getattr(getattr(model, "targets", None), "ddt", 0.0)
    ddt = float(ddt_raw[0]) if isinstance(ddt_raw, list) and ddt_raw else float(ddt_raw)
    horizon = float(getattr(getattr(model, "scale", None), "horizon", 0.0) or 0.0)

    has_due: set[str] = set()
    for ev in events:
        if isinstance(ev, DueDateEvent):
            jid = getattr(ev, "job_id", None)
            if isinstance(jid, str) and jid:
                has_due.add(jid)

    added = 0
    for ev in list(events):
        if not isinstance(ev, ArrivalEvent):
            continue
        jid = getattr(ev, "job_id", None)
        if not isinstance(jid, str) or not jid:
            continue
        if jid in has_due:
            continue

        proc_times = getattr(ev, "process_times", None) or []
        work_content = float(sum(proc_times)) if isinstance(proc_times, list) else 0.0
        theoretical_slack = ddt * work_content
        max_possible_slack = horizon * 0.98 - float(ev.time)
        actual_slack = min(theoretical_slack, max(0.0, max_possible_slack))
        min_slack = work_content * 1.05
        if actual_slack < min_slack:
            actual_slack = min_slack
        due_date = float(ev.time + actual_slack)
        if horizon > 0.0 and due_date > horizon:
            due_date = horizon

        events.append(
            DueDateEvent(time=float(ev.time), job_id=jid, due_date=float(np.round(due_date, 4)))
        )
        has_due.add(jid)
        added += 1

    if added:
        events.sort(key=lambda e: e.time)
    return events


def _repair_due_date_change_semantics(model: InputModel, events):
    arrivals: Dict[str, ArrivalEvent] = {}
    for ev in events:
        if isinstance(ev, ArrivalEvent):
            jid = str(getattr(ev, "job_id", ""))
            if jid and jid not in arrivals:
                arrivals[jid] = ev

    if not arrivals:
        return events

    horizon = float(getattr(getattr(model, "scale", None), "horizon", 0.0) or 0.0)
    current_due: Dict[str, float] = {}
    to_remove: set[int] = set()
    eps = 1e-4

    def _sort_key(e):
        return (float(getattr(e, "time", 0.0)), int(getattr(e, "priority", 100)))

    events.sort(key=_sort_key)

    for ev in events:
        if isinstance(ev, DueDateEvent):
            jid = str(getattr(ev, "job_id", ""))
            if jid:
                current_due[jid] = float(getattr(ev, "due_date", 0.0))
            continue

        if not isinstance(ev, DueDateChangeEvent):
            continue

        jid = str(getattr(ev, "job_id", ""))
        if not jid:
            continue
        prev = current_due.get(jid)
        if prev is None:
            continue

        arr = arrivals.get(jid)
        if arr is None:
            continue

        proc_times = getattr(arr, "process_times", None) or []
        total_proc = float(sum(proc_times)) if isinstance(proc_times, list) else 0.0
        lb = float(arr.time) + total_proc

        t_ev = float(getattr(ev, "time", 0.0))

        new_due = float(getattr(ev, "new_due_date", 0.0))
        reason = getattr(ev, "reason", "")
        r = str(reason).lower() if isinstance(reason, str) else ""

        if r.find("urgent") >= 0:
            new_due = max(lb, min(new_due, prev))
        elif r.find("relax") >= 0:
            new_due = max(lb, max(new_due, prev))
        else:
            new_due = max(lb, new_due)

        min_due_by_time = t_ev + eps
        new_due = max(new_due, lb, min_due_by_time)

        # max(prev, lb, min_due_by_time)。
        if r.find("relax") >= 0 and new_due < prev - 1e-9:
            candidate = max(prev, lb, min_due_by_time)
            new_due = candidate

        if abs(new_due - prev) <= 1e-12:
            if r.find("urgent") >= 0:
                candidate = prev - eps
                if candidate >= lb + 1e-12:
                    new_due = candidate
                else:
                    to_remove.add(id(ev))
                    continue
            elif r.find("relax") >= 0:
                candidate = prev + eps
                new_due = candidate
            else:
                to_remove.add(id(ev))
                continue

        ev.new_due_date = float(new_due)
        current_due[jid] = float(new_due)

    if to_remove:
        events = [e for e in events if id(e) not in to_remove]

    events.sort(key=_sort_key)
    return events


def _normalize_batch_job_ids(events):
    """Normalize all batch job IDs so no bare parent ID remains in batches.

    The function only considers true batch arrivals with ``batch_id``. When a
    parent ID such as ``WIP-1`` or ``Job-3`` coexists with children like
    ``<parent>-B*``, the parent is renamed to ``<parent>-B1`` and existing
    children are shifted to keep a consistent sequence. Parents without batch
    children and already-normalized pure child sets are left unchanged. Only job
    ID strings are renamed; no events are added or removed.
    """

    batch_arrivals = [
        e
        for e in events
        if isinstance(e, ArrivalEvent) and getattr(e, "batch_id", None)
    ]
    if not batch_arrivals:
        return events

    def _split_parent_child(jid: str):
        if "-B" not in jid:
            return jid, None
        base, suffix = jid.rsplit("-B", 1)
        try:
            idx = int(suffix)
        except ValueError:
            return jid, None
        return base, idx

    children_by_parent = {}
    parents = set()

    for arr in batch_arrivals:
        jid = str(arr.job_id)
        base, idx = _split_parent_child(jid)
        if idx is None:
            parents.add(jid)
        else:
            children_by_parent.setdefault(base, []).append((idx, jid))

    rename_map = {}

    for parent_id in parents:
        children = children_by_parent.get(parent_id)
        if not children:
            continue

        parent_new = f"{parent_id}-B1"
        rename_map[parent_id] = parent_new

        for idx, old_child_id in sorted(children):
            new_child_id = f"{parent_id}-B{idx + 1}"
            if new_child_id != old_child_id:
                rename_map[old_child_id] = new_child_id

    if not rename_map:
        return events

    for ev in events:
        if not hasattr(ev, "job_id"):
            continue
        old = getattr(ev, "job_id")
        new = rename_map.get(str(old))
        if new is not None:
            setattr(ev, "job_id", new)

    events.sort(key=lambda e: e.time)
    return events


def _repair_dynamic_event_times(model: InputModel, events):
    """Ensure dynamic job-level events never occur before job arrival.

    Only timestamps of priority, cancellation, process-time, route, and due-date
    change events are adjusted. Arrival, due-date-set, breakdown, preventive
    maintenance, and repair-completion events are not modified. Because the
    metrics engine does not use these dynamic job-level events for target metric
    estimation, running this repair after calibration fixes event causality
    without changing calibrated metric values.
    """

    earliest_arrival_by_job: Dict[str, float] = {}
    for ev in events:
        if isinstance(ev, ArrivalEvent):
            jid = str(ev.job_id)
            t = float(ev.time)
            prev = earliest_arrival_by_job.get(jid)
            if prev is None or t < prev:
                earliest_arrival_by_job[jid] = t

    if not earliest_arrival_by_job:
        return events

    horizon = float(model.scale.horizon)
    eps = 1e-4

    dyn_types = (
        PriorityChangeEvent,
        OrderCancellationEvent,
        ProcessTimeChangeEvent,
        RouteChangeEvent,
        DueDateChangeEvent,
    )

    for ev in events:
        if isinstance(ev, dyn_types):
            jid = str(ev.job_id)
            t_arr = earliest_arrival_by_job.get(jid)
            if t_arr is None:
                continue
            if float(ev.time) < t_arr - 1e-9:
                new_t = min(horizon, t_arr + eps)
                ev.time = new_t

    latest_other_by_job: Dict[str, float] = {}
    cancellations_by_job: Dict[str, List[OrderCancellationEvent]] = {}
    for ev in events:
        if isinstance(ev, OrderCancellationEvent):
            jid = str(ev.job_id)
            cancellations_by_job.setdefault(jid, []).append(ev)
            continue
        if isinstance(
            ev,
            (
                PriorityChangeEvent,
                ProcessTimeChangeEvent,
                RouteChangeEvent,
                DueDateChangeEvent,
            ),
        ):
            jid = str(ev.job_id)
            t = float(ev.time)
            prev = latest_other_by_job.get(jid)
            if prev is None or t > prev:
                latest_other_by_job[jid] = t

    for jid, cancels in cancellations_by_job.items():
        if not cancels:
            continue
        t_last = latest_other_by_job.get(jid)
        if t_last is None:
            continue
        for cev in cancels:
            t_c = float(cev.time)
            if t_c < t_last + eps:
                cev.time = min(horizon, t_last + eps)

    events.sort(key=lambda e: e.time)
    return events


def _repair_downtime_overlaps(model: InputModel, events):
    horizon = float(model.scale.horizon)
    eps = 1e-4

    repairs_by_machine: Dict[str, List[MachineRepairCompletionEvent]] = {}
    for ev in events:
        if isinstance(ev, MachineRepairCompletionEvent):
            mid = str(getattr(ev, "machine_id", ""))
            if mid:
                repairs_by_machine.setdefault(mid, []).append(ev)
    for mid in repairs_by_machine:
        repairs_by_machine[mid].sort(key=lambda e: float(e.time))

    downtime_by_machine: Dict[str, List] = {}
    for ev in events:
        if isinstance(ev, (BreakdownEvent, PreventiveMaintenanceEvent)):
            mid = str(getattr(ev, "machine_id", ""))
            if mid:
                downtime_by_machine.setdefault(mid, []).append(ev)

    for mid, downs in downtime_by_machine.items():
        downs.sort(key=lambda e: float(e.time))

        reps = repairs_by_machine.get(mid, [])
        rep_used: set[int] = set()
        rep_for_breakdown: Dict[int, MachineRepairCompletionEvent] = {}

        if reps:
            for d_ev in downs:
                if not isinstance(d_ev, BreakdownEvent):
                    continue
                s0 = float(d_ev.time)
                dur0 = float(getattr(d_ev, "duration", 0.0) or 0.0)
                e0 = s0 + dur0
                for i, r_ev in enumerate(reps):
                    if i in rep_used:
                        continue
                    t_r = float(r_ev.time)
                    if s0 <= t_r < e0 - 1e-12:
                        rep_for_breakdown[id(d_ev)] = r_ev
                        rep_used.add(i)
                        d_ev.duration = max(0.0, t_r - s0)
                        break

        active_until = -1e18
        for d_ev in downs:
            s = float(d_ev.time)
            dur = float(getattr(d_ev, "duration", 0.0) or 0.0)

            old_end = s + dur
            if isinstance(d_ev, BreakdownEvent):
                r_ev = rep_for_breakdown.get(id(d_ev))
                if r_ev is not None:
                    old_end = float(r_ev.time)
                    if old_end < s:
                        old_end = s

            if s < active_until - 1e-12:
                new_s = active_until
                if new_s < horizon:
                    new_s = min(horizon, new_s + eps)
                d_ev.time = min(horizon, new_s)
                s = float(d_ev.time)

            if old_end > horizon:
                old_end = horizon

            if isinstance(d_ev, BreakdownEvent):
                r_ev = rep_for_breakdown.get(id(d_ev))
                if r_ev is not None:
                    if float(r_ev.time) < s:
                        r_ev.time = min(horizon, s)
                    old_end = min(old_end, float(r_ev.time))
                    d_ev.duration = max(0.0, old_end - s)
                    dur = float(d_ev.duration)
            else:
                d_ev.duration = max(0.0, old_end - s)
                dur = float(d_ev.duration)

            end = s + dur
            if end > horizon + 1e-12:
                d_ev.duration = max(0.0, horizon - s)
                dur = float(d_ev.duration)
                end = s + dur

            if end > active_until:
                active_until = end

    events.sort(key=lambda e: e.time)
    return events


def _log_tolerance_summary(model: InputModel, target_metrics_dict: Dict[str, float], final_metrics: Dict[str, Any]) -> None:
    base_tol = max(0.01, float(getattr(model.tolerance, "l2", 0.1)))
    t_scv_p = float(target_metrics_dict.get("scv_p", 0.0))
    if t_scv_p >= 1.5:
        scv_p_threshold = min(0.18, base_tol * 1.8)
    else:
        scv_p_threshold = min(0.12, base_tol * 1.2)
    per_metric_thresholds = {
        'rho_global': min(0.06, base_tol * 0.6),
        'scv_a': min(0.12, base_tol * 1.2),
        'scv_p': scv_p_threshold,
        'ddt': min(0.10, base_tol * 1.0),
        'disturbance': min(0.10, base_tol * 1.0),
        'load_cv': min(0.15, base_tol * 1.5),
    }

    best_observed_metrics = {k: final_metrics.get(k, 0.0) for k in target_metrics_dict}
    best_metric_rel_errors: Dict[str, float] = {}
    best_max_relative_error = 0.0
    best_worst_metric: Optional[str] = None
    best_all_metrics_ok = True
    eps = 1e-3

    target_vec = np.array(list(target_metrics_dict.values()))
    observed_vec = np.array(list(best_observed_metrics.values()))
    norm_factor = float(np.linalg.norm(target_vec)) or 1.0
    best_l2_for_summary = float(np.linalg.norm(target_vec - observed_vec)) / norm_factor

    for k, target_val in target_metrics_dict.items():
        observed_val = best_observed_metrics[k]
        if k != 'rho_bottleneck' and k in per_metric_thresholds:
            if target_val == 0.0:
                rel_error = abs(observed_val - target_val)
            else:
                rel_error = abs(observed_val - target_val) / abs(target_val)
            best_metric_rel_errors[k] = rel_error
            threshold = per_metric_thresholds[k]
            effective_threshold = threshold + eps
            if rel_error > effective_threshold:
                best_all_metrics_ok = False
                if rel_error > best_max_relative_error:
                    best_max_relative_error = rel_error
                    best_worst_metric = k

    logger.debug(f"Best-step relative errors for tolerance summary: {best_metric_rel_errors}")

    if best_l2_for_summary <= model.tolerance.l2 and best_all_metrics_ok:
        logger.info(
            f"[Tolerance] Best-so-far solution meets tolerance "
            f"(L2={best_l2_for_summary:.4f}, max_rel_err={best_max_relative_error:.4f})"
        )
    else:
        if best_worst_metric is not None:
            threshold = per_metric_thresholds[best_worst_metric]
            logger.warning(
                f"[Tolerance] Best-so-far solution does NOT meet tolerance "
                f"(L2={best_l2_for_summary:.4f}, max_rel_err={best_max_relative_error:.4f}, "
                f"worst_metric={best_worst_metric}, threshold={threshold:.4f})"
            )
        else:
            logger.warning(
                f"[Tolerance] Best-so-far solution does NOT meet tolerance "
                f"(L2={best_l2_for_summary:.4f})"
            )


def _build_metric_comparison_summary(
    current_metrics: Dict[str, Any],
    previous_metrics: Dict[str, Any],
    target_metrics: Dict[str, float],
) -> str:
    """Build a deterministic numeric comparison summary for logs and LLM prompts.

    Only metrics present in ``target_metrics`` and numeric in both current and
    previous results are compared.
    """

    lines: List[str] = []
    lines.append("Metric comparison between CURRENT run and PREVIOUS run:")
    for name, target in target_metrics.items():
        if name == "rho_bottleneck":
            continue

        cur_val = current_metrics.get(name)
        prev_val = previous_metrics.get(name)

        if not isinstance(cur_val, (int, float)) or not isinstance(prev_val, (int, float)):
            continue

        tgt_val = float(target)
        cur = float(cur_val)
        prev = float(prev_val)
        delta = cur - prev
        rel_prev = (delta / prev * 100.0) if prev != 0.0 else None
        rel_tgt = ((cur - tgt_val) / tgt_val * 100.0) if tgt_val != 0.0 else None

        rel_prev_str = f", vs previous: {rel_prev:+.2f}%" if rel_prev is not None else ""
        rel_tgt_str = f", vs target: {rel_tgt:+.2f}%" if rel_tgt is not None else ""

        lines.append(
            f"- {name}: previous={prev:.4f}, current={cur:.4f}, target={tgt_val:.4f}, "
            f"delta={delta:+.4f}{rel_prev_str}{rel_tgt_str}"
        )

    if len(lines) == 1:
        lines.append("(No numeric metrics could be compared between runs.)")

    return "\n".join(lines)


def _call_llm_for_comparison(prompt: str) -> Optional[str]:
    """Call an external LLM API to generate a natural-language comparison report.

    Environment variables configure the call: ``DYNASCHEDBENCH_LLM_API_KEY`` is
    required, while ``DYNASCHEDBENCH_LLM_ENDPOINT`` and
    ``DYNASCHEDBENCH_LLM_MODEL`` are optional. Failed calls or malformed
    responses are logged and return ``None``.
    """

    dummy_flag = os.getenv("DYNASCHEDBENCH_DUMMY_LLM", "").lower()
    if dummy_flag in {"1", "true", "yes"}:
        logger.info("Using dummy LLM backend for comparison report (no external API call).")
        return (
            "[DUMMY LLM] This comparison report was generated in test mode; no external service was called.\n\n"
            f"{prompt}"
        )

    api_key = os.getenv("DYNASCHEDBENCH_LLM_API_KEY")
    if not api_key:
        logger.info("DYNASCHEDBENCH_LLM_API_KEY not set; skipping LLM-based comparison report.")
        return None

    endpoint = os.getenv("DYNASCHEDBENCH_LLM_ENDPOINT", "https://api.openai.com/v1/chat/completions")
    model = os.getenv("DYNASCHEDBENCH_LLM_MODEL", "gpt-4o-mini")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert in dynamic job shop scheduling benchmark analysis. "
                    "Summarize metric differences between two runs and explain whether the NEW run "
                    "is better or worse than the PREVIOUS run. Always answer in English."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.3,
        "max_tokens": 600,
    }

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    request = urllib.request.Request(endpoint, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
        result = json.loads(raw)
    except Exception as exc:
        logger.error(f"LLM comparison request failed: {exc}")
        return None

    try:
        choices = result.get("choices") or []
        if not choices:
            return None
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
    except Exception as exc:
        logger.error(f"Failed to parse LLM comparison response: {exc}")
        return None

    return None


def _generate_comparison_report_with_llm(
    current_metrics: Dict[str, Any],
    previous_metrics: Dict[str, Any],
    target_metrics: Dict[str, float],
) -> str:
    """Generate the final comparison report from numeric and optional LLM output.

    The deterministic numeric summary is always included. If an LLM backend is
    configured and succeeds, an ``[LLM Analysis]`` section is appended.
    """

    numeric_summary = _build_metric_comparison_summary(
        current_metrics=current_metrics,
        previous_metrics=previous_metrics,
        target_metrics=target_metrics,
    )

    prompt = (
        "Below is a metric comparison between a new generation experiment (CURRENT) and a previous experiment (PREVIOUS). "\
        "Act as a dynamic job shop scheduling benchmark expert and "\
        "summarize concisely in English:\n"\
        "1. How key metrics changed relative to the previous run (better, worse, or almost unchanged);\n"\
        "2. Whether closeness to targets improved overall and whether clear trade-offs exist;\n"\
        "3. Provide 2-5 recommendations for follow-up tuning or analysis.\n\n"\
        "Focus on rho_global, scv_a, scv_p, ddt, disturbance, and load_cv.\n"\
        "Here is the numeric comparison:\n\n"\
        f"{numeric_summary}\n\n"\
        "Use 3-6 bullet points or short paragraphs and do not copy the table numbers verbatim."
    )

    llm_text = _call_llm_for_comparison(prompt)
    if llm_text:
        return numeric_summary + "\n\n[LLM Analysis]\n" + llm_text

    return numeric_summary


def run_generation_pipeline(
    model: InputModel,
    output_path: Path,
    max_calib_steps: int,
    compare_metrics_paths: Optional[List[Path]] = None,
    use_moo: bool = False,
    use_hybrid: bool = False,
    moo_population_size: int = 60,
    moo_n_generations: int = 40,
    hybrid_population_size: int = 80,
    hybrid_n_generations: int = 100,
    hybrid_convergence_window: int = 10,
    hybrid_convergence_tol: float = 0.0005,
    hybrid_max_sequential_steps: int = 7,
    # Sequential-mode early stopping hyperparameters
    seq_early_stop_no_improve_steps: int = 3,
    seq_early_stop_relax_factor: float = 2.0,
    seq_min_relative_improvement: float = 0.005,
    # Sequential-mode per-metric tolerance overrides (relative errors)
    seq_tol_rho_global: Optional[float] = None,
    seq_tol_scv_a: Optional[float] = None,
    seq_tol_scv_p: Optional[float] = None,
    seq_tol_ddt: Optional[float] = None,
    seq_tol_disturbance: Optional[float] = None,
    seq_tol_load_cv: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """
    Encapsulates the full pipeline for generating a SINGLE instance.
    This function is called by both `gen` and `gen-batch`.
    Returns the final metrics dictionary on success, or None on failure.
    
    Args:
        model: Input configuration model
        output_path: Where to save results
        max_calib_steps: Maximum calibration iterations (for sequential mode)
        compare_metrics_paths: Optional pair of final_metrics.json file paths
            for comparison (BASELINE, CANDIDATE)
        use_moo: If True, use Multi-Objective Optimization calibrator (NSGA-II) v3
        use_hybrid: If True, use Hybrid calibrator (Sequential + MOO for coupled metrics)
    """
    logger.info(
        f"Starting generation pipeline: mode={model.evaluation.mode}, "
        f"seed={getattr(model.meta, 'seed', None)}, "
        f"max_calib_steps={max_calib_steps}, use_moo={use_moo}, use_hybrid={use_hybrid}"
    )
    logger.debug(
        "Scale summary: "
        f"horizon={float(model.scale.horizon):.3f}, "
        f"jobs_total={getattr(model.scale, 'jobs_total', None)}, "
        f"num_machines={getattr(model.scale, 'num_machines', None)}, "
        f"num_job_families={getattr(model.scale, 'num_job_families', None)}"
    )
    logger.debug(
        "Target metrics (raw): "
        f"rho_global={model.targets.rho_global}, "
        f"scv_a={model.targets.scv_a}, "
        f"scv_p={model.targets.scv_p}, "
        f"ddt={model.targets.ddt}, "
        f"disturbance={model.targets.disturbance}, "
        f"load_cv={getattr(model.targets, 'load_cv', None)}, "
        f"rho_bottleneck={model.targets.rho_bottleneck}"
    )

    exporter = Exporter(output_path)
    # The input model might have been modified (e.g., with a new seed), so we dump the current state.
    input_str = model.model_dump_json()

    # Stage 1 removed: RangeAdvisor is now a standalone CLI tool, not auto-invoked here.

    projector = FeasibilityProjector(model)
    model, projections = projector.check_and_project()
    if projections:
        logger.debug(
            "Feasibility projector applied %d projections. First few: %s",
            len(projections),
            projections[:5],
        )
    else:
        logger.debug("Feasibility projector made no changes to the input model.")

    # --- Stage 2: Generation and Calibration ---
    seed_manager = SeedManager(model.meta.seed)
    constructor = FastPathConstructor(model, seed_manager)
    events = constructor.generate_events()

    # Summarize generated events for debugging
    event_counts: Dict[str, int] = {}
    for ev in events:
        etype = getattr(ev, "event_type", type(ev).__name__)
        event_counts[etype] = event_counts.get(etype, 0) + 1
    if events:
        times = [float(getattr(ev, "time", 0.0)) for ev in events]
        logger.debug(
            "Generation summary: total_events=%d, min_time=%.3f, max_time=%.3f, by_type=%s",
            len(events),
            min(times),
            max(times),
            event_counts,
        )
    else:
        logger.debug("Generation summary: constructor produced 0 events.")

    def _as_float(v: Any) -> float:
        return float(v[0]) if isinstance(v, list) and v else float(v)

    target_metrics_dict = {
        "rho_global": _as_float(model.targets.rho_global),
        # For bottleneck, the MetricsEngine returns an L2 error norm; target is 0.0
        "rho_bottleneck": 0.0,
        "ddt": _as_float(model.targets.ddt),
        "scv_a": _as_float(model.targets.scv_a),
        "scv_p": _as_float(model.targets.scv_p),
        "disturbance": _as_float(model.targets.disturbance),
    }
    
    # Add load_cv to targets if it's specified (not None)
    if model.targets.load_cv is not None:
        target_metrics_dict["load_cv"] = float(model.targets.load_cv)
    final_metrics = {}
    pareto_info = {}  # Will store MOO information if used
    
    # --- Choose calibration mode: Hybrid, MOO, or Sequential ---
    if use_hybrid:
        if not PYMOO_AVAILABLE:
            logger.error("Hybrid mode requested but pymoo not available. Please install: pip install pymoo")
            logger.info("Falling back to sequential calibration...")
            use_hybrid = False
        else:
            logger.info("Using HYBRID calibrator (4D MOO with convergence detection)")
            logger.info("   Search space: scv_a, scv_p, ddt, rho_bottleneck [0.5-1.6] scale factors")
            logger.info(
                f"   Population: {hybrid_population_size}, Max generations: {hybrid_n_generations} "
                "(stops early on convergence)"
            )
            logger.info(
                "   Termination: Total error improvement < "
                f"{hybrid_convergence_tol*100:.3f}% over {hybrid_convergence_window} generations"
            )
            logger.info("   Selection: Balanced solution (minimize worst-case metric error)")
            hybrid_calibrator = HybridCalibrator(
                model=model,
                target_metrics=target_metrics_dict,
                population_size=hybrid_population_size,
                n_generations=hybrid_n_generations,
                convergence_window=hybrid_convergence_window,
                convergence_tol=hybrid_convergence_tol,
                max_sequential_steps=hybrid_max_sequential_steps,
            )
            events, pareto_info = hybrid_calibrator.calibrate()
            
            # Re-sort and clamp after calibration
            events.sort(key=lambda e: e.time)
            horizon = float(model.scale.horizon)
            for event in events:
                if event.time > horizon:
                    event.time = horizon
                if hasattr(event, 'due_date') and event.due_date > horizon:
                    event.due_date = horizon
            
            # Calculate final metrics
            metrics_engine = MetricsEngine(model, events)
            final_metrics = metrics_engine.estimate()
            
            logger.info("Hybrid calibration complete")
            logger.info("Final metrics:")
            for k in target_metrics_dict:
                target_val = target_metrics_dict[k]
                observed_val = final_metrics.get(k, 0.0)
                error = abs(observed_val - target_val) / (target_val + 1e-6) * 100
                logger.info(f"  - {k}: Target={target_val:.3f}, Observed={observed_val:.3f} (error={error:.2f}%)")
            _log_tolerance_summary(model, target_metrics_dict, final_metrics)
    
    elif use_moo:
        if not PYMOO_AVAILABLE:
            logger.error("MOO mode requested but pymoo not available. Please install: pip install pymoo")
            logger.info("Falling back to sequential calibration...")
            use_moo = False
        else:
            logger.info("Using Multi-Objective Optimization (MOO) v3 calibrator (EXTENDED 10 parameters)")
            logger.info(f"   Population: {moo_population_size}, Max generations: {moo_n_generations}")
            moo_calibrator = MOOCalibratorV3(
                model=model,
                target_metrics=target_metrics_dict,
                population_size=moo_population_size,
                n_generations=moo_n_generations,
            )
            events, pareto_info = moo_calibrator.calibrate()
            
            # Re-sort and clamp after MOO
            events.sort(key=lambda e: e.time)
            horizon = float(model.scale.horizon)
            for event in events:
                if event.time > horizon:
                    event.time = horizon
                if hasattr(event, 'due_date') and event.due_date > horizon:
                    event.due_date = horizon
            
            # Calculate final metrics
            metrics_engine = MetricsEngine(model, events)
            final_metrics = metrics_engine.estimate()
            
            logger.info("MOO calibration complete")
            logger.info("Final metrics:")
            for k in target_metrics_dict:
                target_val = target_metrics_dict[k]
                observed_val = final_metrics.get(k, 0.0)
                error = abs(observed_val - target_val) / (target_val + 1e-6) * 100
                logger.info(f"  - {k}: Target={target_val:.3f}, Observed={observed_val:.3f} (error={error:.2f}%)")
            _log_tolerance_summary(model, target_metrics_dict, final_metrics)
    
    if not use_moo and not use_hybrid:
        # Use sequential calibration (original approach)
        # Early stopping variables
        prev_l2_error = float('inf')
        no_improvement_count = 0
        # Best-so-far tracking (by L2 first, then worst per-metric relative error)
        best_l2_error = float('inf')
        best_max_rel_error = float('inf')
        best_events = events
        best_final_metrics: Dict[str, Any] | None = None
        best_step = -1
        reached_max_steps = False

        best_feasible_l2 = float("inf")
        best_feasible_max_rel_error = float("inf")
        best_feasible_events = None
        best_feasible_final_metrics: Dict[str, Any] | None = None
        best_feasible_step = -1

        logger.debug("Sequential calibration target metrics (normalized): %s", target_metrics_dict)

        for step in range(max_calib_steps + 1):
            logger.info(f"--- Starting Generation/Calibration Step {step} ---")
            metrics_engine = MetricsEngine(model, events)
            final_metrics = metrics_engine.estimate()

            observed_metrics_dict = {k: final_metrics.get(k, 0.0) for k in target_metrics_dict}
            logger.debug(f"Step {step} observed metrics: {observed_metrics_dict}")
            
            target_vec = np.array(list(target_metrics_dict.values()))
            observed_vec = np.array(list(observed_metrics_dict.values()))
            norm_factor = float(np.linalg.norm(target_vec))
            if norm_factor == 0.0:
                norm_factor = 1.0
            l2_error = float(np.linalg.norm(target_vec - observed_vec)) / norm_factor
            
            logger.info(f"Step {step} | Overall L2 Error: {l2_error:.4f}")
            
            # Check per-metric errors with individual thresholds
            base_tol = max(0.01, float(getattr(model.tolerance, "l2", 0.1)))
            t_scv_p = float(target_metrics_dict.get("scv_p", 0.0))
            if t_scv_p >= 1.5:
                scv_p_threshold = min(0.18, base_tol * 1.8)
            else:
                scv_p_threshold = min(0.12, base_tol * 1.2)
            per_metric_thresholds = {
                'rho_global': min(0.06, base_tol * 0.6),
                'scv_a': min(0.12, base_tol * 1.2), 
                'scv_p': scv_p_threshold,
                'ddt': min(0.10, base_tol * 1.0),
                'disturbance': min(0.10, base_tol * 1.0),
                'load_cv': min(0.15, base_tol * 1.5),  # 10% tolerance for load coefficient of variation
            }

            # Allow explicit CLI overrides for per-metric thresholds (relative errors)
            if seq_tol_rho_global is not None:
                per_metric_thresholds['rho_global'] = float(seq_tol_rho_global)
            if seq_tol_scv_a is not None:
                per_metric_thresholds['scv_a'] = float(seq_tol_scv_a)
            if seq_tol_scv_p is not None:
                per_metric_thresholds['scv_p'] = float(seq_tol_scv_p)
            if seq_tol_ddt is not None:
                per_metric_thresholds['ddt'] = float(seq_tol_ddt)
            if seq_tol_disturbance is not None:
                per_metric_thresholds['disturbance'] = float(seq_tol_disturbance)
            if seq_tol_load_cv is not None:
                per_metric_thresholds['load_cv'] = float(seq_tol_load_cv)
            
            max_relative_error = 0.0
            worst_metric = None
            all_metrics_ok = True
            metric_rel_errors: Dict[str, float] = {}
            eps = 1e-3

            for k in target_metrics_dict:
                target_val = target_metrics_dict[k]
                observed_val = observed_metrics_dict[k]
                logger.info(f"  - {k}: Target={target_val:.3f}, Observed={observed_val:.3f}")
                
                # Calculate relative error for non-bottleneck metrics
                if k != 'rho_bottleneck' and k in per_metric_thresholds:
                    if target_val == 0.0:
                        rel_error = abs(observed_val - target_val)
                    else:
                        rel_error = abs(observed_val - target_val) / abs(target_val)
                    
                    metric_rel_errors[k] = rel_error
                    threshold = per_metric_thresholds[k]
                    effective_threshold = threshold + eps
                    if rel_error > effective_threshold:
                        all_metrics_ok = False
                        if rel_error > max_relative_error:
                            max_relative_error = rel_error
                            worst_metric = k

            logger.debug(f"Step {step} relative errors: {metric_rel_errors}")

            if all_metrics_ok:
                if l2_error < best_feasible_l2 - 1e-9:
                    best_feasible_l2 = l2_error
                    best_feasible_max_rel_error = 0.0
                    best_feasible_events = events
                    best_feasible_final_metrics = final_metrics
                    best_feasible_step = step

            # Update best-so-far solution
            improved = False
            if l2_error < best_l2_error - 1e-9:
                improved = True
            elif abs(l2_error - best_l2_error) <= 1e-9 and max_relative_error < best_max_rel_error - 1e-9:
                improved = True
            if improved:
                best_l2_error = l2_error
                best_max_rel_error = max_relative_error
                best_events = events
                best_final_metrics = final_metrics
                best_step = step

            # Early stopping: check if error is not improving
            if step > 0:
                min_improve = max(seq_min_relative_improvement, 0.0)
                if l2_error >= prev_l2_error * (1.0 - min_improve):
                    no_improvement_count += 1
                else:
                    no_improvement_count = 0
            
            prev_l2_error = l2_error
            
            EARLY_STOP_NO_IMPROVEMENT_STEPS = max(1, int(seq_early_stop_no_improve_steps))
            EARLY_STOP_RELAX_FACTOR = max(1.0, float(seq_early_stop_relax_factor))
            if no_improvement_count >= EARLY_STOP_NO_IMPROVEMENT_STEPS:
                can_early_stop = True
                # If some metrics are still outside their strict thresholds, require them
                # to be within a relaxed band before allowing early stopping.
                if not all_metrics_ok and worst_metric and worst_metric in per_metric_thresholds:
                    relaxed_threshold = per_metric_thresholds[worst_metric] * EARLY_STOP_RELAX_FACTOR
                    if max_relative_error > relaxed_threshold:
                        can_early_stop = False
                        logger.info(
                            f"Early stopping condition met but {worst_metric} still has "
                            f"{max_relative_error*100:.2f}% error (relaxed threshold={relaxed_threshold*100:.1f}%). "
                            "Continuing calibration."
                        )
                if can_early_stop:
                    logger.warning(
                        f"Early stopping: no improvement for {no_improvement_count} steps "
                        f"(L2={l2_error:.4f}, max_rel_err={max_relative_error:.4f})"
                    )
                    logger.info(f"Final state: L2={l2_error:.4f}, max_rel_err={max_relative_error:.4f}")
                    break
            
            # Check convergence: both L2 and per-metric conditions must be met
            if l2_error <= model.tolerance.l2 and all_metrics_ok:
                logger.info(f"All metrics converged (L2={l2_error:.4f}, max_rel_err={max_relative_error:.4f})")
                best_l2_error = l2_error
                best_max_rel_error = max_relative_error
                best_events = events
                best_final_metrics = final_metrics
                best_step = step
                break
            elif l2_error <= model.tolerance.l2 and not all_metrics_ok:
                if worst_metric:
                    logger.warning(f"L2 converged but {worst_metric} has {max_relative_error*100:.2f}% error (threshold {per_metric_thresholds[worst_metric]*100:.1f}%)")
                logger.info(f"Continuing calibration to improve individual metrics...")
            if step == max_calib_steps:
                reached_max_steps = True
                logger.info(f"Reached maximum calibration steps ({max_calib_steps}); exiting calibration loop and using best-so-far result.")
                break

            calibrator = Calibrator(model, events, target_metrics_dict, observed_metrics_dict)
            events = calibrator.calibrate()
            
            # Re-sort events after calibration to maintain time ordering
            events.sort(key=lambda e: e.time)
    
        if best_feasible_final_metrics is not None:
            best_l2_error = best_feasible_l2
            best_max_rel_error = best_feasible_max_rel_error
            best_events = best_feasible_events
            best_final_metrics = best_feasible_final_metrics
            best_step = best_feasible_step

        # After exiting the loop (for any reason), fall back to best-so-far result
        if best_final_metrics is not None:
            if best_step >= 0:
                logger.info(
                    f"[BestResult] Using best calibration step {best_step} "
                    f"(L2={best_l2_error:.4f}, max_rel_err={best_max_rel_error:.4f})"
                )
            events = best_events
            final_metrics = best_final_metrics

            _log_tolerance_summary(model, target_metrics_dict, final_metrics)

    # --- Repair dynamic event times to preserve basic causality ---
    # Ensure dynamic job-level events (cancellations, priority changes,
    # process-time changes, route changes, due-date changes) do not occur
    # before their corresponding job arrives. This does not affect metrics
    # used for calibration, as MetricsEngine currently ignores these events.
    events = _repair_dynamic_event_times(model, events)

    events = _repair_downtime_overlaps(model, events)

    # --- Clamp all event times to horizon for ALL calibration modes ---
    # This ensures no events exceed the time horizon regardless of calibration mode
    horizon = float(model.scale.horizon)
    clamped_count = 0
    event_clamp_details = []
    
    for event in events:
        if event.time > horizon:
            if clamped_count < 5:
                event_clamp_details.append(f"{event.event_type} at {event.time:.2f}")
            event.time = horizon
            clamped_count += 1
        # Also clamp due dates
        if hasattr(event, 'due_date') and event.due_date > horizon:
            event.due_date = horizon
            clamped_count += 1
    
    if clamped_count > 0:
        clamp_ratio = clamped_count / len(events) if events else 0.0
        
        if clamp_ratio > 0.01:
            logger.warning(f"Clamped {clamped_count} events/attributes ({clamp_ratio*100:.1f}%) to horizon {horizon}")
            if event_clamp_details:
                logger.debug(f"First clamped events: {', '.join(event_clamp_details)}")
        else:
            logger.info(f"Clamped {clamped_count} events/attributes to horizon {horizon} (minor adjustment)")
    
    # --- Apply batch arrivals AFTER calibration to preserve batch consistency ---
    if model.dynamic_scenarios.batch_arrival_probability > 0:
        arrival_events = [e for e in events if e.event_type == "ARRIVAL"]
        expanded_arrivals = constructor._expand_batch_arrivals(arrival_events)
        # Replace arrival events with expanded ones
        non_arrival_events = [e for e in events if e.event_type != "ARRIVAL"]
        events = expanded_arrivals + non_arrival_events
        events.sort(key=lambda e: e.time)
        logger.info(f"Applied batch arrivals post-calibration: {len(events)} total events")

        try:
            non_wip_ids = set()
            for ev in events:
                if isinstance(ev, ArrivalEvent):
                    atype = getattr(ev, "arrival_type", None)
                    if atype == "initial_wip":
                        continue
                    non_wip_ids.add(str(getattr(ev, "job_id", "")))
            if non_wip_ids and hasattr(model, "scale") and hasattr(model.scale, "jobs_total"):
                model.scale.jobs_total = int(len(non_wip_ids))
        except Exception:
            pass

    # --- Normalize all batch job_ids so no bare parent remains for batches ---
    events = _normalize_batch_job_ids(events)

    events = _ensure_due_date_set_for_all_arrivals(model, events)

    events = _repair_due_dates(model, events)

    events = _repair_due_date_change_semantics(model, events)


    # --- Stage 2.5: Validate Generated Instance ---
    logger.info("Validating generated instance...")
    validator = InstanceValidator(model, events)
    is_valid, validation_errors, validation_warnings = validator.validate()
    
    if not is_valid:
        logger.error(f"Instance validation failed with {len(validation_errors)} errors!")
        logger.error("Please check the input configuration and try again.")
        # Don't fail completely, but log the errors
        # Users can choose to use the instance at their own risk
    
    # --- Stage 3: Comparison and Reporting ---
    # comparison_text = None
    # if compare_to_path:
    #     logger.info(f"--- Comparing to previous run in '{compare_to_path}' ---")
    #     previous_metrics_path = compare_to_path / "final_metrics.json"
    #     if previous_metrics_path.exists():
    #         with open(previous_metrics_path, 'r') as f:
    #             previous_metrics = json.load(f)
    #         comparison_text = generate_comparison_report(final_metrics, previous_metrics)
    #         logger.info("\n--- Comparison Analysis ---\n" + comparison_text)
    #     else:
    #         logger.warning(f"Could not find 'final_metrics.json' in '{compare_to_path}'. Skipping comparison.")

    comparison_text: Optional[str] = None
    if compare_metrics_paths:
        try:
            if len(compare_metrics_paths) != 2:
                logger.warning(
                    f"--compare-to expects exactly 2 final_metrics.json paths, got {len(compare_metrics_paths)}; skipping comparison."
                )
            else:
                baseline_path, candidate_path = compare_metrics_paths
                logger.info(
                    "--- Comparing metrics files ---\n"
                    f"  BASELINE: {baseline_path}\n"
                    f"  CANDIDATE: {candidate_path}"
                )

                missing = [p for p in (baseline_path, candidate_path) if not p.exists()]
                if missing:
                    logger.warning(
                        "One or both comparison files do not exist; skipping comparison: "
                        + ", ".join(str(p) for p in missing)
                    )
                else:
                    with open(baseline_path, "r") as f:
                        baseline_metrics = json.load(f)
                    with open(candidate_path, "r") as f:
                        candidate_metrics = json.load(f)

                    comparison_text = _generate_comparison_report_with_llm(
                        current_metrics=candidate_metrics,
                        previous_metrics=baseline_metrics,
                        target_metrics=target_metrics_dict,
                    )
                    logger.info("\n--- Comparison Analysis ---\n" + comparison_text)
        except Exception as exc:
            logger.error(f"Comparison between metrics files failed: {exc}")

    # --- Stage 4: Export Artifacts ---
    input_hash = exporter.write_meta(input_str, __version__, seed_map=seed_manager.get_seed_map())
    errors = {k: abs(final_metrics.get(k, 0) - v) / v if v != 0 else 0 for k, v in target_metrics_dict.items()}
    logger.debug(f"Final metrics before export: {final_metrics}")
    logger.debug(f"Relative errors vs targets: {errors}")

    input_model_path = output_path / "input_model.json"
    with open(input_model_path, "w", encoding="utf-8") as f:
        f.write(model.model_dump_json(indent=2, ensure_ascii=False))

    # Build static job info from final events and write to static_jobs.json
    static_jobs: Dict[str, Any] = {"jobs": {}}
    for ev in events:
        if isinstance(ev, ArrivalEvent):
            jid = str(ev.job_id)
            info = static_jobs["jobs"].setdefault(jid, {})
            info.setdefault("job_family", ev.job_family)
            info.setdefault("routing", list(ev.routing))
            info.setdefault("process_times", list(ev.process_times))
            info.setdefault("arrival_type", getattr(ev, "arrival_type", "planned"))
            if "due_date" not in info:
                info["due_date"] = None
    for ev in events:
        if isinstance(ev, DueDateEvent):
            jid = str(ev.job_id)
            info = static_jobs["jobs"].setdefault(jid, {
                "job_family": None,
                "routing": [],
                "process_times": [],
                "due_date": None,
            })
            info["due_date"] = float(ev.due_date)

    exporter.write_static_jobs(static_jobs)
    exporter.write_static_machines(model.plant.machines)
    exporter.write_events(events)
    exporter.write_final_metrics(final_metrics)
    # Ensure a trace artifact exists as tests expect it
    exporter.write_trace(pd.DataFrame({"time": [0.0]}))

    report_data = FinalReportData(  # type: ignore[call-arg]
        input_hash=input_hash, version=__version__, seed_map=seed_manager.get_seed_map(),
        target_metrics=target_metrics_dict,
        observed_metrics={k: final_metrics.get(k, 0.0) for k in target_metrics_dict},
        errors=errors, projections=projections,
        ssi=final_metrics.get("SSI", {}),
        ssi_norm=final_metrics.get("SSI_norm", {}),
        difficulty_score=float(final_metrics.get("difficulty_score", 0.0)),
        difficulty_category=str(final_metrics.get("difficulty_category", "medium")),
        comparison_report=comparison_text,
        # comparison_report=comparison_text,
    )
    exporter.write_report(report_data)
    
    # Write Pareto info if MOO was used
    if pareto_info:
        pareto_path = output_path / "pareto_info.json"
        with open(pareto_path, 'w') as f:
            json.dump(pareto_info, f, indent=2)
        logger.info(f"Pareto front information saved to {pareto_path}")
    
    logger.info(f"Successfully generated instance in {output_path}")
    # Also print a concise success message to stdout for CLI tests
    print("Successfully generated instance")
    return final_metrics
