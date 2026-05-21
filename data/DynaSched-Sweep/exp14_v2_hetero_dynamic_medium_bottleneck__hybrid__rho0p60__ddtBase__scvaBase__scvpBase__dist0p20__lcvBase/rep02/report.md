
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `e5a86327b905`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:42:28.299832+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.512 | 14.67 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.610 | 7.36 |

| scv_a | 1.000 | 1.020 | 1.98 |

| scv_p | 1.000 | 0.751 | 24.91 |

| disturbance | 0.200 | 0.221 | 10.31 |

| load_cv | 0.200 | 0.214 | 6.99 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 3.603 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.217 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.120 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `13.2` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.246 |
| **P (Period/Due Date)** | 0.064 |
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
  "arrivals": 2795,
  "disturbances": 2795,
  "dynamic_world": 2795,
  "ptimes": 2795,
  "routing": 2795
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)