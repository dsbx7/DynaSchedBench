from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from loguru import logger
from typing_extensions import Annotated

from dsbx.Eval import Trajectory
from dsbx.Logging import init_logging
from dsbx.Vis import (
    plot_gantt_from_trajectory,
    plot_job_gantt_from_trajectory,
)
from dsbx.Vis.MetricsCurves import (
    plot_metric_over_time,
    plot_all_metrics_from_trajectory,
    SUPPORTED_METRIC_OVER_TIME,
)
from dsbx.Eval.Metrics import METRIC_STATIC_KEYS, METRIC_DYNAMIC_KEYS
from dsbx.Vis.EventsTimeline import plot_events_timeline_from_jsonl
from dsbx.Vis.InteractiveGantt import interactive_gantt_from_trajectory


app = typer.Typer(
    name="dsbx-vis",
    help="Visualize DynaSchedBench trajectories and metrics.",
    add_completion=False,
)


def _load_trajectory_for_vis(trajectory_file: Path) -> Trajectory:
    """Internal helper to load a Trajectory for visualization, supporting JSON and JSONL."""

    if trajectory_file.suffix.lower() == ".jsonl":
        try:
            return Trajectory.load_from_disk(trajectory_file)
        except Exception as e:  # pragma: no cover - filesystem / parse error path
            logger.error(f"Failed to load trajectory JSONL file: {e}")
            raise typer.Exit(code=3)

    try:
        raw = trajectory_file.read_text(encoding="utf-8")
    except OSError as e:  # pragma: no cover - filesystem error path
        logger.error(f"Failed to read trajectory file: {e}")
        raise typer.Exit(code=3)

    return Trajectory.model_validate_json(raw)


