from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

import colorsys
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

from dsbx.Eval import Trajectory


def plot_gantt_from_trajectory(
    traj: Trajectory,
    *,
    out_path: Optional[Path] = None,
    figsize: Tuple[float, float] = (10.0, 6.0),
    dpi: int = 300,
    time_window: Optional[Tuple[float, float]] = None,
    label_mode: str = "op",
    x_grid_step: Optional[float] = None,
):
    """Plot a simple Gantt chart from a trajectory.

    Uses the final snapshot's machine schedule segments. If ``time_window``
    is provided, only segments intersecting that window are drawn, and both
    bars and labels are clipped to the window.
    """

    snap = traj.last_snapshot
    machines = snap.machines
    jobs = snap.jobs

    # Identify tail operations of jobs that were cancelled before finishing
    # all operations. Only these tail segments will receive a special visual
    # highlight in the Gantt chart so that cancellations at the end of a
    # (unfinished) route are easy to spot.
    cancel_tail_ops: Set[Tuple[str, str]] = set()
    for j in jobs:
        jid = getattr(j, "job_id", None)
        if not isinstance(jid, str):
            continue
        try:
            cancelled = getattr(j, "cancellation_time", None) is not None
            cur_idx = int(getattr(j, "current_op_index", 0))
            total_ops = int(getattr(j, "total_ops", 0))
        except Exception:
            continue
        if not cancelled:
            continue
        # If the job was cancelled only after all operations were finished,
        # we do not treat it as a "tail-cancel" case for visualization.
        if total_ops <= 0 or cur_idx >= total_ops:
            continue

        tail_done_idx = -1
        try:
            for op in getattr(j, "ops", []) or []:
                if getattr(op, "status", None) == "done":
                    idx = int(getattr(op, "index", 0))
                    if idx > tail_done_idx:
                        tail_done_idx = idx
        except Exception:
            tail_done_idx = -1

        # Require at least one completed operation and at least one
        # *remaining* operation after it; otherwise there is no meaningful
        # unfinished tail to highlight.
        if tail_done_idx < 0 or tail_done_idx >= total_ops - 1:
            continue

        try:
            tail_op = j.ops[tail_done_idx]
            tail_op_id = getattr(tail_op, "op_id", None)
            if isinstance(tail_op_id, str):
                cancel_tail_ops.add((jid, tail_op_id))
        except Exception:
            continue

    t_start: Optional[float] = None
    t_end: Optional[float] = None
    if time_window is not None:
        t_start, t_end = time_window
        if t_start >= t_end:
            raise ValueError("time_window must satisfy t_start < t_end")

    job_ids_in_schedule: List[str] = []
    for m in machines:
        for seg in m.schedule_segments:
            job_id_val = getattr(seg, "job_id", None)
            if isinstance(job_id_val, str):
                job_ids_in_schedule.append(job_id_val)

    all_starts: List[float] = []
    all_ends: List[float] = []
    min_seg_width: Optional[float] = None
    for m in machines:
        for seg in m.schedule_segments:
            start = float(seg.start)
            end = float(seg.end)

            if t_start is not None and t_end is not None:
                if end <= t_start or start >= t_end:
                    continue
                if start < t_start:
                    start = t_start
                if end > t_end:
                    end = t_end

            if end <= start:
                continue

            all_starts.append(start)
            all_ends.append(end)
            width = end - start
            if min_seg_width is None or width < min_seg_width:
                min_seg_width = width

    if not all_starts or not all_ends:
        raise ValueError("Empty schedule in selected time window: nothing to plot")

    if t_start is not None and t_end is not None:
        total_span = t_end - t_start
    else:
        total_span = max(all_ends) - min(all_starts)

    #
    release_time_by_job: Dict[str, float] = {}
    for j in jobs:
        jid = getattr(j, "job_id", None)
        if isinstance(jid, str):
            try:
                release_time_by_job[jid] = float(j.release_time)
            except Exception:
                continue

    def _job_sort_key(jid: str) -> Tuple[float, str]:
        rt = release_time_by_job.get(jid)
        if rt is None:
            return (float("inf"), jid)
        return (rt, jid)

    unique_job_ids = sorted(set(job_ids_in_schedule))
    job_ids = sorted(unique_job_ids, key=_job_sort_key)

    job_index_for_label: Dict[str, int] = {job_id: idx + 1 for idx, job_id in enumerate(job_ids)}

    job_color: Dict[str, Tuple[float, float, float, float]] = {}
    num_jobs = len(job_ids)
    if num_jobs > 0:
        for idx, job_id in enumerate(job_ids):
            if job_id == "__DOWNTIME__":
                continue
            hue = (idx / max(1, num_jobs)) % 1.0
            lightness = 0.75
            saturation = 0.6
            r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
            job_color[job_id] = (r, g, b, 1.0)

    op_index_by_op_id: Dict[str, int] = {}
    for job in jobs:
        for op in job.ops:
            op_index_by_op_id[op.op_id] = op.index

    job_seq_label_counter: Dict[str, int] = {}

    # Choose a reasonable figure width so that the smallest visible segment
    # has a non-degenerate width on the page, while capping the total width
    # to avoid excessive memory usage.
    fig_width, fig_height = figsize
    if total_span > 0.0 and min_seg_width is not None and min_seg_width > 0.0:
        min_block_inches = 0.5

        if label_mode in ("job_id", "job_op") and job_ids:
            label_ids = [jid for jid in job_ids if isinstance(jid, str) and jid != "__DOWNTIME__"]
            if not label_ids:
                label_ids = [jid for jid in job_ids if isinstance(jid, str)]
            max_label_len = max(len(jid) for jid in label_ids) if label_ids else 0
            est_width = 0.12 * max_label_len
            if est_width > min_block_inches:
                min_block_inches = est_width

        max_fig_width_inches = 40.0
        required_width = total_span * (min_block_inches / min_seg_width)
        if required_width < fig_width:
            required_width = fig_width
        fig_width = min(required_width, max_fig_width_inches)

    fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=dpi)

    yticks: List[float] = []
    ylabels: List[str] = []

    for idx, m in enumerate(machines):
        y = float(idx)
        yticks.append(y)
        ylabels.append(m.machine_id)

        visible_segments: List[dict] = []
        for seg in m.schedule_segments:
            start = float(seg.start)
            end = float(seg.end)

            if t_start is not None and t_end is not None:
                if end <= t_start or start >= t_end:
                    continue
                if start < t_start:
                    start = t_start
                if end > t_end:
                    end = t_end

            if end <= start:
                continue

            new_entry = {
                "start": start,
                "end": end,
                "job_id": getattr(seg, "job_id", None),
                "op_id": getattr(seg, "op_id", None),
            }

            if not visible_segments:
                visible_segments.append(new_entry)
            else:
                updated: List[dict] = []
                ns = new_entry["start"]
                ne = new_entry["end"]

                for entry in visible_segments:
                    es = entry["start"]
                    ee = entry["end"]

                    if ee <= ns or es >= ne:
                        updated.append(entry)
                        continue

                    if es < ns:
                        updated.append(
                            {
                                "start": es,
                                "end": ns,
                                "job_id": entry["job_id"],
                                "op_id": entry["op_id"],
                            }
                        )
                    if ee > ne:
                        updated.append(
                            {
                                "start": ne,
                                "end": ee,
                                "job_id": entry["job_id"],
                                "op_id": entry["op_id"],
                            }
                        )

                updated.append(new_entry)
                visible_segments = updated

        if not visible_segments:
            continue

        seg_entries = sorted(visible_segments, key=lambda e: e["start"])

        for entry in seg_entries:
            left = entry["start"]
            width = entry["end"] - entry["start"]
            job_id_for_color = entry["job_id"]
            op_id_for_color = entry["op_id"]

            edgecolor = "black"
            linewidth = 0.5

            if job_id_for_color == "__DOWNTIME__":
                if isinstance(op_id_for_color, str) and "__DOWN_BD__" in op_id_for_color:
                    color = (0.85, 0.3, 0.3, 1.0)
                elif isinstance(op_id_for_color, str) and "__DOWN_PM__" in op_id_for_color:
                    color = (0.3, 0.45, 0.85, 1.0)
                else:
                    color = (0.6, 0.6, 0.6, 1.0)
            else:
                base_color = job_color.get(job_id_for_color, (0.7, 0.7, 0.7, 1.0))
                if (
                    isinstance(job_id_for_color, str)
                    and isinstance(op_id_for_color, str)
                    and (job_id_for_color, op_id_for_color) in cancel_tail_ops
                ):
                    color = base_color
                    edgecolor = "red"
                    linewidth = 1.2
                else:
                    color = base_color

            ax.barh(
                y=y,
                width=width,
                left=left,
                height=0.8,
                align="center",
                edgecolor=edgecolor,
                linewidth=linewidth,
                color=color,
            )

        logical_blocks: List[Tuple[float, float, str, Optional[str]]] = []
        current_block: Optional[List] = None

        for entry in seg_entries:
            job_id = entry["job_id"]
            op_id = entry["op_id"]
            start = entry["start"]
            end = entry["end"]

            if not isinstance(job_id, str):
                continue

            if current_block is None:
                current_block = [start, end, job_id, op_id]
                continue

            last_start, last_end, last_job, last_op = current_block
            if job_id == last_job and op_id == last_op and start <= last_end:
                if end > last_end:
                    current_block[1] = end
            else:
                logical_blocks.append(tuple(current_block))
                current_block = [start, end, job_id, op_id]

        if current_block is not None:
            logical_blocks.append(tuple(current_block))

        for start, end, job_id, op_id in logical_blocks:
            if job_id == "__DOWNTIME__":
                if isinstance(op_id, str) and "__DOWN_BD__" in op_id:
                    label_str = "BD"
                elif isinstance(op_id, str) and "__DOWN_PM__" in op_id:
                    label_str = "PM"
                else:
                    label_str = "DT"
                center_x = start + (end - start) * 0.5

                ax.text(
                    center_x,
                    y,
                    label_str,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="black",
                    clip_on=True,
                )
                continue

            job_idx = job_index_for_label.get(job_id)
            if job_idx is None:
                continue

            op_index = None
            if isinstance(op_id, str):
                op_index = op_index_by_op_id.get(op_id)

            if op_index is not None:
                op_vis_idx = int(op_index) + 1
            else:
                cur = job_seq_label_counter.get(job_id, 0) + 1
                job_seq_label_counter[job_id] = cur
                op_vis_idx = cur

            if label_mode == "job_id":
                label_str = str(job_id)
            elif label_mode == "job_op":
                #   WIP-3
                #   B2
                #   [1]
                jid_str = str(job_id)
                prefix, sep, suffix = jid_str.rpartition("-")
                if sep:
                    top = prefix
                    mid = suffix
                else:
                    top = jid_str
                    mid = ""

                if mid:
                    label_str = f"{top}\n{mid}\n[{op_vis_idx}]"
                else:
                    label_str = f"{top}\n[{op_vis_idx}]"
            else:
                label_str = rf"$O_{{{job_idx},{op_vis_idx}}}$"
            center_x = start + (end - start) * 0.5

            ax.text(
                center_x,
                y,
                label_str,
                ha="center",
                va="center",
                fontsize=8,
                color="black",
                clip_on=True,
            )

    if t_start is not None and t_end is not None:
        ax.set_xlim(t_start, t_end)

    # Optional fixed-step vertical grid on the time axis
    if x_grid_step is not None and x_grid_step > 0.0:
        try:
            ax.xaxis.set_major_locator(MultipleLocator(x_grid_step))
        except Exception:
            # Fallback to default locator if something goes wrong
            pass

    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels)
    ax.set_xlabel("Time")
    ax.set_ylabel("Machine")
    ax.set_title("DynaSchedBench Gantt Chart")
    ax.grid(True, axis="x", linestyle="--", alpha=0.4)

    fig.tight_layout()
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, bbox_inches="tight")
    return fig, ax
