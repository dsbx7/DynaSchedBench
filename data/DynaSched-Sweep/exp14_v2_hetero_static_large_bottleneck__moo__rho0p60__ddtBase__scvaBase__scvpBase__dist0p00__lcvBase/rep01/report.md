
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `f258ea179417`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:13:58.438948+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.401 | 33.18 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.906 | 18.69 |

| scv_a | 1.000 | 1.257 | 25.70 |

| scv_p | 1.000 | 2.020 | 102.05 |

| disturbance | 0.000 | 0.000 | 0.00 |

| load_cv | 0.200 | 0.339 | 69.68 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 4.895 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.169 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `8.8` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.285 |
| **P (Period/Due Date)** | 0.051 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


All input targets were within the feasible envelope. No projections were needed.


## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2404,
  "disturbances": 2404,
  "dynamic_world": 2404,
  "ptimes": 2404,
  "routing": 2404
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)