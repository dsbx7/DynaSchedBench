
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `30effc6fd5b5`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:56:15.337112+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.657 | 9.47 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.525 | 11.04 |

| scv_a | 2.000 | 2.112 | 5.60 |

| scv_p | 2.000 | 1.425 | 28.73 |

| disturbance | 0.050 | 0.056 | 11.28 |

| load_cv | 0.400 | 0.470 | 17.40 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 135.665 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.181 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.119 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `22.6` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.791 |
| **P (Period/Due Date)** | 0.055 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=100 with rho_global=0.600 suggests horizon≈510.018 (was 737.705). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 4072,
  "disturbances": 4072,
  "dynamic_world": 4072,
  "ptimes": 4072,
  "routing": 4072
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)