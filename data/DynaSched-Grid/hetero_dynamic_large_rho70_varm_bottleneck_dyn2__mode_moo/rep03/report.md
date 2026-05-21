
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `62d435237acb`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T13:41:40.211448+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.700 | 0.675 | 3.61 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 6.091 | 22.41 |

| scv_a | 1.000 | 1.104 | 10.45 |

| scv_p | 1.000 | 0.699 | 30.13 |

| disturbance | 0.200 | 0.211 | 5.63 |

| load_cv | 0.200 | 0.454 | 126.86 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 93.177 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.164 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `25.2` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.731 |
| **P (Period/Due Date)** | 0.050 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.700 suggests horizon≈3781.513 (was 4411.765). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3469,
  "disturbances": 3469,
  "dynamic_world": 3469,
  "ptimes": 3469,
  "routing": 3469
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)