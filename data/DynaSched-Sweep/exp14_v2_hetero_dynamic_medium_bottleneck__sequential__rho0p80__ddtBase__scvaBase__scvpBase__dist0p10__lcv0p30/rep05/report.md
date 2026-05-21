
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `21aa5f768541`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:35:01.126183+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.785 | 1.93 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.883 | 1.87 |

| scv_a | 1.000 | 0.956 | 4.39 |

| scv_p | 1.000 | 1.031 | 3.09 |

| disturbance | 0.100 | 0.104 | 3.51 |

| load_cv | 0.300 | 0.306 | 2.15 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 97.680 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.205 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.124 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `22.8` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.739 |
| **P (Period/Due Date)** | 0.061 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.800 suggests horizon≈765.027 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2733,
  "disturbances": 2733,
  "dynamic_world": 2733,
  "ptimes": 2733,
  "routing": 2733
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)