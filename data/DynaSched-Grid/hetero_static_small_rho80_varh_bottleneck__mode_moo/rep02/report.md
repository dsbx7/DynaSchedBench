
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `2337f09f5642`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:58:15.711638+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.753 | 5.94 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.097 | 17.67 |

| scv_a | 2.000 | 2.748 | 37.42 |

| scv_p | 2.000 | 1.727 | 13.67 |

| disturbance | 0.050 | 0.051 | 1.66 |

| load_cv | 0.200 | 0.226 | 13.25 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 55.445 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.244 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.132 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `19.5` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.649 |
| **P (Period/Due Date)** | 0.072 |
| **K (Conflict)** | 0.007 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=100 with rho_global=0.800 suggests horizon≈382.514 (was 737.705). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 4116,
  "disturbances": 4116,
  "dynamic_world": 4116,
  "ptimes": 4116,
  "routing": 4116
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)