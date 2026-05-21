
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `c5e8a429e7b0`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:33:31.117197+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.534 | 10.92 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.102 | 2.53 |

| scv_a | 1.000 | 0.990 | 1.03 |

| scv_p | 1.000 | 0.751 | 24.86 |

| disturbance | 0.000 | 0.000 | 0.00 |

| load_cv | 0.200 | 0.195 | 2.61 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 5.061 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.196 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `9.1` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.290 |
| **P (Period/Due Date)** | 0.059 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


All input targets were within the feasible envelope. No projections were needed.


## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2437,
  "disturbances": 2437,
  "dynamic_world": 2437,
  "ptimes": 2437,
  "routing": 2437
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)