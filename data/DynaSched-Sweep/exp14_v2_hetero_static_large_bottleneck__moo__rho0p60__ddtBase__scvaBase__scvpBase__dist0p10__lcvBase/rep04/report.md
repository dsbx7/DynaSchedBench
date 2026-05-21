
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `5e948c99e0e3`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:18:40.411277+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.362 | 39.71 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.883 | 18.23 |

| scv_a | 1.000 | 1.124 | 12.36 |

| scv_p | 1.000 | 1.607 | 60.68 |

| disturbance | 0.100 | 0.142 | 42.05 |

| load_cv | 0.200 | 0.279 | 39.38 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 2.896 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.170 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `9.8` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.219 |
| **P (Period/Due Date)** | 0.052 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


All input targets were within the feasible envelope. No projections were needed.


## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2412,
  "disturbances": 2412,
  "dynamic_world": 2412,
  "ptimes": 2412,
  "routing": 2412
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)