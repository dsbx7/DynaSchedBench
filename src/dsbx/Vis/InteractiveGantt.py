from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib.cm as cm
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
import time

from dsbx.Eval import Trajectory


def interactive_gantt_from_files(
    gantt_path: Path,
    *,
    static_jobs_path: Optional[Path] = None,
    events_path: Optional[Path] = None,
    figsize: Tuple[float, float] = (12.0, 6.0),
    dpi: int = 150,
) -> Tuple[Figure, Axes, Axes]:
    """Interactive Gantt chart viewer with hover info panel.
    
    Reads gantt.json, optional static_jobs.json and events.jsonl,
    displays a machine-centric Gantt chart with a side text panel
    showing details when hovering over processing segments.
    """
    gantt_path = Path(gantt_path)
    with gantt_path.open("r", encoding="utf-8") as f:
        gantt_data = json.load(f)

    static_jobs: Dict[str, dict] = {}
    if static_jobs_path is not None:
        static_jobs_path = Path(static_jobs_path)
        with static_jobs_path.open("r", encoding="utf-8") as f:
            raw_static = json.load(f)
        jobs_obj = raw_static.get("jobs")
        if isinstance(jobs_obj, dict):
            static_jobs = jobs_obj

    events_by_job: Dict[str, List[dict]] = {}
    events_by_machine: Dict[str, List[dict]] = {}
    job_events_lines_cache: Dict[str, List[str]] = {}
    if events_path is not None:
        events_path = Path(events_path)
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                job_id = ev.get("job_id")
                if isinstance(job_id, str):
                    events_by_job.setdefault(job_id, []).append(ev)
                machine_id = ev.get("machine_id")
                if isinstance(machine_id, str):
                    events_by_machine.setdefault(machine_id, []).append(ev)

    jobs_by_id: Dict[str, dict] = {}
    op_index_by_op_id: Dict[str, int] = {}
    for job in gantt_data.get("jobs", []) or []:
        job_id = job.get("job_id")
        if not isinstance(job_id, str):
            continue
        jobs_by_id[job_id] = job
        for op in job.get("ops", []) or []:
            op_id = op.get("op_id")
            if not isinstance(op_id, str):
                continue
            idx = op.get("index")
            if isinstance(idx, int):
                op_index_by_op_id[op_id] = idx

    machines = gantt_data.get("machines", []) or []

    fig, (ax_gantt, ax_info) = plt.subplots(
        1,
        2,
        figsize=figsize,
        dpi=dpi,
        gridspec_kw={"width_ratios": [3.0, 2.0]},
    )

    bar_meta: Dict[Rectangle, dict] = {}
    rects_by_lane: Dict[int, List[Rectangle]] = {}
    rect_labels: Dict[Rectangle, object] = {}

    yticks: List[float] = []
    ylabels: List[str] = []

    job_ids: List[str] = []
    data_time_min: Optional[float] = None
    data_time_max: Optional[float] = None
    for machine in machines:
        for task in machine.get("tasks", []) or []:
            job_id = task.get("job_id")
            if isinstance(job_id, str) and job_id not in job_ids:
                job_ids.append(job_id)
    cmap = cm.get_cmap("tab20")
    job_to_color: Dict[str, Tuple[float, float, float, float]] = {}
    job_index_for_label: Dict[str, int] = {}
    job_seq_label_counter: Dict[str, int] = {}
    for idx, job_id in enumerate(sorted(job_ids)):
        job_to_color[job_id] = cmap(idx % cmap.N)
        job_index_for_label[job_id] = idx + 1

    for m_idx, machine in enumerate(machines):
        y = float(m_idx)
        machine_id = machine.get("machine_id")
        if not isinstance(machine_id, str):
            machine_id = f"M{m_idx}"
        machine_group = machine.get("group")

        yticks.append(y)
        ylabels.append(machine_id)

        for task in machine.get("tasks", []) or []:
            start = task.get("start")
            end = task.get("end")
            if start is None or end is None:
                continue
            try:
                start_f = float(start)
                end_f = float(end)
            except (TypeError, ValueError):
                continue
            width = end_f - start_f
            if width <= 0:
                continue

            if data_time_min is None or start_f < data_time_min:
                data_time_min = start_f
            if data_time_max is None or end_f > data_time_max:
                data_time_max = end_f

            job_id = task.get("job_id")
            op_id = task.get("op_id")
            is_cancel_tail = bool(task.get("is_cancel_tail", False))

            base_color = job_to_color.get(job_id, (0.3, 0.3, 0.3, 1.0))
            color = base_color
            edgecolor = "black"
            linewidth = 0.3
            if is_cancel_tail:
                # Use a distinct style for tail segments of cancelled jobs.
                color = (1.0, 0.6, 0.6, 1.0)
                edgecolor = "red"
                linewidth = 0.8

            rects = ax_gantt.barh(
                y=y,
                width=width,
                left=start_f,
                height=0.8,
                align="center",
                edgecolor=edgecolor,
                linewidth=linewidth,
                color=color,
                alpha=0.9,
            )
            rect = rects[0]

            op_index: Optional[int] = None
            if isinstance(op_id, str):
                if op_id in op_index_by_op_id:
                    op_index = op_index_by_op_id[op_id]
                else:
                    marker = "-op"
                    if marker in op_id:
                        suffix = op_id.split(marker)[-1]
                        try:
                            op_index = int(suffix)
                        except ValueError:
                            op_index = None

            static_pt: Optional[float] = None
            if static_jobs and isinstance(job_id, str) and op_index is not None:
                job_static = static_jobs.get(job_id)
                if isinstance(job_static, dict):
                    pt_list = job_static.get("process_times") or []
                    if (
                        isinstance(pt_list, list)
                        and 0 <= op_index < len(pt_list)
                    ):
                        try:
                            static_pt = float(pt_list[op_index])
                        except (TypeError, ValueError):
                            static_pt = None

            job_info = jobs_by_id.get(job_id) if isinstance(job_id, str) else None

            bar_meta[rect] = {
                "machine_id": machine_id,
                "machine_group": machine_group,
                "job_id": job_id,
                "op_id": op_id,
                "start": start_f,
                "end": end_f,
                "duration": width,
                "op_index": op_index,
                "static_pt": static_pt,
                "job_info": job_info,
                "is_cancel_tail": is_cancel_tail,
            }

            rects_by_lane.setdefault(m_idx, []).append(rect)

            if isinstance(job_id, str):
                job_idx = job_index_for_label.get(job_id)
                if job_idx is not None:
                    if op_index is not None:
                        op_vis_idx = int(op_index) + 1
                    else:
                        cur = job_seq_label_counter.get(job_id, 0) + 1
                        job_seq_label_counter[job_id] = cur
                        op_vis_idx = cur

                    label_str = rf"$O_{{{job_idx},{op_vis_idx}}}$"
                    text_obj = ax_gantt.text(
                        start_f + width * 0.5,
                        y,
                        label_str,
                        ha="center",
                        va="center",
                        fontsize=8,
                        color="black",
                        visible=False,
                        clip_on=True,
                    )
                    rect_labels[rect] = text_obj

    ax_gantt.set_yticks(yticks)
    ax_gantt.set_yticklabels(ylabels)
    ax_gantt.set_xlabel("Time")
    ax_gantt.set_ylabel("Machine")
    ax_gantt.set_title("Gantt inspect")
    ax_gantt.grid(True, axis="x", linestyle="--", alpha=0.4)

    if data_time_min is not None and data_time_max is not None:
        span = data_time_max - data_time_min
        if span <= 0:
            span = 1.0
        pad = 0.02 * span
        ax_gantt.set_xlim(data_time_min - pad, data_time_max + pad)

    ax_info.axis("off")
    ax_info.text(
        0.01,
        0.99,
        "Hover over a bar to see details.",
        va="top",
        ha="left",
        fontsize=9,
        family="monospace",
    )

    active_rect: Optional[Rectangle] = None
    pan_active: bool = False
    pan_last_x: Optional[float] = None
    last_update_time: float = 0.0
    labels_on: bool = False
    last_labels_update_time: float = 0.0
    max_zoom_factor: float = 5.0

    def _fmt(value: Optional[float]) -> str:
        if value is None:
            return "n/a"
        try:
            return f"{float(value):.4f}"
        except (TypeError, ValueError):
            return str(value)

    def _overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
        return (a0 <= b1) and (b0 <= a1)

    def _format_events(meta: dict) -> List[str]:
        lines: List[str] = []
        job_id = meta.get("job_id")
        machine_id = meta.get("machine_id")
        start = meta.get("start")
        end = meta.get("end")

        if isinstance(job_id, str) and events_by_job:
            cached = job_events_lines_cache.get(job_id)
            if cached is None:
                job_events = events_by_job.get(job_id, [])
                if job_events:
                    block: List[str] = ["Job events:"]
                    shown = 0
                    for ev in job_events:
                        t = ev.get("time")
                        etype = ev.get("event_type")
                        if etype is None:
                            continue
                        extra_parts: List[str] = []
                        for k, v in ev.items():
                            if k in {"time", "event_type"}:
                                continue
                            extra_parts.append(f"{k}={v}")
                        extra = " ".join(extra_parts)
                        if extra:
                            block.append(f"  t={_fmt(t)} {etype} {extra}")
                        else:
                            block.append(f"  t={_fmt(t)} {etype}")
                        shown += 1
                        if shown >= 10:
                            break
                    cached = block
                    job_events_lines_cache[job_id] = cached
            if cached:
                lines.extend(cached)

        if (
            isinstance(machine_id, str)
            and events_by_machine
            and start is not None
            and end is not None
        ):
            machine_events = events_by_machine.get(machine_id, [])
            breakdowns: List[dict] = []
            for ev in machine_events:
                if ev.get("event_type") != "BREAKDOWN":
                    continue
                t = ev.get("time")
                duration = ev.get("duration", 0.0)
                if t is None:
                    continue
                try:
                    bd_start = float(t)
                    bd_end = bd_start + float(duration)
                except (TypeError, ValueError):
                    continue
                if _overlap(start, end, bd_start, bd_end):
                    breakdowns.append(ev)
            if breakdowns:
                lines.append("Machine breakdowns overlapping:")
                for ev in breakdowns[:5]:
                    t = ev.get("time")
                    duration = ev.get("duration", 0.0)
                    lines.append(
                        f"  t={_fmt(t)} duration={_fmt(duration)}"
                    )

        if not lines:
            lines.append("No related events.")
        return lines

    def _update_labels_for_view(force: bool = False) -> None:
        """Show labels for visible bars only, with throttled updates.

        Labels appear only when the current time span is below the zoom
        threshold, only bars intersecting the current time range are labeled,
        and updates are throttled through ``last_labels_update_time`` to avoid
        recomputing labels on every tiny pan movement.
        """

        nonlocal labels_on, last_labels_update_time

        if not rect_labels:
            return
        if data_time_min is None or data_time_max is None:
            return

        full_span = data_time_max - data_time_min
        if full_span <= 0:
            return

        xmin, xmax = ax_gantt.get_xlim()
        span = xmax - xmin
        if span <= 0:
            return

        min_span = full_span / max_zoom_factor
        want_labels = span <= min_span

        now = time.monotonic()
        if (not force) and (want_labels == labels_on) and (now - last_labels_update_time < 0.05):
            return

        last_labels_update_time = now
        labels_on = want_labels

        if not labels_on:
            for text in rect_labels.values():
                if text.get_visible():
                    text.set_visible(False)
            return

        for rect, text in rect_labels.items():
            meta = bar_meta.get(rect)
            if not meta:
                if text.get_visible():
                    text.set_visible(False)
                continue

            start = meta.get("start")
            end = meta.get("end")
            if start is None or end is None:
                if text.get_visible():
                    text.set_visible(False)
                continue

            if (float(end) < xmin) or (float(start) > xmax):
                if text.get_visible():
                    text.set_visible(False)
                continue

            visible_start = max(float(start), xmin)
            visible_end = min(float(end), xmax)
            center_x = 0.5 * (visible_start + visible_end)

            center_y = rect.get_y() + rect.get_height() * 0.5
            text.set_position((center_x, center_y))

            if not text.get_visible():
                text.set_visible(True)

    def on_motion(event) -> None:
        nonlocal active_rect, pan_active, pan_last_x, last_update_time

        if event.inaxes is not ax_gantt:
            if active_rect is not None:
                active_rect.set_linewidth(0.3)
                active_rect.set_edgecolor("black")
                active_rect = None
                fig.canvas.draw_idle()
            return

        if pan_active and event.xdata is not None and pan_last_x is not None:
            cur_xmin, cur_xmax = ax_gantt.get_xlim()
            if cur_xmax > cur_xmin:
                dx = float(event.xdata) - float(pan_last_x)
                new_xmin = cur_xmin - dx
                new_xmax = cur_xmax - dx

                if data_time_min is not None and data_time_max is not None:
                    full_span = data_time_max - data_time_min
                    if full_span <= 0:
                        full_span = 1.0
                    pad = 0.02 * full_span
                    min_allowed = data_time_min - pad
                    max_allowed = data_time_max + pad
                    span = new_xmax - new_xmin
                    if span > 0:
                        if new_xmin < min_allowed:
                            shift = min_allowed - new_xmin
                            new_xmin += shift
                            new_xmax += shift
                        if new_xmax > max_allowed:
                            shift = new_xmax - max_allowed
                            new_xmin -= shift
                            new_xmax -= shift

                ax_gantt.set_xlim(new_xmin, new_xmax)
                fig.canvas.draw_idle()

            pan_last_x = event.xdata
            return

        ydata = event.ydata
        lanes_to_check: List[int] = []
        if ydata is not None:
            lane = int(round(ydata))
            lanes_to_check = [lane, lane - 1, lane + 1]

        candidate_rects: List[Rectangle] = []
        for lane in lanes_to_check:
            rects_lane = rects_by_lane.get(lane)
            if rects_lane:
                candidate_rects.extend(rects_lane)

        if not candidate_rects:
            if active_rect is not None:
                active_rect.set_linewidth(0.3)
                active_rect.set_edgecolor("black")
                active_rect = None
                fig.canvas.draw_idle()
            return

        hits: List[Rectangle] = []
        for rect in candidate_rects:
            contains, _ = rect.contains(event)
            if contains:
                hits.append(rect)

        if not hits:
            if active_rect is not None:
                active_rect.set_linewidth(0.3)
                active_rect.set_edgecolor("black")
                active_rect = None
                fig.canvas.draw_idle()
            return

        if event.xdata is not None:
            ex = float(event.xdata)
            best_rect = min(
                hits,
                key=lambda r: abs(ex - (r.get_x() + r.get_width() / 2.0)),
            )
        else:
            best_rect = hits[0]

        if best_rect is active_rect:
            now = time.monotonic()
            if now - last_update_time < 0.03:
                return
        else:
            if active_rect is not None:
                active_rect.set_linewidth(0.3)
                active_rect.set_edgecolor("black")
            active_rect = best_rect
            active_rect.set_linewidth(1.5)
            active_rect.set_edgecolor("red")

        meta = bar_meta[best_rect]

        now = time.monotonic()
        if now - last_update_time < 0.03:
            return
        last_update_time = now

        lines: List[str] = []

        machine_id = meta.get("machine_id")
        machine_group = meta.get("machine_group")
        job_id = meta.get("job_id")
        op_id = meta.get("op_id")
        op_index = meta.get("op_index")
        start = meta.get("start")
        end = meta.get("end")
        duration = meta.get("duration")
        static_pt = meta.get("static_pt")
        job_info = meta.get("job_info")

        lines.append(f"Machine: {machine_id} group={machine_group}")
        lines.append(f"Job/op: {job_id} / {op_id} index={op_index}")
        lines.append(
            "Realized: start={0} end={1} dur={2}".format(
                _fmt(start),
                _fmt(end),
                _fmt(duration),
            )
        )

        if static_jobs_path is None:
            lines.append("Static: static_jobs.json not provided.")
        else:
            if static_pt is not None:
                lines.append(f"Static planned PT: {_fmt(static_pt)}")
                if duration is not None:
                    diff = float(duration) - float(static_pt)
                    lines.append(f"Diff(real-static): {_fmt(diff)}")
            else:
                lines.append("Static planned PT: n/a")

        if job_info is not None:
            release = job_info.get("release_time")
            due = job_info.get("due_date")
            completion = job_info.get("completion_time")
            lines.append("Job timing in gantt.json:")
            lines.append(
                "  release={0} due={1} completion={2}".format(
                    _fmt(release),
                    _fmt(due),
                    _fmt(completion),
                )
            )

        if events_path is None:
            lines.append("Events: events.jsonl not provided.")
        else:
            lines.append("")
            lines.extend(_format_events(meta))

        text = "\n".join(lines)

        ax_info.clear()
        ax_info.axis("off")
        ax_info.text(
            0.01,
            0.99,
            text,
            va="top",
            ha="left",
            fontsize=9,
            family="monospace",
        )
        fig.canvas.draw_idle()

    def on_button_press(event) -> None:
        nonlocal pan_active, pan_last_x

        if event.inaxes is not ax_gantt:
            return

        if event.button == 1 and event.xdata is not None:
            pan_active = True
            pan_last_x = float(event.xdata)

    def on_button_release(event) -> None:
        nonlocal pan_active, pan_last_x

        if pan_active:
            pan_active = False
            pan_last_x = None
            _update_labels_for_view(force=True)

    def on_scroll(event) -> None:
        """Mouse wheel zoom on the Gantt axis (time axis)."""

        if event.inaxes is not ax_gantt:
            return

        if event.xdata is None:
            return

        cur_xmin, cur_xmax = ax_gantt.get_xlim()
        if cur_xmax <= cur_xmin:
            return

        if event.button == "up":
            scale = 1.0 / 1.2
        elif event.button == "down":
            scale = 1.2
        else:
            return

        center = float(event.xdata)
        width_left = center - cur_xmin
        width_right = cur_xmax - center
        new_xmin = center - width_left * scale
        new_xmax = center + width_right * scale

        if data_time_min is not None and data_time_max is not None:
            full_span = data_time_max - data_time_min
            if full_span <= 0:
                full_span = 1.0
            min_span = full_span / max_zoom_factor
            max_span = full_span * 10.0
            new_span = new_xmax - new_xmin

            if new_span < min_span:
                center = (new_xmin + new_xmax) * 0.5
                new_xmin = center - min_span * 0.5
                new_xmax = center + min_span * 0.5
                new_span = min_span

            if new_span > max_span:
                pad = 0.02 * full_span
                new_xmin = data_time_min - pad
                new_xmax = data_time_max + pad

        ax_gantt.set_xlim(new_xmin, new_xmax)
        _update_labels_for_view()
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("motion_notify_event", on_motion)
    fig.canvas.mpl_connect("scroll_event", on_scroll)
    fig.canvas.mpl_connect("button_press_event", on_button_press)
    fig.canvas.mpl_connect("button_release_event", on_button_release)

    fig.tight_layout()

    return fig, ax_gantt, ax_info