@app.command(name="gantt")
def gantt(
    trajectory_file: Annotated[
        Path,
        typer.Option(
            "-t",
            "--trajectory",
            exists=True,
            readable=True,
            help="Path to a JSON file containing a serialized Trajectory.",
        ),
    ],
    out_path: Annotated[
        Optional[Path],
        typer.Option("-o", "--out", help="Output PDF path (default: <trajectory_dir>/gantt.pdf)."),
    ] = None,
    chunk_width: Annotated[
        Optional[float],
        typer.Option(
            "--chunk",
            help=(
                "Optional time window width; if set, split the timeline into windows of this "
                "duration and write a multi-page PDF (one page per window)."
            ),
        ),
    ] = None,
    label_mode: Annotated[
        str,
        typer.Option(
            "--label",
            help=(
                "Label mode: 'op' (default) for O_{i,j}, 'job_id' to show raw job_id, "
                "or 'job_op' to show job_id with operation index."
            ),
        ),
    ] = "op",
    x_grid_step: Annotated[
        Optional[float],
        typer.Option(
            "--x-grid-step",
            help=(
                "Optional fixed spacing for vertical grid lines on the time axis. "
                "If set to a positive value, major ticks and grid lines are placed "
                "every this many time units."
            ),
        ),
    ] = None,
    warm: Annotated[
        bool,
        typer.Option(
            "--warm",
            help=(
                "Enable warm-start view: restrict the Gantt to the trailing time window "
                "of the trajectory (based on --warmup-ratio)."
            ),
        ),
    ] = False,
    warmup_ratio: Annotated[
        float,
        typer.Option(
            "--warmup-ratio",
            help=(
                "For --warm: fraction of the trajectory time to treat as warm-up and "
                "exclude from the plot window (0.0-1.0)."
            ),
        ),
    ] = 0.3,
) -> None:
    """Render a Gantt chart from a serialized trajectory."""

    init_logging(component="V", command="gantt", log_level="INFO", run_id=trajectory_file.stem)

    traj = _load_trajectory_for_vis(trajectory_file)

    # Optional warm-start view: restrict plotting to [start_time, last_time].
    start_time = 0.0
    time_window = None
    try:
        last_time = float(traj.last_snapshot.time)
    except Exception:  # pragma: no cover - defensive fallback
        last_time = 0.0
    if warm and last_time > 0.0:
        ratio = float(warmup_ratio)
        if ratio < 0.0:
            ratio = 0.0
        if ratio >= 1.0:
            ratio = 0.99
        start_time = ratio * last_time
        time_window = (start_time, last_time)

    used_default_out = out_path is None
    if out_path is None:
        final_out = trajectory_file.with_name("gantt.pdf")
    else:
        final_out = Path(out_path)
        if final_out.suffix.lower() != ".pdf":
            final_out = final_out.with_suffix(".pdf")

    if chunk_width is not None and chunk_width > 0.0:
        snap = traj.last_snapshot
        machines = snap.machines

        all_starts = []
        all_ends = []
        for m in machines:
            for seg in m.schedule_segments:
                s = float(seg.start)
                e = float(seg.end)
                if time_window is not None:
                    t0, t1 = time_window
                    if e <= t0 or s >= t1:
                        continue
                    if s < t0:
                        s = t0
                    if e > t1:
                        e = t1
                all_starts.append(s)
                all_ends.append(e)

        if not all_starts or not all_ends:
            raise ValueError("Empty schedule: nothing to plot")

        global_start = min(all_starts)
        global_end = max(all_ends)

        from matplotlib.backends.backend_pdf import PdfPages
        import matplotlib.pyplot as plt

        with PdfPages(final_out) as pdf:
            t0 = global_start
            while t0 < global_end:
                t1 = min(t0 + chunk_width, global_end)

                has_segment = False
                for m in machines:
                    for seg in m.schedule_segments:
                        s = float(seg.start)
                        e = float(seg.end)
                        if time_window is not None:
                            tw0, tw1 = time_window
                            if e <= tw0 or s >= tw1:
                                continue
                            if s < tw0:
                                s = tw0
                            if e > tw1:
                                e = tw1
                        if e > t0 and s < t1:
                            has_segment = True
                            break
                    if has_segment:
                        break
                if not has_segment:
                    t0 = t1
                    continue

                fig, ax = plot_gantt_from_trajectory(
                    traj,
                    out_path=None,
                    time_window=(t0, t1) if time_window is None else (max(t0, time_window[0]), min(t1, time_window[1])),
                    label_mode=label_mode,
                    x_grid_step=x_grid_step,
                )
                pdf.savefig(fig, bbox_inches="tight")
                plt.close(fig)
                t0 = t1

        if used_default_out:
            typer.echo(
                f"Gantt PDF (chunked, chunk={chunk_width}) saved to (default path): {final_out}"
            )
        else:
            typer.echo(f"Gantt PDF (chunked, chunk={chunk_width}) saved to: {final_out}")
    else:
        fig, ax = plot_gantt_from_trajectory(
            traj,
            out_path=final_out,
            time_window=time_window,
            label_mode=label_mode,
            x_grid_step=x_grid_step,
        )
        if used_default_out:
            typer.echo(f"Gantt PDF saved to (default path): {final_out}")
        else:
            typer.echo(f"Gantt PDF saved to: {final_out}")


