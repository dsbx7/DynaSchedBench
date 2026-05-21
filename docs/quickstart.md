# Quickstart

This page walks through the shortest useful DynaSchedBench workflow:
install the package, generate one dynamic scheduling instance, run a baseline
agent, evaluate the trajectory, and create plots.

## 1. Install DynaSchedBench

Install the public package from PyPI:

```bash
pip install dsbx
```

For development from a cloned repository:

```bash
python -m pip install -e .[dev,docs]
```

Confirm that the five release commands are available:

```bash
dsbx-gen --help
dsbx-agent --help
dsbx-eval --help
dsbx-vis --help
dsbx-sim --help
```

## 2. Prepare an input model

DynaSchedBench generation starts from an `InputModel` JSON file. The repository
contains a compact tutorial example at
{download}`docs/examples/minimal_input_model.json <examples/minimal_input_model.json>`.

If you are reading this page on Read the Docs, create a local file named
`examples/minimal_input_model.json` and copy the JSON from
{doc}`instance-format`.

## 3. Generate an instance

```bash
dsbx-gen gen \
  -i docs/examples/minimal_input_model.json \
  -o runs/minimal \
  --max-calib-steps 5
```

The generated directory is the main artifact consumed by later commands. It
contains:

- `input_model.json`: normalized configuration used for the run.
- `events.jsonl`: dynamic event stream.
- `static_jobs.json`: generated jobs and routes.
- `static_machines.json`: generated machine definitions.
- `final_metrics.json`: instance-level target/realized metrics.
- `report.md`: human-readable generation report.

## 4. Validate the event stream

```bash
dsbx-eval check-events \
  -c runs/minimal/input_model.json \
  -e runs/minimal/events.jsonl \
  --strict-events
```

Use this before running many agents. It catches malformed event streams,
undefined job references, invalid dynamic-event ordering, and target-feasibility
issues.

## 5. Run a baseline agent

```bash
dsbx-agent run \
  -d runs/minimal \
  -o runs/minimal/spt \
  -a spt \
  --random-seed 42
```

The `-d/--dir` argument points to the generated instance directory, not the
original configuration file. Common alternatives are:

```bash
dsbx-agent run -d runs/minimal -o runs/minimal/random -a random --random-seed 42
dsbx-agent run -d runs/minimal -o runs/minimal/pdr_spt_lit -a pdr:SPT:LIT
dsbx-agent list-agents
```

Agent output usually includes:

- `trajectory.json`: full in-memory trajectory when enabled.
- `trajectory_light.jsonl`: streaming trajectory summary for large runs.
- `metrics.json`: scalar metrics from `evaluate_trajectory`.
- `gantt.pdf`: default schedule visualization.

## 6. Evaluate and visualize

```bash
dsbx-eval from-trajectory \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -o runs/minimal/spt/metrics_recomputed.json
```

```bash
dsbx-vis gantt \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -o runs/minimal/spt/gantt.pdf

dsbx-vis metric-curve \
  -t runs/minimal/spt/trajectory_light.jsonl \
  -m wip \
  -o runs/minimal/spt/wip.pdf

dsbx-vis events-timeline \
  -e runs/minimal/events.jsonl \
  -o runs/minimal/events_timeline.png
```

## 7. Use the Python API

The same scheduling loop can be embedded in experiments:

```python
from pathlib import Path

from dsbx.Agents import SPTAgent
from dsbx.Env import DynaSchedEnv
from dsbx.Eval.Metrics import evaluate_trajectory
from dsbx.Gen import load_input_model

model = load_input_model(Path("docs/examples/minimal_input_model.json"))
env = DynaSchedEnv(model)
agent = SPTAgent()

obs = env.reset()
done = False

while not done:
    legal_actions = env.legal_actions()
    if not legal_actions:
        obs = env.advance_if_idle()
        continue

    action = agent.act(obs, legal_actions, env)
    obs, reward, done, info = env.step(action)

metrics = evaluate_trajectory(env.get_trajectory())
print(metrics)
```

For a deeper walkthrough, continue with {doc}`workflows`.
