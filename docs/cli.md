# Command-Line Interface

DynaSchedBench exposes five release commands. The PyPI project name is `dsbx`,
the Python import name is `dsbx`, and command names always use the
`dsbx-` prefix.

| Command | Purpose |
| --- | --- |
| `dsbx-gen` | Generate and inspect dynamic scheduling instances. |
| `dsbx-agent` | Run agents on generated instances. |
| `dsbx-eval` | Evaluate trajectories and validate instances. |
| `dsbx-vis` | Plot schedules, metrics, and event timelines. |
| `dsbx-sim` | Export simulator snapshots without running an agent. |

## `dsbx-gen`

Use `dsbx-gen` to create concrete dynamic scheduling instances from input-model
JSON files.

### Generate One Instance

```bash
dsbx-gen gen \
  -i docs/examples/minimal_input_model.json \
  -o runs/minimal \
  --max-calib-steps 5
```

Key options:

- `-i, --input`: required input-model JSON file.
- `-o, --output`: output directory. If omitted, `outputs.path` from the model
  may be used.
- `--max-calib-steps`: sequential calibration budget.
- `--use-moo`: use NSGA-II MOO calibration.
- `--use-hybrid`: use hybrid sequential plus MOO calibration.
- `--auto`: let the calibration advisor choose mode and step budget.
- `--compare-to`: compare two `final_metrics.json` files.
- `--log-level`: `DEBUG`, `INFO`, `WARNING`, or `ERROR`.

### Generate A Batch

```bash
dsbx-gen gen-batch \
  -i path/to/batch_input_model.json \
  -o runs/batch \
  --max-calib-steps 25
```

Batch generation expands list-valued target fields. It writes one instance
directory per expanded configuration plus `summary.csv` and `instance_space.png`.

### Replay A Pareto Solution

```bash
dsbx-gen replay \
  -i path/to/input_model.json \
  -p runs/hybrid/pareto_info.json \
  --list

dsbx-gen replay \
  -i path/to/input_model.json \
  -p runs/hybrid/pareto_info.json \
  --solution-id 0 \
  -o runs/replayed_solution_0
```

Replay regenerates events from a saved Pareto decision vector without rerunning
the full MOO or hybrid search.

## `dsbx-agent`

Use `dsbx-agent` to run schedulers on generated instances. The input is a
generated instance directory, not the original input-model JSON file.

```bash
dsbx-agent run \
  -d runs/minimal \
  -o runs/minimal/spt \
  -a spt \
  --random-seed 42
```

Common options:

- `-d, --dir`: generated instance directory from `dsbx-gen gen`.
- `-o, --output`: output directory for trajectories, metrics, and plots.
- `-a, --agent`: agent name such as `spt`, `random`, or `pdr:SPT:LIT`.
- `--save-trajectory / --no-save-trajectory`: write `trajectory.json`.
- `--save-trajectory-light / --no-save-trajectory-light`: stream
  `trajectory_light.jsonl`.
- `--max-steps`: safety bound on decision steps.
- `--random-seed`: seed for stochastic agents and tie-breaking.

Discover agents:

```bash
dsbx-agent list-agents
dsbx-agent agent-help pdr
dsbx-agent agent-help ga
dsbx-agent agent-help llm-scheduler
```

Typical output files:

- `trajectory.json`: full trajectory when enabled.
- `trajectory_light.jsonl`: streaming summary trajectory.
- `metrics.json`: scalar metrics.
- `gantt.pdf`: default Gantt chart.
- agent-specific logs and debug artifacts.

## `dsbx-eval`

Use `dsbx-eval` for trajectory metrics, event validation, schedule feasibility,
and LLM debug views.

### Evaluate A Trajectory

```bash
dsbx-eval from-trajectory \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -o runs/minimal/spt/metrics_recomputed.json
```

Useful options:

- `--show-violations / --hide-violations`: print hard-constraint violations.
- `--fail-on-violation`: exit non-zero when violations are found.
- `--warm`: ignore an initial warm-up period for time-series metrics.
- `--warmup-ratio`: warm-up fraction, default `0.3`.

### Validate Events

```bash
dsbx-eval check-events \
  -c runs/minimal/input_model.json \
  -e runs/minimal/events.jsonl \
  --strict-events \
  --fail-on-error
```

This checks input-model consistency, event references, ordering, and optional
strict event constraints.

### Check A Schedule

```bash
dsbx-eval check-schedule \
  -t runs/minimal/spt/trajectory_light.jsonl \
  --fail-on-violation
```

This command checks hard scheduling constraints on an agent rollout.

### Debug LLM Runs

```bash
dsbx-eval debug-llmscheduler \
  -t runs/llm/trajectory_light.jsonl \
  -e runs/minimal/events.jsonl \
  -l runs/llm/main.log \
  -o runs/llm/llmscheduler_debug.jsonl
```

```bash
dsbx-eval debug-llmcoder \
  -t runs/llmcoder/trajectory_light.jsonl \
  -e runs/minimal/events.jsonl \
  --coder-trajectory runs/llmcoder/coder_trajectory.jsonl \
  -l runs/llmcoder/main.log \
  -o runs/llmcoder/llmcoder_debug.json
```

## `dsbx-vis`

Use `dsbx-vis` to turn event streams and trajectories into diagnostics.

```bash
dsbx-vis gantt \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -o runs/minimal/spt/gantt.pdf

dsbx-vis job-gantt \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -o runs/minimal/spt/job_gantt.pdf

dsbx-vis metrics-summary \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -o runs/minimal/spt/metrics_summary.pdf

dsbx-vis metric-curve \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -m wip \
  -o runs/minimal/spt/wip.pdf

dsbx-vis events-timeline \
  -e runs/minimal/events.jsonl \
  -o runs/minimal/events_timeline.png
```

List supported time-series metric names:

```bash
dsbx-vis metrics-list
```

Most trajectory-based plotting commands support `--warm` and `--warmup-ratio`.
Gantt commands also support chunked PDFs:

```bash
dsbx-vis gantt \
  -t runs/minimal/spt/trajectory_light.jsonl \
  --chunk 100 \
  -o runs/minimal/spt/gantt_chunked.pdf
```

For interactive inspection:

```bash
dsbx-vis gantt-inspect \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -s runs/minimal/static_jobs.json \
  -e runs/minimal/events.jsonl
```

## `dsbx-sim`

`dsbx-sim` exports simulator state snapshots from an input model. It applies
events up to the requested time but does not run a scheduling algorithm.

```bash
dsbx-sim snapshot \
  -c docs/examples/minimal_input_model.json \
  -t 50 \
  -o runs/minimal_snapshot_t50.json
```

Options:

- `-c, --config`: required input-model JSON file.
- `-t, --time`: decision time to inspect.
- `-o, --out`: optional output JSON path. Without `-o`, the snapshot is printed
  to stdout.
