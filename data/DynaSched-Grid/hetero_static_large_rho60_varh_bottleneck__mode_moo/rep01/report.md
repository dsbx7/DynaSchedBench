
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `a6a6420ab7d8`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:14:42.971173+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.537 | 10.45 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 3.908 | 21.45 |

| scv_a | 2.000 | 2.409 | 20.43 |

| scv_p | 2.000 | 3.923 | 96.14 |

| disturbance | 0.050 | 0.050 | 0.86 |

| load_cv | 0.200 | 0.367 | 83.57 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 41.876 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.256 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `18.7` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.605 |
| **P (Period/Due Date)** | 0.075 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


All input targets were within the feasible envelope. No projections were needed.


## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3845,
  "disturbances": 3845,
  "dynamic_world": 3845,
  "ptimes": 3845,
  "routing": 3845
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)