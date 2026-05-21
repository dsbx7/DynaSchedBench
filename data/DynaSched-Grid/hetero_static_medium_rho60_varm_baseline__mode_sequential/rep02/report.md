
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `fa62d0ee5094`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:47:02.496820+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.617 | 2.78 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.754 | 4.47 |

| scv_a | 1.000 | 0.980 | 2.00 |

| scv_p | 1.000 | 0.964 | 3.55 |

| disturbance | 0.050 | 0.050 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 35.891 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.210 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.127 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `17.6` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.580 |
| **P (Period/Due Date)** | 0.063 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.600 suggests horizon≈1020.036 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3969,
  "disturbances": 3969,
  "dynamic_world": 3969,
  "ptimes": 3969,
  "routing": 3969
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)