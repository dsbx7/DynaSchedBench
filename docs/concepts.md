# Concepts

DynaSchedBench separates dynamic scheduling experiments into a few explicit
objects. Understanding these objects makes the command-line tools much easier
to use.

## Input Model

An `InputModel` JSON file describes the scheduling problem before any random
events are generated. It contains:

- `plant`: machines, machine groups, job families, and routes.
- `scale`: horizon, optional fixed job count, and validation-only scale hints.
- `dynamics`: arrival-rate pattern over time.
- `targets`: desired utilization, due-date tightness, arrival variability,
  processing-time variability, disturbance level, and load balance.
- `dynamic_scenarios`: probabilities for cancellations, priority changes,
  emergency jobs, processing-time changes, maintenance, batches, route changes,
  and due-date changes.
- `calibration`: how the generator should tune parameters to match targets.
- `outputs`: default output directory when `dsbx-gen gen` is not given `-o`.

The schema is defined by `dsbx.Gen.models.inputs.InputModel`.

## Generated Instance

`dsbx-gen gen` transforms an input model into a concrete dynamic scheduling
instance. A generated instance directory is the handoff point between the
generator, simulator, agents, evaluation, and visualization.

Typical files are:

- `input_model.json`: normalized model used by the generator.
- `events.jsonl`: event stream, one JSON event per line.
- `static_jobs.json`: generated jobs, families, routes, and due dates.
- `static_machines.json`: generated machines and groups.
- `final_metrics.json`: realized instance-level metrics.
- `pareto_info.json`: Pareto-front metadata for MOO or hybrid calibration.
- `report.md`: readable generation report.

## Event Stream

The simulator consumes `events.jsonl`. Events represent external dynamics such
as arrivals, cancellations, priority changes, machine breakdowns, maintenance,
processing-time changes, route changes, rework, and due-date changes. Events
are applied over simulated time. Scheduling actions are not stored in this file;
they are produced by agents during rollout.

## Simulator Snapshot

A `Snapshot` is the simulator state at a decision time. It includes current
time, machine states, queues, jobs, operation states, and static context. The
snapshot is used by:

- `dsbx.Env.DynaSchedEnv` to build observations and legal actions.
- Agents to choose scheduling actions.
- Evaluation to compute metrics.
- Visualization to draw final schedules and time-series diagnostics.

## Environment And Agent

`DynaSchedEnv` wraps the simulator as a single-agent environment. At each
decision point:

1. The environment returns an observation.
2. The agent reads legal actions.
3. The agent selects one action or lets time advance when no action is legal.
4. The environment applies the action and records a trajectory step.

Actions use job and machine information, commonly:

```json
{
  "job_id": "job_0001",
  "machine_group": "cutting",
  "machine_id": "cut-1"
}
```

`machine_id` is optional for agents that select only a machine group; the
environment can resolve candidates when possible.

## Trajectory

A trajectory records an agent rollout. DynaSchedBench supports both full JSON
trajectories and streaming JSONL summaries for large runs.

Use trajectories for:

- recomputing metrics with `dsbx-eval from-trajectory`;
- checking hard scheduling constraints with `dsbx-eval check-schedule`;
- plotting Gantt charts and metric curves with `dsbx-vis`;
- debugging LLM decisions with the specialized debug commands.

## Cold-Start And Warm-Start Modes

Cold-start experiments begin with an initially empty system and arrivals over
time. Warm-start experiments initialize work in process before the first
decision. The input model controls this through `evaluation.mode` and
`evaluation.initial_wip_method`. Evaluation and visualization commands also
provide `--warm` and `--warmup-ratio` options to ignore an initial warm-up
window when computing or plotting selected metrics.
