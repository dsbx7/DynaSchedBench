
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `d2987588b62d`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:35:40.966212+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.439 | 45.07 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 8.337 | 67.55 |

| scv_a | 1.000 | 1.135 | 13.49 |

| scv_p | 1.000 | 1.723 | 72.31 |

| disturbance | 0.200 | 0.201 | 0.63 |

| load_cv | 0.200 | 0.319 | 59.46 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 5.428 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.120 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `14.1` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.299 |
| **P (Period/Due Date)** | 0.037 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.800 suggests horizon≈3308.824 (was 4411.765). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2432,
  "disturbances": 2432,
  "dynamic_world": 2432,
  "ptimes": 2432,
  "routing": 2432
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)