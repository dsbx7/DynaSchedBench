# Input Model And Instance Format

This page documents the JSON files users interact with most often:
configuration files passed to `dsbx-gen gen`, and artifacts emitted by the
generator.

## Minimal Input Model

The tutorial model is stored at
{download}`docs/examples/minimal_input_model.json <examples/minimal_input_model.json>`.

```{literalinclude} examples/minimal_input_model.json
:language: json
```

Run it with:

```bash
dsbx-gen gen -i docs/examples/minimal_input_model.json -o runs/minimal
```

## Top-Level Sections

### `meta`

General reproducibility metadata:

- `seed`: random seed used by generation.
- `grid`: report and segment time grid.
- `version`: schema version. The current layered schema uses `2.0`.

### `plant`

Static production system definition:

- `machines`: each machine has a unique `id`, a `group`, and a positive
  `speed` multiplier.
- `process_templates`: each job family has a `family` name and a route.
- `job_mix_weights`: optional family probabilities in `process_templates`
  order. If omitted, families are sampled uniformly.

Every route step references a machine group defined in `machines`.

### `scale`

Problem size and horizon:

- `horizon`: simulation time horizon.
- `jobs_total`: optional fixed number of generated jobs. When present, it
  overrides derivation from target utilization.
- `num_machines` and `num_job_families`: optional validation hints.

### `dynamics`

Arrival-rate pattern:

- `arrival_pattern`: `constant`, `periodic`, or `linear_trend`.
- `arrival_amplitude`: fluctuation strength.
- `arrival_period`: period for `periodic`; defaults to `horizon / 3` when
  omitted.

### `targets`

Target characteristics to calibrate:

- `rho_global`: global utilization target.
- `rho_bottleneck`: optional time-windowed group utilization targets.
- `load_cv`: optional load imbalance target across machine groups.
- `ddt`: due-date tightness factor.
- `scv_a`: squared coefficient of variation for arrivals.
- `scv_p`: squared coefficient of variation for processing times.
- `disturbance`: disturbance level, such as downtime share.
- `availability`: alternative to `disturbance`; do not set both.

`rho_global`, `ddt`, `scv_a`, `scv_p`, and `disturbance` can also be lists for
batch generation. When lists are used, all list lengths must match.

### `dynamic_scenarios`

Probabilities and parameters for dynamic events:

- `cancellation_rate`
- `priority_change_rate`
- `emergency_job_ratio`
- `rework_probability`
- `ptime_change_rate`
- `pm_interval`
- `batch_arrival_probability`
- `route_change_probability`
- `due_date_change_probability`

Lower priority numbers represent higher urgency. For emergency jobs, use an
`emergency_priority` value less than or equal to `normal_priority_change_value`.

### `evaluation`

Experiment initialization:

- `mode`: `cold_start` or `warm_start`.
- `initial_wip_method`: `auto` or `manual`.
- `n0_initial`: manual initial WIP count for warm-start experiments.

### `calibration`

Generation strategy and budget:

- `mode`: `sequential`, `moo`, `hybrid`, or `auto`.
- `max_steps`: sequential calibration step budget.
- `moo_population_size`, `moo_n_generations`: MOO budget.
- `hybrid_population_size`, `hybrid_n_generations`: hybrid budget.
- `seq_tol_*`: optional per-metric sequential tolerances.

For quick smoke tests, use a small `max_steps`. For final benchmark generation,
use larger budgets and keep the full `final_metrics.json` and `report.md`.

### `outputs`

Default output location. `dsbx-gen gen -o ...` overrides this field.

## Generated Files

After generation, downstream commands expect a directory with these files:

| File | Purpose |
| --- | --- |
| `input_model.json` | Normalized model used for this generated instance. |
| `events.jsonl` | Dynamic event stream. |
| `static_jobs.json` | Concrete jobs, routes, release times, and due dates. |
| `static_machines.json` | Concrete machines and groups. |
| `final_metrics.json` | Realized target metrics and calibration summary. |
| `report.md` | Human-readable generation report. |
| `pareto_info.json` | MOO/hybrid Pareto metadata, when available. |

Use the generated directory with `dsbx-agent run -d`, not the original JSON
configuration file.

## Validation

Validate a generated event stream:

```bash
dsbx-eval check-events \
  -c runs/minimal/input_model.json \
  -e runs/minimal/events.jsonl \
  --strict-events \
  --fail-on-error
```

For large benchmark collections, run this validation before launching expensive
agent sweeps.
