# Evaluation

DynaSchedBench evaluation is trajectory-based. Generate an instance, run an
agent, then evaluate the resulting trajectory.

## Trajectory Files

Agent runs can write two trajectory formats:

- `trajectory.json`: a full serialized trajectory. This is convenient for small
  examples and debugging.
- `trajectory_light.jsonl`: a streaming summary trajectory. This is the better
  default for larger runs because it avoids keeping every full snapshot in
  memory.

Most evaluation and visualization commands accept both formats.

## Recompute Metrics

```bash
dsbx-eval from-trajectory \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -o runs/minimal/spt/metrics_recomputed.json
```

Options:

- `--show-violations / --hide-violations`: print hard-constraint violations.
- `--fail-on-violation`: use a non-zero exit code if violations exist.
- `--warm`: ignore an initial warm-up window for time-series metrics.
- `--warmup-ratio`: warm-up window fraction, default `0.3`.

## Metric Families

Static scalar metrics include:

- flow and completion: `makespan`, `total_flow_time`, `mean_flow_time`,
  `throughput`;
- due-date performance: `total_tardiness`, `mean_tardiness`,
  `num_tardy_jobs`, `total_weighted_tardiness`;
- WIP and queues: `max_wip`, `mean_wip`, `max_queue_length_total`,
  `mean_queue_length_total`;
- completion ratios: `num_jobs_total`, `num_jobs_completed`,
  `job_completion_ratio`, `job_cancellation_ratio`;
- utilization: `avg_utilization_global`, `max_utilization_global`,
  `min_utilization_global`, `utilization_cv_global`;
- job structure: `mean_num_ops_per_job`, `mean_work_content_per_job`.

Dynamic metrics include:

- `avg_changed_ops_ratio`
- `avg_start_time_shift`
- `max_start_time_shift`
- `reschedule_steps`
- `reschedule_frequency`
- `schedule_edit_intensity`

Use `dsbx-vis metrics-list` to print the metric names supported by curve plots
and scalar summaries.

## Validate Generated Events

```bash
dsbx-eval check-events \
  -c runs/minimal/input_model.json \
  -e runs/minimal/events.jsonl \
  --strict-events \
  --fail-on-error
```

Recommended usage:

- Run without `--strict-events` for quick feasibility checks.
- Add `--strict-events` before launching large experiments.
- Add `--fail-on-error` in CI or benchmark generation scripts.
- Use `--strict-max-messages` to limit long error reports.

## Check Schedule Feasibility

```bash
dsbx-eval check-schedule \
  -t runs/minimal/spt/trajectory_light.jsonl \
  --show-violations \
  --fail-on-violation
```

This checks hard constraints on the produced schedule. It is useful after
implementing a new agent or changing environment logic.

## Warm-Window Evaluation

Warm-window evaluation ignores early transient behavior:

```bash
dsbx-eval from-trajectory \
  -t runs/minimal/spt/trajectory_light.jsonl \
  --warm \
  --warmup-ratio 0.3
```

With `--warmup-ratio 0.3`, time-series aggregates begin at 30 percent of the
final trajectory time.

## Debug LLM Episodes

LLM debug commands consolidate trajectory, event, and log information into
compact files for per-decision inspection.

```bash
dsbx-eval debug-llmscheduler \
  -t runs/llm_scheduler/trajectory_light.jsonl \
  -e runs/minimal/events.jsonl \
  -l runs/llm_scheduler/main.log \
  -o runs/llm_scheduler/debug.jsonl
```

```bash
dsbx-eval debug-llmcoder \
  -t runs/llm_coder/trajectory_light.jsonl \
  -e runs/minimal/events.jsonl \
  --coder-trajectory runs/llm_coder/coder_trajectory.jsonl \
  -l runs/llm_coder/main.log \
  -o runs/llm_coder/debug.json
```

Use these files to inspect prompts, selected actions, candidate rules, and
event context around difficult decisions.
