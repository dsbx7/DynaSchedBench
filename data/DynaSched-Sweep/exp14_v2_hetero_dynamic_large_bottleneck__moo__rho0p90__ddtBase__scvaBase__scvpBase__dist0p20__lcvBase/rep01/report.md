
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `364c82e338e8`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T17:52:24.012560+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.864 | 4.02 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.581 | 12.16 |

| scv_a | 2.000 | 2.496 | 24.78 |

| scv_p | 2.000 | 4.079 | 103.93 |

| disturbance | 0.200 | 0.203 | 1.64 |

| load_cv | 0.200 | 0.321 | 60.25 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 210.067 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.179 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `28.5` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.861 |
| **P (Period/Due Date)** | 0.054 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.900 suggests horizon≈2941.176 (was 4411.765). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3014,
  "disturbances": 3014,
  "dynamic_world": 3014,
  "ptimes": 3014,
  "routing": 3014
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)