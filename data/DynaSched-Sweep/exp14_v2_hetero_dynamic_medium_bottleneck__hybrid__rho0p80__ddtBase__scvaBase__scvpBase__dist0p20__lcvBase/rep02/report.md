
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `b9e1033f24ec`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:44:54.597879+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.636 | 20.49 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.731 | 15.18 |

| scv_a | 1.000 | 1.100 | 9.96 |

| scv_p | 1.000 | 1.348 | 34.77 |

| disturbance | 0.200 | 0.260 | 30.02 |

| load_cv | 0.200 | 0.215 | 7.39 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 9.058 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.174 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.118 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `16.0` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.371 |
| **P (Period/Due Date)** | 0.053 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.800 suggests horizon≈765.027 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2815,
  "disturbances": 2815,
  "dynamic_world": 2815,
  "ptimes": 2815,
  "routing": 2815
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)