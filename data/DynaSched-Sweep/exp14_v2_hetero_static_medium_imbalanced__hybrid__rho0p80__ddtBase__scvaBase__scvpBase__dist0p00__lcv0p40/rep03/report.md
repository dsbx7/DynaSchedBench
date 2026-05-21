
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `13898a7debfc`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:45:04.137608+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.814 | 1.80 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.717 | 5.20 |

| scv_a | 1.000 | 0.977 | 2.26 |

| scv_p | 1.000 | 0.864 | 13.58 |

| disturbance | 0.000 | 0.000 | 0.00 |

| load_cv | 0.400 | 0.411 | 2.87 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 94.118 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.212 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.126 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `20.1` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.733 |
| **P (Period/Due Date)** | 0.063 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.800 suggests horizon≈765.027 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2171,
  "disturbances": 2171,
  "dynamic_world": 2171,
  "ptimes": 2171,
  "routing": 2171
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)