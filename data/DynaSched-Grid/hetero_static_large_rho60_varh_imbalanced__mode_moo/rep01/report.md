
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `a415930ea86c`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:14:45.718822+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.592 | 1.34 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 3.538 | 28.90 |

| scv_a | 2.000 | 3.461 | 73.04 |

| scv_p | 2.000 | 1.301 | 34.97 |

| disturbance | 0.050 | 0.054 | 8.20 |

| load_cv | 0.400 | 0.458 | 14.58 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 165.655 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.283 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `24.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.823 |
| **P (Period/Due Date)** | 0.082 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


All input targets were within the feasible envelope. No projections were needed.


## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3854,
  "disturbances": 3854,
  "dynamic_world": 3854,
  "ptimes": 3854,
  "routing": 3854
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)