# Benchmarks

DynaSchedBench benchmark data is organized around generated instances and agent
trajectories. A generated instance is reusable: many agents can run on the same
instance directory, producing separate trajectories and metrics.

## Generated Instance Directory

A generated instance typically contains:

- `input_model.json`: the normalized generation configuration.
- `events.jsonl`: the dynamic event stream consumed by the simulator.
- `static_jobs.json`: job metadata extracted from the event stream.
- `static_machines.json`: machine and machine-group metadata.
- `final_metrics.json`: generator-side metrics and calibration diagnostics.
- `pareto_info.json`: Pareto-front metadata for MOO or hybrid calibration.
- `report.md`: a human-readable generation report.

These files are produced by `dsbx-gen gen` or `dsbx-gen gen-batch`.

## Agent Run Directory

An agent run typically contains:

- `trajectory.json` or `trajectory_light.jsonl`
- `metrics.json`
- generated plots such as `gantt.pdf`
- agent-specific logs

These files are produced by `dsbx-agent run`.

## Repository Data Layout

The repository may include benchmark collections under `data/`, such as
generated grids, GEN-Bench style files, JMS-Bench style files, or MK-Bench style
files. Treat each collection as immutable experiment input once published.

Recommended practice:

- Keep input models and generated instance artifacts together.
- Write each agent's output under a separate subdirectory.
- Store metrics and plots next to the trajectory that produced them.
- Record package version, Git commit, seed, and command line in experiment logs.

## Reproducibility Checklist

For a benchmark result to be reproducible, keep:

- the original input-model JSON;
- the generated instance directory;
- the exact agent command and random seed;
- the trajectory file;
- `metrics.json` or recomputation instructions;
- any LLM provider/model settings for LLM agents;
- the DynaSchedBench package version.

For published comparisons, prefer rerunning metrics from trajectories:

```bash
dsbx-eval from-trajectory \
  -t path/to/agent_run/trajectory_light.jsonl \
  -o path/to/agent_run/metrics_recomputed.json \
  --fail-on-violation
```

## Scaling Experiments

For large sweeps:

1. Generate and validate all instances.
2. Run agents with `trajectory_light.jsonl` enabled.
3. Recompute metrics in a separate evaluation pass.
4. Generate only the plots needed for the paper or artifact review.
5. Keep `runs/` or experiment output outside the package wheel.

Heavy research agents, third-party training code, pretrained policies, and
generated training artifacts are kept outside the PyPI wheel so `pip install
dsbx` remains lightweight.
