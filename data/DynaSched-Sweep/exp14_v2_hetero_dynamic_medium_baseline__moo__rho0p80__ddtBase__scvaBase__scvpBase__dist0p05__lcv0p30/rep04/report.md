
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `2bb6ee105302`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:30:15.566330+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.794 | 0.72 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 2.973 | 40.24 |

| scv_a | 1.000 | 7.107 | 610.73 |

| scv_p | 1.000 | 0.825 | 17.51 |

| disturbance | 0.050 | 0.050 | 0.00 |

| load_cv | 0.300 | 0.468 | 55.96 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 243.338 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.336 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.114 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `26.0` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.884 |
| **P (Period/Due Date)** | 0.095 |
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
  "arrivals": 2652,
  "disturbances": 2652,
  "dynamic_world": 2652,
  "ptimes": 2652,
  "routing": 2652
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)