@app.command(name="job-gantt")
def job_gantt(
    trajectory_file: Annotated[
        Path,
        typer.Option(
            "-t",
            "--trajectory",
            exists=True,
            readable=True,
            help="Path to a JSON file containing a serialized Trajectory.",
        ),
    ],
    out_path: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--out",
            help="Output PDF path (default: <trajectory_dir>/job_gantt.pdf).",
        ),
    ] = None,
    chunk_width: Annotated[
        Optional[float],
        typer.Option(
            "--chunk",
            help=(
                "Optional time window width; if set, split the timeline into windows of this "
                "duration and write a multi-page PDF (one page per window)."
            ),
        ),
    ] = None,
    x_grid_step: Annotated[
        Optional[float],
        typer.Option(
            "--x-grid-step",
            help=(
                "Optional fixed spacing for vertical grid lines on the time axis. "
                "If set to a positive value, major ticks and grid lines are placed "
                "every this many time units."
            ),
        ),
    ] = None,
    legend_loc: Annotated[
        str,
        typer.Option(
            "--legend-loc",
            help=(
                "Matplotlib legend location for the machine-group legend (e.g. 'upper right', "
                "'upper left', 'lower left', 'best')."
            ),
        ),
    ] = "upper right",
    warm: Annotated[
        bool,
        typer.Option(
            "--warm",
            help=(
                "Enable warm-start view: restrict the job Gantt to the trailing time window "
                "of the trajectory (based on --warmup-ratio)."
            ),
        ),
    ] = False,
    warmup_ratio: Annotated[
        float,
        typer.Option(
            "--warmup-ratio",
            help=(
                "For --warm: fraction of the trajectory time to treat as warm-up and "
                "exclude from the plot window (0.0-1.0)."
            ),
        ),
    ] = 0.3,
) -> None:
    """Render a job-centric Gantt chart from a serialized trajectory."""

    init_logging(component="V", command="job-gantt", log_level="INFO", run_id=trajectory_file.stem)

    traj = _load_trajectory_for_vis(trajectory_file)

    # Optional warm-start view: restrict plotting to [start_time, last_time]
    time_window = None
    try:
        last_time = float(traj.last_snapshot.time)
    except Exception:  # pragma: no cover - defensive fallback
        last_time = 0.0
    if warm and last_time > 0.0:
        ratio = float(warmup_ratio)
        if ratio < 0.0:
            ratio = 0.0
        if ratio >= 1.0:
            ratio = 0.99
        start_time = ratio * last_time
        time_window = (start_time, last_time)

    used_default_out = out_path is None
    if out_path is None:
        final_out = trajectory_file.with_name("job_gantt.pdf")
    else:
        final_out = Path(out_path)

    if final_out.suffix.lower() != ".pdf":
        final_out = final_out.with_suffix(".pdf")

    if chunk_width is not None and chunk_width > 0.0:
        snap = traj.last_snapshot
        jobs = snap.jobs

        all_starts = []
        all_ends = []
        for j in jobs:
            for op in j.ops:
                if op.start_time is None or op.end_time is None:
                    continue
                s = float(op.start_time)
                e = float(op.end_time)
                if time_window is not None:
                    t0, t1 = time_window
                    if e <= t0 or s >= t1:
                        continue
                    if s < t0:
                        s = t0
                    if e > t1:
                        e = t1
                all_starts.append(s)
                all_ends.append(e)

        if not all_starts or not all_ends:
            raise ValueError("Empty schedule: nothing to plot")

        from matplotlib.backends.backend_pdf import PdfPages
        import matplotlib.pyplot as plt

        global_start = min(all_starts)
        global_end = max(all_ends)

        with PdfPages(final_out) as pdf:
            t0 = global_start
            while t0 < global_end:
                t1 = min(t0 + chunk_width, global_end)

                # Skip windows with no operations
                has_segment = False
                for j in jobs:
                    for op in j.ops:
                        if op.start_time is None or op.end_time is None:
                            continue
                        s = float(op.start_time)
                        e = float(op.end_time)
                        if time_window is not None:
                            tw0, tw1 = time_window
                            if e <= tw0 or s >= tw1:
                                continue
                            if s < tw0:
                                s = tw0
                            if e > tw1:
                                e = tw1
                        if e > t0 and s < t1:
                            has_segment = True
                            break
                    if has_segment:
                        break
                if not has_segment:
                    t0 = t1
                    continue

                fig, ax = plot_job_gantt_from_trajectory(
                    traj,
                    out_path=None,
                    time_window=(t0, t1) if time_window is None else (max(t0, time_window[0]), min(t1, time_window[1])),
                    x_grid_step=x_grid_step,
                    legend_loc=legend_loc,
                )
                pdf.savefig(fig, bbox_inches="tight")
                plt.close(fig)
                t0 = t1

        if used_default_out:
            typer.echo(
                f"Job Gantt PDF (chunked, chunk={chunk_width}) saved to (default path): {final_out}"
            )
        else:
            typer.echo(f"Job Gantt PDF (chunked, chunk={chunk_width}) saved to: {final_out}")
    else:
        fig, ax = plot_job_gantt_from_trajectory(
            traj,
            out_path=final_out,
            time_window=time_window,
            x_grid_step=x_grid_step,
            legend_loc=legend_loc,
        )
        if used_default_out:
            typer.echo(f"Job Gantt PDF saved to (default path): {final_out}")
        else:
            typer.echo(f"Job Gantt PDF saved to: {final_out}")


