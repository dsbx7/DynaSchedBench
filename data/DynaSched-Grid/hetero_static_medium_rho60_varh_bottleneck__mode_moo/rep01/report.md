
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `1532af05f258`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:46:54.357001+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.724 | 20.60 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 3.341 | 32.85 |

| scv_a | 2.000 | 1.677 | 16.15 |

| scv_p | 2.000 | 1.568 | 21.62 |

| disturbance | 0.050 | 0.046 | 7.45 |

| load_cv | 0.200 | 0.300 | 50.14 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 128.490 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.299 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.129 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `23.2` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.782 |
| **P (Period/Due Date)** | 0.086 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.600 suggests horizon≈1020.036 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3953,
  "disturbances": 3953,
  "dynamic_world": 3953,
  "ptimes": 3953,
  "routing": 3953
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)