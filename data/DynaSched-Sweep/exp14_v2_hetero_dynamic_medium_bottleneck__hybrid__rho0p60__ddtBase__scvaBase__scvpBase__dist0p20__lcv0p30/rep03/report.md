
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `898f13b0dd10`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:43:05.016611+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.565 | 5.77 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.148 | 3.45 |

| scv_a | 1.000 | 0.966 | 3.40 |

| scv_p | 1.000 | 1.077 | 7.66 |

| disturbance | 0.200 | 0.214 | 6.89 |

| load_cv | 0.300 | 0.302 | 0.80 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 7.975 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.194 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.117 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `15.7` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.353 |
| **P (Period/Due Date)** | 0.058 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.600 suggests horizon≈1020.036 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2801,
  "disturbances": 2801,
  "dynamic_world": 2801,
  "ptimes": 2801,
  "routing": 2801
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)