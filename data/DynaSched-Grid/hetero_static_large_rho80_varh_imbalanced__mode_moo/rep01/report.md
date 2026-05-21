
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `e3be1a55c73b`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:36:08.950554+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.797 | 0.43 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.686 | 5.82 |

| scv_a | 2.000 | 1.991 | 0.43 |

| scv_p | 2.000 | 2.298 | 14.91 |

| disturbance | 0.050 | 0.049 | 1.31 |

| load_cv | 0.400 | 0.427 | 6.82 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 154.098 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.213 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `23.6` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.811 |
| **P (Period/Due Date)** | 0.064 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.800 suggests horizon≈3308.824 (was 4411.765). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3908,
  "disturbances": 3908,
  "dynamic_world": 3908,
  "ptimes": 3908,
  "routing": 3908
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)