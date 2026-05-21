
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `bb29a72db57a`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:13:01.802680+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.700 | 0.691 | 1.27 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.747 | 4.60 |

| scv_a | 2.000 | 1.910 | 4.50 |

| scv_p | 2.000 | 2.358 | 17.91 |

| disturbance | 0.200 | 0.198 | 0.80 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 153.571 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.211 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.118 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `27.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.811 |
| **P (Period/Due Date)** | 0.063 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.700 suggests horizon≈874.317 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3558,
  "disturbances": 3558,
  "dynamic_world": 3558,
  "ptimes": 3558,
  "routing": 3558
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)