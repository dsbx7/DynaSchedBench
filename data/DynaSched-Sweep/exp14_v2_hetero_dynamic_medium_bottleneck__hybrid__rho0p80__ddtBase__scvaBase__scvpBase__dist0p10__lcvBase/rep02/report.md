
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `f9d6830d0564`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:43:30.126607+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.803 | 0.39 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.110 | 2.69 |

| scv_a | 1.000 | 1.443 | 44.31 |

| scv_p | 1.000 | 1.273 | 27.31 |

| disturbance | 0.100 | 0.121 | 20.61 |

| load_cv | 0.200 | 0.217 | 8.44 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 115.547 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.196 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.116 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `23.4` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.765 |
| **P (Period/Due Date)** | 0.059 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.800 suggests horizon≈765.027 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2805,
  "disturbances": 2805,
  "dynamic_world": 2805,
  "ptimes": 2805,
  "routing": 2805
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)