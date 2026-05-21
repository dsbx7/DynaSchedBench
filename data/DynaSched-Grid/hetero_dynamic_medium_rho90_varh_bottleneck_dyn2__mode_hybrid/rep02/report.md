
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `23ea1c3efb65`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:23:52.838038+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.821 | 8.77 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.923 | 19.03 |

| scv_a | 2.000 | 2.054 | 2.71 |

| scv_p | 2.000 | 3.530 | 76.51 |

| disturbance | 0.200 | 0.246 | 22.93 |

| load_cv | 0.200 | 0.288 | 43.86 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 185.818 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.169 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.126 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `27.7` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.841 |
| **P (Period/Due Date)** | 0.051 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.900 suggests horizon≈680.024 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3651,
  "disturbances": 3651,
  "dynamic_world": 3651,
  "ptimes": 3651,
  "routing": 3651
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)