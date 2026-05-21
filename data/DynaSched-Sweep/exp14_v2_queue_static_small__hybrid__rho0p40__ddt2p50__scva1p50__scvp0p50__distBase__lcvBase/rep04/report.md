
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `2de2ce405770`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T13:05:56.230891+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.400 | 0.405 | 1.19 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 2.500 | 2.494 | 0.24 |

| scv_a | 1.500 | 1.405 | 6.34 |

| scv_p | 0.500 | 0.408 | 18.33 |

| disturbance | 0.000 | 0.000 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 1.297 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.401 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.030 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `6.1` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.134 |
| **P (Period/Due Date)** | 0.111 |
| **K (Conflict)** | 0.002 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=50 with rho_global=0.400 suggests horizon≈416.667 (was 238.095). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 1647,
  "disturbances": 1647,
  "dynamic_world": 1647,
  "ptimes": 1647,
  "routing": 1647
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)