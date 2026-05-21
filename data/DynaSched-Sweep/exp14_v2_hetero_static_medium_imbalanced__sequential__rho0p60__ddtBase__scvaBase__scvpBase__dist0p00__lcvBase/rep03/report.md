
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `66d31b680a7e`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:28:19.761786+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.591 | 1.56 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.743 | 4.68 |

| scv_a | 1.000 | 1.026 | 2.61 |

| scv_p | 1.000 | 1.054 | 5.40 |

| disturbance | 0.000 | 0.000 | 0.00 |

| load_cv | 0.400 | 0.398 | 0.62 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 21.893 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.211 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.117 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `14.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.504 |
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
  "arrivals": 2016,
  "disturbances": 2016,
  "dynamic_world": 2016,
  "ptimes": 2016,
  "routing": 2016
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)