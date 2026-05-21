from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import json
import matplotlib.pyplot as plt
import numpy as np

from dsbx.Eval import Trajectory
from dsbx.Eval.Metrics import (
    evaluate_trajectory,
    METRIC_STATIC_KEYS,
    METRIC_DYNAMIC_KEYS,
)


SUPPORTED_METRIC_OVER_TIME: List[str] = [
    "wip",
    "wip_waiting",
    "wip_processing",
    "utilization_global",
    "utilization_max_machine",
    "utilization_min_machine",
    "utilization_cv_machine",
    "utilization_group_global",
    "queue_length_total",
    "queue_length_max_machine",
    "queue_length_avg_machine",
    "jobs_completed",
    "jobs_total",
    "jobs_arrived",
    "jobs_not_arrived",
    "jobs_cancelled",
    "stability_changed_ops_ratio",
    "stability_avg_start_time_shift",
    "stability_max_start_time_shift",
    "reschedules_cumulative",
]


def _extract_metric_over_time(
    traj: Trajectory,
    metric: str,
    start_time: float = 0.0,
) -> Tuple[List[float], List[float]]:
    """Helper to derive a simple time series from a trajectory.

    Currently supports a small set of built-in metrics; this can be
    extended later as needed.
    """

    times: List[float] = []
    values: List[float] = []

    completed_counts: int = 0

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
            if metric == "wip":
                v = float(rec.get("wip_waiting", 0.0)) + float(rec.get("wip_processing", 0.0))
            elif metric == "wip_waiting":
                v = float(rec.get("wip_waiting", 0.0))
            elif metric == "wip_processing":
                v = float(rec.get("wip_processing", 0.0))
            elif metric == "queue_length_total":
                v = float(rec.get("queue_total", 0.0))
            elif metric == "jobs_completed":
                v = float(rec.get("num_jobs_completed", 0.0))
            elif metric == "jobs_total":
                v = float(rec.get("num_jobs_total", 0.0))
            elif metric == "jobs_cancelled":
                v = float(rec.get("num_jobs_cancelled", 0.0))
            elif metric == "stability_changed_ops_ratio":
                v = float(rec.get("changed_ops_ratio", 0.0))
            elif metric == "stability_avg_start_time_shift":
                v = float(rec.get("avg_start_time_shift", 0.0))
            elif metric == "stability_max_start_time_shift":
                v = float(rec.get("max_start_time_shift", 0.0))
            elif metric == "reschedules_cumulative":
                has_decision = bool(rec.get("has_decision", False))
                action_info = rec.get("action")
                v = 1.0 if (has_decision or action_info) else 0.0
                if values:
                    v += values[-1]
            else:
                raise ValueError(
                    f"Metric '{metric}' requires full snapshots; summary JSONL lacks necessary details"
                )
            times.append(t)
            values.append(float(v))
        return times, values

    for step in traj.steps:
        t = float(step.time)
        if t < float(start_time):
            continue
        snap = step.snapshot
        if metric == "wip":
            v = sum(1 for j in snap.jobs if j.status in ("waiting", "processing"))
        elif metric == "wip_waiting":
            v = sum(1 for j in snap.jobs if j.status == "waiting")
        elif metric == "wip_processing":
            v = sum(1 for j in snap.jobs if j.status == "processing")
        elif metric == "utilization_global":
            utils = list(snap.system_stats.utilization_by_machine.values())
            v = float(sum(utils) / len(utils)) if utils else 0.0
        elif metric == "utilization_max_machine":
            utils = list(snap.system_stats.utilization_by_machine.values())
            v = float(max(utils)) if utils else 0.0
        elif metric == "utilization_min_machine":
            utils = list(snap.system_stats.utilization_by_machine.values())
            v = float(min(utils)) if utils else 0.0
        elif metric == "utilization_cv_machine":
            utils = list(snap.system_stats.utilization_by_machine.values())
            if utils:
                mean_u = float(sum(utils) / len(utils))
                if mean_u > 0.0 and len(utils) >= 2:
                    var = float(sum((float(u) - mean_u) ** 2 for u in utils) / len(utils))
                    std = var ** 0.5
                    v = std / mean_u
                else:
                    v = 0.0
            else:
                v = 0.0
        elif metric == "utilization_group_global":
            ug = list(snap.system_stats.utilization_by_group.values())
            v = float(sum(ug) / len(ug)) if ug else 0.0
        elif metric == "queue_length_total":
            v = sum(len(m.queue) for m in snap.machines)
        elif metric == "queue_length_max_machine":
            lengths = [len(m.queue) for m in snap.machines]
            v = float(max(lengths)) if lengths else 0.0
        elif metric == "queue_length_avg_machine":
            lengths = [len(m.queue) for m in snap.machines]
            v = float(sum(lengths) / len(lengths)) if lengths else 0.0
        elif metric == "jobs_completed":
            completed_counts = sum(1 for j in snap.jobs if j.status == "completed")
            v = float(completed_counts)
        elif metric == "jobs_total":
            v = float(len(snap.jobs))
        elif metric == "jobs_arrived":
            v = float(sum(1 for j in snap.jobs if j.status != "not_arrived"))
        elif metric == "jobs_not_arrived":
            v = float(sum(1 for j in snap.jobs if j.status == "not_arrived"))
        elif metric == "jobs_cancelled":
            v = float(sum(1 for j in snap.jobs if j.status == "cancelled"))
        elif metric == "stability_changed_ops_ratio":
            v = float(snap.stability_stats.changed_ops_ratio)
        elif metric == "stability_avg_start_time_shift":
            v = float(snap.stability_stats.avg_start_time_shift)
        elif metric == "stability_max_start_time_shift":
            v = float(snap.stability_stats.max_start_time_shift)
        elif metric == "reschedules_cumulative":
            v = float(snap.system_stats.num_reschedules)
        else:
            raise ValueError(f"Unsupported metric-over-time: {metric}")
        times.append(t)
        values.append(float(v))

    return times, values