@app.command(name="metrics-list")
def metrics_list() -> None:
    """List supported metric names for curves and scalar summaries."""

    init_logging(component="V", command="metrics-list", log_level="INFO", run_id="metrics-list")

    typer.echo("Supported metric-curve names (for V metric-curve -m ...):")
    for name in SUPPORTED_METRIC_OVER_TIME:
        typer.echo(f"- {name}")

    typer.echo("")
    typer.echo("Supported scalar metrics from evaluate_trajectory (E):")
    typer.echo("Static metrics:")
    for name in METRIC_STATIC_KEYS:
        typer.echo(f"- {name}")

    typer.echo("")
    typer.echo("Dynamic metrics:")
    for name in METRIC_DYNAMIC_KEYS:
        typer.echo(f"- {name}")


@app.command(name="metrics-summary")
def metrics_summary(
    trajectory_file: Annotated[
        Path,
        typer.Option(
            "-t",
            "--trajectory",
            exists=True,
            readable=True,
            help="Path to a JSON file containing a serialized Trajectory.",
        ),
    ],
    out_path: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--out",
            help="Output PDF path (default: <trajectory_dir>/metrics_summary.pdf).",
        ),
    ] = None,
    warm: Annotated[
        bool,
        typer.Option(
            "--warm",
            help=(
                "Enable warm-start view: compute scalar metrics and time-series panels "
                "on the trailing window of the trajectory only."
            ),
        ),
    ] = False,
    warmup_ratio: Annotated[
        float,
        typer.Option(
            "--warmup-ratio",
            help=(
                "For --warm: fraction of the trajectory time to treat as warm-up and "
                "exclude from aggregated metrics (0.0-1.0)."
            ),
        ),
    ] = 0.3,
) -> None:
    """Compute all scalar metrics from a trajectory and plot them as a summary bar chart.

    This command loads a serialized Trajectory JSON, runs
    ``dsbx.Eval.Metrics.evaluate_trajectory`` to obtain both
    static and dynamic metrics, and visualizes them in themed subplots
    (e.g. time / tardiness, WIP & queue, utilization / size, ratios,
    and dynamics) using different plot styles. The figure is always
    saved as a PDF; use ``-o`` to override the default output path.
    """

    init_logging(component="V", command="metrics-summary", log_level="INFO", run_id=trajectory_file.stem)

    traj = _load_trajectory_for_vis(trajectory_file)

    # Optional warm-start: restrict metrics to [start_time, last_time].
    start_time = 0.0
    try:
        last_time = float(traj.last_snapshot.time)
    except Exception:  # pragma: no cover - defensive fallback
        last_time = 0.0
    if warm and last_time > 0.0:
        ratio = float(warmup_ratio)
        if ratio < 0.0:
            ratio = 0.0
        if ratio >= 1.0:
            ratio = 0.99
        start_time = ratio * last_time

    used_default_out = out_path is None
    if out_path is None:
        final_out = trajectory_file.with_name("metrics_summary.pdf")
    else:
        final_out = Path(out_path)

    if final_out.suffix.lower() != ".pdf":
        final_out = final_out.with_suffix(".pdf")

    fig, ax = plot_all_metrics_from_trajectory(traj, out_path=final_out, start_time=start_time)
    if used_default_out:
        typer.echo(f"Metrics summary PDF saved to (default path): {final_out}")
    else:
        typer.echo(f"Metrics summary PDF saved to: {final_out}")