def _trajectory_to_gantt_dict(
    traj: Trajectory,
    time_window: Optional[Tuple[float, float]] = None,
) -> Dict[str, object]:
    """Convert a Trajectory's final snapshot into a gantt.json-like dict.

    If ``time_window`` is provided, only tasks intersecting that window are
    included and their start/end times are clipped to the window, mirroring
    the behavior of the static Gantt implementation.
    """

    snap = traj.last_snapshot
    t_start: Optional[float] = None
    t_end: Optional[float] = None
    if time_window is not None:
        t_start, t_end = time_window
        if t_start >= t_end:
            raise ValueError("time_window must satisfy t_start < t_end")

    # Identify tail operations of jobs that were cancelled before finishing
    # all operations, mirroring the static Gantt semantics.
    cancel_tail_ops = set()
    for j in snap.jobs:
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
        if tail_done_idx < 0 or tail_done_idx >= total_ops - 1:
            continue
        try:
            tail_op = j.ops[tail_done_idx]
            tail_op_id = getattr(tail_op, "op_id", None)
            if isinstance(tail_op_id, str):
                cancel_tail_ops.add((jid, tail_op_id))
        except Exception:
            continue

    machines_data: List[Dict[str, object]] = []
    for m in snap.machines:
        tasks: List[Dict[str, object]] = []
        for seg in m.schedule_segments:
            try:
                start_f = float(seg.start)
                end_f = float(seg.end)
            except (TypeError, ValueError):
                continue

            if t_start is not None and t_end is not None:
                if end_f <= t_start or start_f >= t_end:
                    continue
                if start_f < t_start:
                    start_f = t_start
                if end_f > t_end:
                    end_f = t_end

            if end_f <= start_f:
                continue

            jid = getattr(seg, "job_id", None)
            op_id = getattr(seg, "op_id", None)

            task: Dict[str, object] = {
                "start": start_f,
                "end": end_f,
                "job_id": jid,
                "op_id": op_id,
            }
            if isinstance(jid, str) and isinstance(op_id, str) and (jid, op_id) in cancel_tail_ops:
                task["is_cancel_tail"] = True

            tasks.append(task)

        machines_data.append(
            {
                "machine_id": getattr(m, "machine_id", None),
                "group": getattr(m, "group", None),
                "tasks": tasks,
            }
        )

    jobs_data: List[Dict[str, object]] = []
    for j in snap.jobs:
        jobs_data.append(
            {
                "job_id": getattr(j, "job_id", None),
                "release_time": getattr(j, "release_time", None),
                "due_date": getattr(j, "due_date", None),
                "completion_time": getattr(j, "completion_time", None),
                "cancellation_time": getattr(j, "cancellation_time", None),
            }
        )

    return {"jobs": jobs_data, "machines": machines_data}


