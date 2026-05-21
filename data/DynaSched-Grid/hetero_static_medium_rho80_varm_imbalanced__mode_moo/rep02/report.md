
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `80f9888999db`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:55:17.171135+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.905 | 13.08 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.567 | 8.23 |

| scv_a | 1.000 | 0.933 | 6.69 |

| scv_p | 1.000 | 0.848 | 15.20 |

| disturbance | 0.050 | 0.074 | 48.20 |

| load_cv | 0.400 | 0.422 | 5.39 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 92.636 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.219 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.125 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `21.4` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.730 |
| **P (Period/Due Date)** | 0.065 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.800 suggests horizon≈765.027 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 4044,
  "disturbances": 4044,
  "dynamic_world": 4044,
  "ptimes": 4044,
  "routing": 4044
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)