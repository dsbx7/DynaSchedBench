from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

from dsbx.Eval import Trajectory


def plot_job_gantt_from_trajectory(
    traj: Trajectory,
    *,
    out_path: Optional[Path] = None,
    figsize: Tuple[float, float] = (10.0, 6.0),
    dpi: int = 150,
    time_window: Optional[Tuple[float, float]] = None,
    x_grid_step: Optional[float] = None,
    legend_loc: str = "upper right",
):
    """Plot a job-centric Gantt chart from a trajectory.

    Unlike the machine-centric Gantt chart, each row represents one job. The
    x-axis is time, each bar is one processing interval for that job, and colors
    distinguish machine groups.
    """

    if not traj.steps:
        raise ValueError("Empty trajectory: nothing to plot")

    snap = traj.last_snapshot
    jobs = snap.jobs
    machines = snap.machines

    t_start: Optional[float] = None
    t_end: Optional[float] = None
    if time_window is not None:
        t_start, t_end = time_window
        if t_start >= t_end:
            raise ValueError("time_window must satisfy t_start < t_end")

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    all_groups: List[str] = []
    for j in jobs:
        for op in j.ops:
            if op.start_time is not None and op.end_time is not None:
                if op.machine_group not in all_groups:
                    all_groups.append(op.machine_group)
    all_groups = sorted(all_groups)
    group_to_color: Dict[str, Tuple[float, float, float, float]] = {}
    if all_groups:
        cmap = plt.get_cmap("tab20")
        for idx, g in enumerate(all_groups):
            base = cmap(idx % cmap.N)
            base_r, base_g, base_b, _ = base
            lighten = 0.5
            r = 1.0 - (1.0 - base_r) * lighten
            g_c = 1.0 - (1.0 - base_g) * lighten
            b = 1.0 - (1.0 - base_b) * lighten
            alpha = 0.9
            group_to_color[g] = (r, g_c, b, alpha)

    group_to_machines: Dict[str, List[str]] = {}
    for m in machines:
        g = getattr(m, "group", None)
        mid = getattr(m, "machine_id", None)
        if isinstance(g, str) and isinstance(mid, str):
            group_to_machines.setdefault(g, []).append(mid)
    for g, mids in group_to_machines.items():
        mids.sort()

    yticks: List[float] = []
    ylabels: List[str] = []

    has_any_segment = False

    for idx, j in enumerate(jobs):
        y = idx
        yticks.append(y)
        ylabels.append(j.job_id)

        for op in j.ops:
            if op.start_time is None or op.end_time is None:
                continue

            start = float(op.start_time)
            end = float(op.end_time)

            if t_start is not None and t_end is not None:
                if end <= t_start or start >= t_end:
                    continue
                if start < t_start:
                    start = t_start
                if end > t_end:
                    end = t_end

            width = end - start
            if width <= 0:
                continue

            has_any_segment = True
            color = group_to_color.get(op.machine_group, (0.85, 0.85, 0.85, 1.0))
            ax.barh(
                y=y,
                width=width,
                left=start,
                height=0.8,
                align="center",
                edgecolor="black",
                linewidth=0.4,
                color=color,
            )

    if not has_any_segment:
        raise ValueError("Empty schedule in selected time window: nothing to plot")

    if t_start is not None and t_end is not None:
        ax.set_xlim(t_start, t_end)

    if x_grid_step is not None and x_grid_step > 0.0:
        try:
            ax.xaxis.set_major_locator(MultipleLocator(x_grid_step))
        except Exception:
            # Fallback to default locator if something goes wrong
            pass

    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels)
    ax.set_xlabel("Time")
    ax.set_ylabel("Job")
    ax.set_title("DynaSchedBench Job-centric Gantt Chart")
    ax.grid(True, axis="x", linestyle="--", alpha=0.4)

    if all_groups:
        handles = []
        labels = []
        for g in all_groups:
            color = group_to_color[g]
            h = ax.barh(0, 0, color=color)  # dummy
            handles.append(h)

            machines_in_group = group_to_machines.get(g, [])
            if machines_in_group:
                label = f"{g} (" + ", ".join(machines_in_group) + ")"
            else:
                label = g
            labels.append(label)

        ax.legend(handles, labels, title="Machine Group", loc=legend_loc)

    fig.tight_layout()
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, bbox_inches="tight")
    return fig, ax