def interactive_gantt_from_trajectory(
    traj: Trajectory,
    *,
    static_jobs_path: Optional[Path] = None,
    events_path: Optional[Path] = None,
    figsize: Tuple[float, float] = (12.0, 6.0),
    dpi: int = 150,
    time_window: Optional[Tuple[float, float]] = None,
) -> Tuple[Figure, Axes, Axes]:
    """Interactive Gantt viewer directly from a Trajectory JSON.

    This helper converts the final snapshot of a :class:`Trajectory` into
    an in-memory gantt.json-like structure, writes it to a temporary file,
    and then delegates to :func:`interactive_gantt_from_files` to reuse the
    existing interactive visualization logic. The temporary file is removed
    after the figure is created.

    When ``time_window`` is provided, only the portion of the schedule within
    that window is visualized (warm-start style view).
    """

    gantt_dict = _trajectory_to_gantt_dict(traj, time_window=time_window)

    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            json.dump(gantt_dict, tmp)
            tmp_path = Path(tmp.name)

        fig, ax_gantt, ax_info = interactive_gantt_from_files(
            tmp_path,
            static_jobs_path=static_jobs_path,
            events_path=events_path,
            figsize=figsize,
            dpi=dpi,
        )
    finally:
        if tmp_path is not None:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return fig, ax_gantt, ax_info