def plot_metric_over_time(
    traj: Trajectory,
    metric: str,
    *,
    out_path: Optional[Path] = None,
    figsize: Tuple[float, float] = (8.0, 4.0),
    dpi: int = 150,
    start_time: float = 0.0,
):
    """Plot a metric curve as a function of time based on a trajectory.

    Supported `metric` values include:
    - "wip": work-in-process count
    - "utilization_global": average machine utilization
    - "queue_length_total": total queue length across all machines
    - "jobs_completed": cumulative number of completed jobs
    """

    times, values = _extract_metric_over_time(traj, metric, start_time=start_time)

    if not times:
        raise ValueError("Trajectory has no data points for the requested metric; cannot plot metric curve")

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.plot(times, values, marker="o", linewidth=1.0, markersize=3.0)
    ax.set_xlabel("Time")
    ax.set_ylabel(metric)
    ax.set_title(f"{metric} over time")
    ax.grid(True, linestyle="--", alpha=0.4)

    fig.tight_layout()
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, bbox_inches="tight")
    return fig, ax



import seaborn as sns


import seaborn as sns
import matplotlib.gridspec as gridspec
from matplotlib.patches import Rectangle, Circle, Wedge
from matplotlib.collections import PatchCollection
import math

# ---- Color Palette ----
COLORS = {
    "processing": "#3B82F6",  # Blue
    "waiting": "#F59E0B",     # Orange
    "completed": "#10B981",   # Green
    "tardy": "#EF4444",       # Red
    "cancelled": "#9CA3AF",   # Gray
    "bg": "#F3F4F6",          # Light Gray
    "text": "#374151",        # Dark Gray
    "grid": "#E5E7EB",        # Light Grid
}

