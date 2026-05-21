
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `4cb96b22af9a`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:28:23.168853+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.593 | 1.15 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.702 | 5.51 |

| scv_a | 1.000 | 1.015 | 1.50 |

| scv_p | 1.000 | 1.146 | 14.55 |

| disturbance | 0.000 | 0.000 | 0.00 |

| load_cv | 0.400 | 0.410 | 2.54 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 52.123 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.213 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.119 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `17.7` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.639 |
| **P (Period/Due Date)** | 0.063 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.600 suggests horizon≈1020.036 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2017,
  "disturbances": 2017,
  "dynamic_world": 2017,
  "ptimes": 2017,
  "routing": 2017
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)