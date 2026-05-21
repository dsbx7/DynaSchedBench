
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `e1a461291142`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:40:12.073069+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.743 | 7.18 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.644 | 6.68 |

| scv_a | 1.000 | 1.076 | 7.63 |

| scv_p | 1.000 | 0.723 | 27.72 |

| disturbance | 0.200 | 0.253 | 26.74 |

| load_cv | 0.300 | 0.343 | 14.45 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 93.077 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.215 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.120 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `25.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.731 |
| **P (Period/Due Date)** | 0.064 |
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
  "arrivals": 2782,
  "disturbances": 2782,
  "dynamic_world": 2782,
  "ptimes": 2782,
  "routing": 2782
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)