
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `0c6fa5f0addb`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:09:34.510219+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.810 | 10.00 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.346 | 7.43 |

| scv_a | 1.000 | 1.025 | 2.55 |

| scv_p | 1.000 | 0.755 | 24.48 |

| disturbance | 0.100 | 0.117 | 17.41 |

| load_cv | 0.200 | 0.230 | 14.81 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 92.626 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.187 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `22.7` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.730 |
| **P (Period/Due Date)** | 0.056 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.900 suggests horizon≈2941.176 (was 4411.765). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3535,
  "disturbances": 3535,
  "dynamic_world": 3535,
  "ptimes": 3535,
  "routing": 3535
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)