def _extract_raw_data(traj: Trajectory) -> Dict[str, Any]:
    """Extract raw data lists for distribution plots."""
    snap = traj.last_snapshot
    jobs = snap.jobs
    machines = snap.machines
    
    # Tardiness distribution
    tardiness_list = []
    horizon = float(getattr(snap, "horizon", 0.0))
    for j in jobs:
        if j.completion_time:
            c = float(j.completion_time)
        else:
            c = float(snap.time)
            
        # Check due date
        has_due = False
        try:
            dd = float(j.due_date)
            if dd < horizon - 1e-9:
                has_due = True
        except:
            pass
            
        if has_due:
            tardiness_list.append(max(0.0, c - dd))
            
    # Utilization distribution
    util_list = list(snap.system_stats.utilization_by_machine.values()) if hasattr(snap.system_stats, "utilization_by_machine") else []
    
    return {
        "tardiness_list": tardiness_list,
        "util_list": util_list,
        "num_jobs": len(jobs),
        "num_completed": sum(1 for j in jobs if j.status == "completed"),
        "num_cancelled": sum(1 for j in jobs if j.status == "cancelled"),
    }

def _extract_time_series_data(traj: Trajectory, start_time: float = 0.0) -> Dict[str, List[float]]:
    """Extract time series for WIP and queue length.

    If ``start_time`` is positive, only decision points with time >= start_time
    are included (useful for warm-start visualizations).
    """

    times: List[float] = []
    wip_waiting: List[float] = []
    wip_processing: List[float] = []
    queue_lengths: List[float] = []

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
            times.append(t)

            n_wait = float(rec.get("wip_waiting", 0.0))
            n_proc = float(rec.get("wip_processing", 0.0))
            wip_waiting.append(n_wait)
            wip_processing.append(n_proc)

            q_len = float(rec.get("queue_total", 0.0))
            queue_lengths.append(q_len)

        return {
            "times": times,
            "wip_waiting": wip_waiting,
            "wip_processing": wip_processing,
            "queue_lengths": queue_lengths,
        }

    for step in traj.steps:
        t = float(step.time)
        if t < float(start_time):
            continue
        times.append(t)
        s = step.snapshot
        
        # WIP
        n_wait = sum(1 for j in s.jobs if j.status == "waiting")
        n_proc = sum(1 for j in s.jobs if j.status == "processing")
        wip_waiting.append(n_wait)
        wip_processing.append(n_proc)
        
        # Queue
        q_len = sum(len(m.queue) for m in s.machines)
        queue_lengths.append(q_len)
        
    return {
        "times": times,
        "wip_waiting": wip_waiting,
        "wip_processing": wip_processing,
        "queue_lengths": queue_lengths,
    }