@app.command(name="metric-curve")
def metric_curve(
    trajectory_file: Annotated[
        Path,
        typer.Option(
            "-t",
            "--trajectory",
            exists=True,
            readable=True,
            help="Path to a JSON file containing a serialized Trajectory.",
        ),
    ],
    metric: Annotated[
        str,
        typer.Option("-m", "--metric", help="Metric name (e.g. 'wip' or 'utilization_global')."),
    ],
    out_path: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--out",
            help="Output PDF path (default: <trajectory_dir>/metric_<metric>.pdf).",
        ),
    ] = None,
    warm: Annotated[
        bool,
        typer.Option(
            "--warm",
            help=(
                "Enable warm-start view: plot the metric curve only for the "
                "trailing window of the trajectory."
            ),
        ),
    ] = False,
    warmup_ratio: Annotated[
        float,
        typer.Option(
            "--warmup-ratio",
            help=(
                "For --warm: fraction of the trajectory time to treat as warm-up and "
                "exclude from the curve (0.0-1.0)."
            ),
        ),
    ] = 0.3,
) -> None:
    """Plot a metric curve over time based on a trajectory."""

    init_logging(component="V", command="metric-curve", log_level="INFO", run_id=trajectory_file.stem)

    traj = _load_trajectory_for_vis(trajectory_file)

    # Optional warm-start: restrict the curve to [start_time, last_time].
    start_time = 0.0
    try:
        last_time = float(traj.last_snapshot.time)
    except Exception:  # pragma: no cover - defensive fallback
        last_time = 0.0
    if warm and last_time > 0.0:
        ratio = float(warmup_ratio)
        if ratio < 0.0:
            ratio = 0.0
        if ratio >= 1.0:
            ratio = 0.99
        start_time = ratio * last_time

    used_default_out = out_path is None
    if out_path is None:
        safe_metric = metric.replace("/", "_")
        final_out = trajectory_file.with_name(f"metric_{safe_metric}.pdf")
    else:
        final_out = Path(out_path)

    if final_out.suffix.lower() != ".pdf":
        final_out = final_out.with_suffix(".pdf")

    fig, ax = plot_metric_over_time(traj, metric=metric, out_path=final_out, start_time=start_time)
    if used_default_out:
        typer.echo(
            f"Metric curve PDF (metric={metric}) saved to (default path): {final_out}"
        )
    else:
        typer.echo(f"Metric curve PDF (metric={metric}) saved to: {final_out}")


