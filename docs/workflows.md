# Workflows

This page gives end-to-end command sequences for common DynaSchedBench tasks.

## Single-Instance Experiment

Generate one instance:

```bash
dsbx-gen gen \
  -i docs/examples/minimal_input_model.json \
  -o runs/minimal \
  --max-calib-steps 5
```

Validate the event stream:

```bash
dsbx-eval check-events \
  -c runs/minimal/input_model.json \
  -e runs/minimal/events.jsonl \
  --strict-events
```

Run a priority-dispatching baseline:

```bash
dsbx-agent run \
  -d runs/minimal \
  -o runs/minimal/pdr_spt_lit \
  -a pdr:SPT:LIT \
  --random-seed 42
```

Recompute metrics:

```bash
dsbx-eval from-trajectory \
  -t runs/minimal/pdr_spt_lit/trajectory_light.jsonl \
  -o runs/minimal/pdr_spt_lit/metrics_recomputed.json
```

Visualize:

```bash
dsbx-vis gantt \
  -t runs/minimal/pdr_spt_lit/trajectory_light.jsonl \
  -o runs/minimal/pdr_spt_lit/gantt.pdf

dsbx-vis metrics-summary \
  -t runs/minimal/pdr_spt_lit/trajectory_light.jsonl \
  -o runs/minimal/pdr_spt_lit/metrics_summary.pdf
```

## Compare Several Agents

Run several agents on the same generated instance:

```bash
dsbx-agent run -d runs/minimal -o runs/minimal/spt -a spt
dsbx-agent run -d runs/minimal -o runs/minimal/random -a random --random-seed 7
dsbx-agent run -d runs/minimal -o runs/minimal/pdr_fifo_lit -a pdr:FIFO:LIT
dsbx-agent run -d runs/minimal -o runs/minimal/ga -a ga --ga-population-size 16 --ga-generations 8
```

Then compare the resulting `metrics.json` files in your analysis script. A
minimal pattern is:

```python
import json
from pathlib import Path

runs = ["spt", "random", "pdr_fifo_lit", "ga"]
for name in runs:
    metrics_path = Path("runs/minimal") / name / "metrics.json"
    metrics = json.loads(metrics_path.read_text())
    print(name, metrics.get("mean_flow_time"), metrics.get("total_tardiness"))
```

## Batch Generation

Batch mode expands list-valued target fields such as `rho_global`, `ddt`,
`scv_a`, `scv_p`, and `disturbance`.

```json
{
  "targets": {
    "rho_global": [0.60, 0.75, 0.90],
    "ddt": [1.2, 1.5, 2.0],
    "scv_a": [0.5, 1.0, 2.0],
    "scv_p": [0.5, 1.0, 2.0],
    "disturbance": [0.0, 0.05, 0.10]
  }
}
```

Every list must have the same length. Run:

```bash
dsbx-gen gen-batch \
  -i path/to/batch_input_model.json \
  -o runs/batch \
  --max-calib-steps 25
```

Batch output includes one directory per generated instance, a `summary.csv`,
and an `instance_space.png` plot.

## MOO And Hybrid Calibration

Sequential calibration is fast and appropriate for smoke tests. For final
benchmark construction, use the mode declared in the input model or select a
mode explicitly:

```bash
dsbx-gen gen -i path/to/input.json -o runs/moo --use-moo
dsbx-gen gen -i path/to/input.json -o runs/hybrid --use-hybrid
dsbx-gen gen -i path/to/input.json -o runs/auto --auto
```

MOO and hybrid runs may write `pareto_info.json`. Inspect and replay a solution:

```bash
dsbx-gen replay \
  -i path/to/input.json \
  -p runs/hybrid/pareto_info.json \
  --list

dsbx-gen replay \
  -i path/to/input.json \
  -p runs/hybrid/pareto_info.json \
  --solution-id 0 \
  -o runs/replayed_solution_0
```

Replay does not rerun the full search. It regenerates events from a selected
Pareto decision vector.

## Warm-Start Evaluation

For warm-start scenarios, either set `evaluation.mode` in the input model or
use warm-window analysis after a rollout:

```bash
dsbx-eval from-trajectory \
  -t runs/minimal/spt/trajectory_light.jsonl \
  --warm \
  --warmup-ratio 0.3

dsbx-vis gantt \
  -t runs/minimal/spt/trajectory_light.jsonl \
  --warm \
  --warmup-ratio 0.3 \
  -o runs/minimal/spt/gantt_warm.pdf
```

The command computes or plots only the trailing portion after the warm-up
window.

## Simulator Snapshot Inspection

Use `dsbx-sim snapshot` to inspect state produced by the input model's event
stream without running a scheduling algorithm:

```bash
dsbx-sim snapshot \
  -c docs/examples/minimal_input_model.json \
  -t 50 \
  -o runs/minimal_snapshot_t50.json
```

This is useful when debugging arrivals, priority changes, maintenance, or other
dynamic events before introducing an agent.
