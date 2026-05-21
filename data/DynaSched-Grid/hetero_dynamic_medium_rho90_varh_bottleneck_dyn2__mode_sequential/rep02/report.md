
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `05408b9d387a`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:21:06.632980+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.881 | 2.06 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.099 | 2.48 |

| scv_a | 2.000 | 2.074 | 3.70 |

| scv_p | 2.000 | 1.740 | 13.01 |

| disturbance | 0.200 | 0.242 | 20.89 |

| load_cv | 0.200 | 0.256 | 28.13 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 142.437 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.196 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.128 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `26.9` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.799 |
| **P (Period/Due Date)** | 0.059 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.900 suggests horizon≈680.024 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3645,
  "disturbances": 3645,
  "dynamic_world": 3645,
  "ptimes": 3645,
  "routing": 3645
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)