def plot_all_metrics_from_trajectory(
    traj: Trajectory,
    *,
    out_path: Optional[Path] = None,
    figsize: Tuple[float, float] = (16.0, 12.0),
    dpi: int = 150,
    start_time: float = 0.0,
):
    """Generate a comprehensive static dashboard for simulation analysis.

    When ``start_time`` is greater than zero, aggregated scalar metrics and the
    WIP/queue time series are restricted to the trailing window
    ``[start_time, last_time]`` of the trajectory (warm-start view). Job-level
    distributions that depend only on the final snapshot remain unchanged.
    """

    metrics = evaluate_trajectory(traj, start_time=start_time)
    raw_data = _extract_raw_data(traj)
    ts_data = _extract_time_series_data(traj, start_time=start_time)
    
    # Setup Figure and Grid
    sns.set_theme(style="white", context="notebook")
    fig = plt.figure(figsize=figsize, dpi=dpi, constrained_layout=True)
    fig.patch.set_facecolor(COLORS["bg"])
    
    # Grid Layout: 
    # Row 0: Header/KPIs (Height 1)
    # Row 1: Middle Section (Height 3) - Split Left/Right
    # Row 2: Bottom Section (Height 2)
    gs = fig.add_gridspec(3, 1, height_ratios=[0.8, 3, 1.5])
    
    # ---- 1. Header & KPI Scorecard ----
    gs_header = gridspec.GridSpecFromSubplotSpec(1, 4, subplot_spec=gs[0], wspace=0.1)
    
    def draw_kpi_card(ax, title, value, subtext=None, color=COLORS["text"], icon_color=None):
        ax.set_facecolor("white")
        ax.axis("off")
        # Background card effect
        rect = Rectangle((0, 0), 1, 1, transform=ax.transAxes, color="white", ec=COLORS["grid"], lw=1, zorder=0)
        ax.add_patch(rect)
        
        ax.text(0.05, 0.75, title, transform=ax.transAxes, fontsize=10, color="#6B7280", fontweight="bold")
        ax.text(0.05, 0.4, value, transform=ax.transAxes, fontsize=24, color=color, fontweight="bold")
        if subtext:
            ax.text(0.05, 0.15, subtext, transform=ax.transAxes, fontsize=9, color="#9CA3AF")
        if icon_color:
            # Simple colored strip on left
            strip = Rectangle((0, 0), 0.02, 1, transform=ax.transAxes, color=icon_color)
            ax.add_patch(strip)

    # KPI 1: Makespan
    ax_kpi1 = fig.add_subplot(gs_header[0])
    draw_kpi_card(ax_kpi1, "MAKESPAN", f"{metrics.get('makespan', 0):.1f}", "Time Units", icon_color=COLORS["processing"])
    
    # KPI 2: Completion Ratio (Donut-like text)
    ax_kpi2 = fig.add_subplot(gs_header[1])
    comp_ratio = metrics.get('job_completion_ratio', 0)
    draw_kpi_card(ax_kpi2, "COMPLETION RATE", f"{comp_ratio:.1%}", 
                  f"Completed: {int(metrics.get('num_jobs_completed', 0))}/{int(metrics.get('num_jobs_total', 0))}", 
                  color=COLORS["completed"], icon_color=COLORS["completed"])

    # KPI 3: Utilization
    ax_kpi3 = fig.add_subplot(gs_header[2])
    util = metrics.get('avg_utilization_global', 0)
    util_color = COLORS["waiting"] if util < 0.4 else (COLORS["processing"] if util < 0.8 else COLORS["tardy"])
    draw_kpi_card(ax_kpi3, "GLOBAL UTILIZATION", f"{util:.1%}", 
                  f"Range: {metrics.get('min_utilization_global',0):.0%} - {metrics.get('max_utilization_global',0):.0%}",
                  color=util_color, icon_color=util_color)

    # KPI 4: Mean Flow Time
    ax_kpi4 = fig.add_subplot(gs_header[3])
    draw_kpi_card(ax_kpi4, "MEAN FLOW TIME", f"{metrics.get('mean_flow_time', 0):.1f}", 
                  f"Total: {metrics.get('total_flow_time', 0):.0f}", icon_color="#6366F1")

    # ---- 2. Middle Section: Resource (Left) vs Delivery (Right) ----
    gs_middle = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs[1], wspace=0.15)
    
    # Left Panel: Resource & Bottleneck
    gs_left = gridspec.GridSpecFromSubplotSpec(3, 1, subplot_spec=gs_middle[0], height_ratios=[1, 1, 1], hspace=0.3)
    
    # 2.1 WIP Stacked Area
    ax_wip = fig.add_subplot(gs_left[0])
    ax_wip.set_title("WIP Dynamics (Waiting vs Processing)", fontsize=10, loc='left', fontweight='bold')
    ax_wip.stackplot(ts_data["times"], ts_data["wip_processing"], ts_data["wip_waiting"], 
                     labels=['Processing', 'Waiting'], colors=[COLORS["processing"], COLORS["waiting"]], alpha=0.8)
    ax_wip.legend(loc='upper left', fontsize=8, frameon=False)
    ax_wip.set_ylabel("Job Count", fontsize=8)
    ax_wip.grid(True, linestyle='--', alpha=0.3)
    ax_wip.margins(x=0)

    # 2.2 Queue Length Line
    ax_queue = fig.add_subplot(gs_left[1])
    ax_queue.set_title("Total Queue Length", fontsize=10, loc='left', fontweight='bold')
    ax_queue.plot(ts_data["times"], ts_data["queue_lengths"], color=COLORS["waiting"], linewidth=1.5)
    ax_queue.fill_between(ts_data["times"], ts_data["queue_lengths"], color=COLORS["waiting"], alpha=0.1)
    # Add max line
    max_q = metrics.get('max_queue_length_total', 0)
    ax_queue.axhline(max_q, color=COLORS["tardy"], linestyle=':', linewidth=1)
    ax_queue.text(ts_data["times"][0], max_q, f" Max: {max_q:.0f}", color=COLORS["tardy"], fontsize=8, va='bottom')
    ax_queue.set_ylabel("Queue Len", fontsize=8)
    ax_queue.grid(True, linestyle='--', alpha=0.3)
    ax_queue.margins(x=0)

    # 2.3 Utilization Boxplot
    ax_util = fig.add_subplot(gs_left[2])
    ax_util.set_title("Machine Utilization Distribution (Load Balance)", fontsize=10, loc='left', fontweight='bold')
    if raw_data["util_list"]:
        sns.boxplot(x=raw_data["util_list"], ax=ax_util, color=COLORS["processing"], width=0.5, fliersize=3)
        sns.stripplot(x=raw_data["util_list"], ax=ax_util, color="#1F2937", size=3, alpha=0.5, jitter=True)
    ax_util.set_xlabel("Utilization", fontsize=8)
    ax_util.set_xlim(0, 1.05)
    ax_util.grid(True, axis='x', linestyle='--', alpha=0.3)

    # Right Panel: Delivery & Tardiness
    gs_right = gridspec.GridSpecFromSubplotSpec(2, 1, subplot_spec=gs_middle[1], height_ratios=[1, 1], hspace=0.3)
    
    # 2.4 Tardiness Overview (Bar + Pie/Waffle logic)
    # Split top right into 2 sub-columns
    gs_right_top = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_right[0], wspace=0.3)
    
    # Bar: Total vs Weighted Tardiness
    ax_tard_bar = fig.add_subplot(gs_right_top[0])
    ax_tard_bar.set_title("Tardiness Impact", fontsize=10, loc='left', fontweight='bold')
    tvals = [metrics.get('total_tardiness', 0), metrics.get('total_weighted_tardiness', 0)]
    tlabels = ['Total', 'Weighted']
    sns.barplot(x=tlabels, y=tvals, ax=ax_tard_bar, palette=[COLORS["tardy"], "#991B1B"], hue=tlabels, legend=False)
    ax_tard_bar.bar_label(ax_tard_bar.containers[0], fmt='%.0f', fontsize=8)
    ax_tard_bar.set_ylabel("Time Units", fontsize=8)
    sns.despine(ax=ax_tard_bar)
    
    # Pie: Job Status (Completed vs Tardy vs Others)
    ax_status = fig.add_subplot(gs_right_top[1])
    ax_status.set_title("Job Status Breakdown", fontsize=10, loc='center', fontweight='bold')
    
    n_total = raw_data["num_jobs"]
    n_tardy = metrics.get('num_tardy_jobs', 0)
    n_completed = raw_data["num_completed"]
    n_ontime = max(0, n_completed - n_tardy) # Assuming tardy jobs are also completed usually, or we count tardy separately. 
    # Let's simplify: Tardy (bad), On-time (good), Cancelled/Incomplete (neutral/bad)
    # Note: num_tardy_jobs counts jobs with completion > due. They must be completed.
    
    n_cancelled = raw_data["num_cancelled"]
    n_incomplete = n_total - n_completed - n_cancelled
    
    sizes = [n_ontime, n_tardy, n_cancelled + n_incomplete]
    labels = ['On-Time', 'Tardy', 'Other']
    colors = [COLORS["completed"], COLORS["tardy"], COLORS["cancelled"]]
    
    if n_total > 0:
        ax_status.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90, 
                      textprops={'fontsize': 8}, wedgeprops=dict(width=0.4, edgecolor='w'))
    
    # 2.5 Tardiness Histogram
    ax_hist = fig.add_subplot(gs_right[1])
    ax_hist.set_title("Tardiness Distribution (Tardy Jobs Only)", fontsize=10, loc='left', fontweight='bold')
    tardy_values = [t for t in raw_data["tardiness_list"] if t > 0]
    if tardy_values:
        sns.histplot(tardy_values, ax=ax_hist, color=COLORS["tardy"], kde=True, bins=15)
    else:
        ax_hist.text(0.5, 0.5, "No Tardy Jobs!", ha='center', va='center', color=COLORS["completed"], fontsize=12)
    ax_hist.set_xlabel("Tardiness Time", fontsize=8)
    sns.despine(ax=ax_hist)

    # ---- 3. Bottom Section: Stability & Dynamics ----
    gs_bottom = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs[2], wspace=0.2)
    
    # 3.1 Stability Radar
    # Normalize metrics for radar: 0 is good (center), 1 is bad (outer)
    # We need to define some arbitrary max values to normalize against, or just show raw values if they are small ratios.
    # Ratios are already 0-1. 
    # Reschedule freq: usually small. Edit intensity: 0-1.
    
    radar_metrics = {
        "Ops Changed %": metrics.get('avg_changed_ops_ratio', 0),
        "Edit Intensity": metrics.get('schedule_edit_intensity', 0),
        "Cancel %": metrics.get('job_cancellation_ratio', 0),
        "Resched Freq": min(1.0, metrics.get('reschedule_frequency', 0) * 10), # Scale up frequency for visibility
    }
    
    # Radar Chart Implementation in Matplotlib
    ax_radar = fig.add_subplot(gs_bottom[0], projection='polar')
    theta = np.linspace(0, 2*np.pi, len(radar_metrics), endpoint=False)
    values = list(radar_metrics.values())
    # Close the loop
    values += [values[0]]
    theta = np.concatenate([theta, [theta[0]]])
    
    ax_radar.set_title("Stability Radar (Lower is Better)", fontsize=10, fontweight='bold', pad=10)
    ax_radar.plot(theta, values, color="#8B5CF6", linewidth=2)
    ax_radar.fill(theta, values, color="#8B5CF6", alpha=0.2)
    ax_radar.set_xticks(theta[:-1])
    ax_radar.set_xticklabels(list(radar_metrics.keys()), fontsize=9)
    ax_radar.set_ylim(0, 1.0)
    ax_radar.grid(True, linestyle='--', alpha=0.3)
    
    # 3.2 Reschedule Stats Text/Capsule
    ax_stats = fig.add_subplot(gs_bottom[1])
    ax_stats.axis("off")
    
    # Draw some "Capsules" for stats
    def draw_stat_row(y, label, value, color):
        ax_stats.text(0.1, y, label, fontsize=10, color="#6B7280", ha='left')
        ax_stats.text(0.6, y, str(value), fontsize=10, color=color, fontweight='bold', ha='left')
        ax_stats.hlines(y-0.05, 0.1, 0.9, color=COLORS["grid"], lw=1)

    ax_stats.text(0, 0.9, "Dynamic Scheduling Stats", fontsize=12, fontweight='bold', color=COLORS["text"])
    draw_stat_row(0.7, "Total Reschedules", int(metrics.get('reschedule_steps', 0)), "#8B5CF6")
    draw_stat_row(0.5, "Avg Start Time Shift", f"{metrics.get('avg_start_time_shift', 0):.2f}", "#8B5CF6")
    draw_stat_row(0.3, "Max Start Time Shift", f"{metrics.get('max_start_time_shift', 0):.2f}", COLORS["tardy"])
    
    # Footer
    fig.text(0.99, 0.01, "Generated by DynaSchedBench", ha='right', fontsize=8, color="#9CA3AF")

    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, bbox_inches="tight", facecolor=fig.get_facecolor())

    return fig, ax_kpi1 # Return one axis as primary



    
