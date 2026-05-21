
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `0c6fccc78621`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:57:10.290435+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.600 | 0.01 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 3.539 | 28.88 |

| scv_a | 1.000 | 2.173 | 117.33 |

| scv_p | 1.000 | 1.406 | 40.59 |

| disturbance | 0.050 | 0.050 | 0.00 |

| load_cv | 0.200 | 0.236 | 17.81 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 10.588 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.283 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.107 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `13.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.394 |
| **P (Period/Due Date)** | 0.082 |
| **K (Conflict)** | 0.005 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=100 with rho_global=0.600 suggests horizon≈510.018 (was 737.705). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 4093,
  "disturbances": 4093,
  "dynamic_world": 4093,
  "ptimes": 4093,
  "routing": 4093
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)