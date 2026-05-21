
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `d2c6ad5d7230`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:38:07.675259+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.580 | 3.27 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 7.826 | 57.27 |

| scv_a | 1.000 | 1.046 | 4.57 |

| scv_p | 1.000 | 1.821 | 82.06 |

| disturbance | 0.200 | 0.203 | 1.42 |

| load_cv | 0.200 | 0.249 | 24.57 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 8.540 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.128 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.123 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `15.5` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.363 |
| **P (Period/Due Date)** | 0.039 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.600 suggests horizon≈1020.036 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2756,
  "disturbances": 2756,
  "dynamic_world": 2756,
  "ptimes": 2756,
  "routing": 2756
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)