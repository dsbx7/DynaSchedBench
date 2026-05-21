
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `a1986b38b070`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:36:31.966474+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.563 | 6.11 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 2.809 | 43.55 |

| scv_a | 1.000 | 8.224 | 722.35 |

| scv_p | 1.000 | 0.790 | 20.97 |

| disturbance | 0.100 | 0.142 | 42.38 |

| load_cv | 0.200 | 0.502 | 150.89 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 143.791 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.356 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.112 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `25.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.800 |
| **P (Period/Due Date)** | 0.100 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.600 suggests horizon≈1020.036 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2748,
  "disturbances": 2748,
  "dynamic_world": 2748,
  "ptimes": 2748,
  "routing": 2748
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)