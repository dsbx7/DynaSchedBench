from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import json
import matplotlib.pyplot as plt
from collections import defaultdict, Counter


def _load_events_from_jsonl(path: Path) -> List[dict]:
    events: List[dict] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def plot_events_timeline(
    events: Iterable[dict],
    *,
    out_path: Optional[Path] = None,
    figsize: Tuple[float, float] = (10.0, 4.0),
    dpi: int = 150,
    start_time: float = 0.0,
):
    """Plot a simple time-line of events grouped by event_type.

    This accepts event dictionaries loaded directly from ``events.jsonl`` or
    any structurally compatible sequence of dictionaries.
    """

    events = list(events)
    if not events:
        raise ValueError("No events provided for timeline plot")

    # Optional warm-start: discard events before ``start_time``.
    if float(start_time) > 0.0:
        events = [e for e in events if float(e.get("time", 0.0)) >= float(start_time)]
        if not events:
            raise ValueError("No events in selected time window for timeline plot")
    time_to_events = defaultdict(list)
    for e in events:
        t = float(e.get("time", 0.0))
        time_to_events[t].append(e)

    times = sorted(time_to_events.keys())
    counts = [len(time_to_events[t]) for t in times]

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    (line,) = ax.plot(times, counts, marker="o", markersize=4.0, linestyle="-", linewidth=1.5)
    ax.fill_between(times, counts, step="mid", alpha=0.1)

    ax.set_xlabel("Time")
    ax.set_ylabel("#Events")
    ax.set_title("Events Count Over Time")
    ax.grid(True, axis="x", linestyle="--", alpha=0.4)

    if out_path is None:
        annot = ax.annotate(
            "",
            xy=(0, 0),
            xytext=(10, 10),
            textcoords="offset points",
            bbox=dict(boxstyle="round", fc="w", alpha=0.8),
            arrowprops=dict(arrowstyle="->"),
        )
        annot.set_visible(False)

        xdata = times
        ydata = counts

        def _summarize_event(e: dict) -> str:
            """Best-effort short summary for a single event.

            Machine-related events such as breakdowns and PM show group and
            machine ID when available; job-related events show job and operation
            identifiers. Other events fall back to a concise summary built from
            common keys.
            """

            etype = str(e.get("event_type", "UNKNOWN"))
            payload = e.get("payload") or e
            if not isinstance(payload, dict):
                payload = {}

            etype_lower = etype.lower()

            def _first_key(d: dict, keys: tuple) -> Optional[str]:
                for k in keys:
                    if k in d and d[k] is not None:
                        return str(d[k])
                return None

            job_id = _first_key(payload, ("job_id", "job", "jobId"))
            op_id = _first_key(payload, ("op_id", "operation_id", "op", "opId"))
            machine_id = _first_key(payload, ("machine_id", "machine", "machineId"))
            group = _first_key(payload, ("machine_group", "group", "group_id", "groupId"))

            if any(k in etype_lower for k in ("breakdown", "pm", "maint", "machine")) or machine_id:
                parts = []
                if group:
                    parts.append(f"group={group}")
                if machine_id:
                    parts.append(f"machine={machine_id}")
                if parts:
                    return ", ".join(parts)

            if any(k in etype_lower for k in ("arrival", "release", "cancel", "job")) or job_id:
                parts = []
                if job_id:
                    parts.append(f"job={job_id}")
                if op_id:
                    parts.append(f"op={op_id}")
                if parts:
                    return ", ".join(parts)

            generic_parts = []
            for k in ("job_id", "op_id", "machine_id", "machine_group", "target_state"):
                if k in payload and payload[k] is not None:
                    generic_parts.append(f"{k}={payload[k]}")
            return ", ".join(str(p) for p in generic_parts) if generic_parts else ""

        def _format_label(idx: int) -> str:
            t = xdata[idx]
            evs = time_to_events[t]
            type_counts = Counter(e.get("event_type", "UNKNOWN") for e in evs)
            lines = [f"t = {t:.3f}", f"{len(evs)} event(s):"]

            sample_by_type = {}
            for e in evs:
                et = e.get("event_type", "UNKNOWN")
                if et not in sample_by_type:
                    sample_by_type[et] = e

            for etype, cnt in type_counts.most_common():
                sample = sample_by_type.get(etype)
                extra = _summarize_event(sample) if sample is not None else ""
                if extra:
                    lines.append(f"- {etype}: {cnt} ({extra})")
                else:
                    lines.append(f"- {etype}: {cnt}")

            return "\n".join(lines)

        def _hover(event):
            vis = annot.get_visible()
            if event.inaxes == ax:
                cont, ind = line.contains(event)
                if cont:
                    idx = ind["ind"][0]
                    x = xdata[idx]
                    y = ydata[idx]
                    annot.xy = (x, y)
                    annot.set_text(_format_label(idx))
                    annot.set_visible(True)
                    fig.canvas.draw_idle()
                elif vis:
                    annot.set_visible(False)
                    fig.canvas.draw_idle()

        fig.canvas.mpl_connect("motion_notify_event", _hover)

    fig.tight_layout()
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, bbox_inches="tight")
    return fig, ax


def plot_events_timeline_from_jsonl(
    events_path: Path,
    *,
    out_path: Optional[Path] = None,
    figsize: Tuple[float, float] = (10.0, 4.0),
    dpi: int = 150,
    start_time: float = 0.0,
):
    """Convenience helper to load events.jsonl and plot the timeline."""

    events = _load_events_from_jsonl(events_path)
    return plot_events_timeline(
        events,
        out_path=out_path,
        figsize=figsize,
        dpi=dpi,
        start_time=start_time,
    )
