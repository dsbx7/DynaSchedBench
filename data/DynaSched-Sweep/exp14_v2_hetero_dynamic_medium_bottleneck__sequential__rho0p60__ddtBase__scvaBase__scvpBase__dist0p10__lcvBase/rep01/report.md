
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `5787498ad6cc`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:34:41.855450+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.621 | 3.46 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.059 | 1.66 |

| scv_a | 1.000 | 1.080 | 8.00 |

| scv_p | 1.000 | 0.981 | 1.92 |

| disturbance | 0.100 | 0.165 | 64.77 |

| load_cv | 0.200 | 0.410 | 104.88 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 75.551 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.198 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.120 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `21.7` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.698 |
| **P (Period/Due Date)** | 0.059 |
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
  "arrivals": 2704,
  "disturbances": 2704,
  "dynamic_world": 2704,
  "ptimes": 2704,
  "routing": 2704
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)