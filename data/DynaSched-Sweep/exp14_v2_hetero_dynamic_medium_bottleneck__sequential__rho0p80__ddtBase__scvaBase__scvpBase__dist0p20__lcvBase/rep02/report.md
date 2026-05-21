
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `7760f8203316`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:35:03.484187+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.799 | 0.08 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.971 | 0.10 |

| scv_a | 1.000 | 0.987 | 1.33 |

| scv_p | 1.000 | 0.868 | 13.22 |

| disturbance | 0.200 | 0.220 | 10.12 |

| load_cv | 0.200 | 0.227 | 13.43 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 94.434 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.201 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.121 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `25.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.733 |
| **P (Period/Due Date)** | 0.060 |
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
  "arrivals": 2735,
  "disturbances": 2735,
  "dynamic_world": 2735,
  "ptimes": 2735,
  "routing": 2735
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)