@app.command(name="events-timeline")
def events_timeline(
    events_file: Annotated[
        Path,
        typer.Option(
            "-e",
            "--events",
            exists=True,
            readable=True,
            help="Path to an events.jsonl file generated by the generator.",
        ),
    ],
    out_path: Annotated[
        Optional[Path],
        typer.Option("-o", "--out", help="Output image path (e.g. events.png)."),
    ] = None,
    warm: Annotated[
        bool,
        typer.Option(
            "--warm",
            help=(
                "Enable warm-start view: restrict the events timeline to the time window "
                "after an initial warm-up period (based on --warmup-ratio)."
            ),
        ),
    ] = False,
    warmup_ratio: Annotated[
        float,
        typer.Option(
            "--warmup-ratio",
            help=(
                "For --warm: fraction of the events time span to treat as warm-up "
                "and exclude from the timeline (0.0-1.0)."
            ),
        ),
    ] = 0.3,
) -> None:
    """Plot an events timeline from an events.jsonl file.

    By default (without ``-o``), this opens an interactive line chart where the
    x-axis is time and the y-axis is the number of events. Hovering over a
    point shows the event types and counts at that time. If ``-o`` is provided,
    a static image is written to disk without interactivity.
    """

    init_logging(component="V", command="events-timeline", log_level="INFO", run_id=events_file.stem)

    # Optional warm-start: restrict to [start_time, last_event_time].
    start_time = 0.0
    if warm:
        try:
            # Lightweight scan to determine max event time
            import json as _json

            max_t = None
            with events_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = _json.loads(line)
                    except Exception:
                        continue
                    t = float(ev.get("time", 0.0))
                    if (max_t is None) or (t > max_t):
                        max_t = t
            if max_t is not None and max_t > 0.0:
                ratio = float(warmup_ratio)
                if ratio < 0.0:
                    ratio = 0.0
                if ratio >= 1.0:
                    ratio = 0.99
                start_time = ratio * max_t
        except Exception:  # pragma: no cover - defensive fallback
            start_time = 0.0

    fig, ax = plot_events_timeline_from_jsonl(events_file, out_path=out_path, start_time=start_time)
    if out_path is None:
        import matplotlib.pyplot as plt

        plt.show()


@app.command(name="gantt-inspect")
def gantt_inspect(
    trajectory_file: Annotated[
        Path,
        typer.Option(
            "-t",
            "--trajectory",
            exists=True,
            readable=True,
            help="Path to a JSON file containing a serialized Trajectory.",
        ),
    ],
    static_jobs_file: Annotated[
        Optional[Path],
        typer.Option(
            "-s",
            "--static",
            exists=True,
            readable=True,
            help="Optional path to static_jobs.json for the same instance.",
        ),
    ] = None,
    events_file: Annotated[
        Optional[Path],
        typer.Option(
            "-e",
            "--events",
            exists=True,
            readable=True,
            help="Optional path to events.jsonl for the same instance.",
        ),
    ] = None,
    warm: Annotated[
        bool,
        typer.Option(
            "--warm",
            help=(
                "Enable warm-start view: restrict the interactive Gantt to the "
                "trailing time window of the trajectory (based on --warmup-ratio)."
            ),
        ),
    ] = False,
    warmup_ratio: Annotated[
        float,
        typer.Option(
            "--warmup-ratio",
            help=(
                "For --warm: fraction of the trajectory time to treat as warm-up and "
                "exclude from the interactive view (0.0-1.0)."
            ),
        ),
    ] = 0.3,
) -> None:
    """Interactively inspect a Trajectory with optional static_jobs.json and events.jsonl.

    Hovering over a processing segment in the Gantt chart will show, in a
    side text panel:
    - Realized start/end/duration derived from the Trajectory's final snapshot;
    - Planned processing time from ``static_jobs.json`` (if provided);
    - Nearby events for the same job/machine from ``events.jsonl`` (if provided).
    """

    init_logging(component="V", command="gantt-inspect", log_level="INFO", run_id=trajectory_file.stem)

    traj = _load_trajectory_for_vis(trajectory_file)

    # Optional warm-start view: restrict interactive Gantt to [start_time, last_time].
    time_window = None
    try:
        last_time = float(traj.last_snapshot.time)
    except Exception:  # pragma: no cover - defensive fallback
        last_time = 0.0
    if warm and last_time > 0.0:
        ratio = float(warmup_ratio)
        if ratio < 0.0:
            ratio = 0.0
        if ratio >= 1.0:
            ratio = 0.99
        start_time = ratio * last_time
        time_window = (start_time, last_time)

    fig, ax_gantt, ax_info = interactive_gantt_from_trajectory(
        traj,
        static_jobs_path=static_jobs_file,
        events_path=events_file,
        time_window=time_window,
    )

    import matplotlib.pyplot as plt

    plt.show()


if __name__ == "__main__":  # pragma: no cover
    app()
