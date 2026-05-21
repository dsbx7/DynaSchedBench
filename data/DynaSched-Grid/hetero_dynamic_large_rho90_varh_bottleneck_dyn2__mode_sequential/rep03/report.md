
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `5f09cda0425d`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T13:43:11.368895+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.826 | 8.18 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.738 | 4.79 |

| scv_a | 2.000 | 1.958 | 2.10 |

| scv_p | 2.000 | 2.258 | 12.91 |

| disturbance | 0.200 | 0.211 | 5.46 |

| load_cv | 0.200 | 0.286 | 43.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 152.297 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.211 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `27.4` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.810 |
| **P (Period/Due Date)** | 0.063 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.900 suggests horizon≈2941.176 (was 4411.765). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3502,
  "disturbances": 3502,
  "dynamic_world": 3502,
  "ptimes": 3502,
  "routing": 3502
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)