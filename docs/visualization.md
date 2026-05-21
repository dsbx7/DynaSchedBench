# Visualization

DynaSchedBench visualization commands produce schedule plots, metric summaries,
metric curves, event timelines, and an interactive Gantt inspector.

## Machine Gantt

```bash
dsbx-vis gantt \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -o runs/minimal/spt/gantt.pdf
```

Useful options:

- `--label op`: show operation labels such as `O_{i,j}`.
- `--label job_id`: show raw job IDs.
- `--label job_op`: show job ID plus operation index.
- `--chunk 100`: split long schedules into a multi-page PDF.
- `--x-grid-step 20`: fix vertical grid spacing.
- `--warm --warmup-ratio 0.3`: plot only the trailing warm-window.

## Job-Centric Gantt

```bash
dsbx-vis job-gantt \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -o runs/minimal/spt/job_gantt.pdf
```

This view places jobs on the y-axis and colors operations by machine group. It
is useful for inspecting flow time, waiting time, and route structure.

## Metrics Summary

```bash
dsbx-vis metrics-summary \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -o runs/minimal/spt/metrics_summary.pdf
```

This recomputes scalar metrics and plots grouped diagnostic panels.

## Metric Curve

List supported curve names:

```bash
dsbx-vis metrics-list
```

Plot one metric over time:

```bash
dsbx-vis metric-curve \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -m wip \
  -o runs/minimal/spt/wip.pdf
```

Frequently useful curve names:

- `wip`
- `wip_waiting`
- `wip_processing`
- `utilization_global`
- `queue_length_total`
- `jobs_completed`
- `stability_changed_ops_ratio`
- `reschedules_cumulative`

## Event Timeline

```bash
dsbx-vis events-timeline \
  -e runs/minimal/events.jsonl \
  -o runs/minimal/events_timeline.png
```

Without `-o`, this command opens an interactive matplotlib window. In headless
or server environments, always pass `-o`.

## Interactive Gantt Inspector

```bash
dsbx-vis gantt-inspect \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -s runs/minimal/static_jobs.json \
  -e runs/minimal/events.jsonl
```

The inspector shows operation timing, planned processing times, and nearby
events for the same job or machine when you hover over a segment.

## Practical Tips

- Use `trajectory_light.jsonl` for large runs.
- Use `--chunk` when the Gantt chart is too dense for one page.
- Use `--warm` when comparing warm-start or long-horizon experiments.
- Save plots under the agent output directory so metrics, trajectories, and
  figures stay together.
