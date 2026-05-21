
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `80c728f385e7`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:50:23.895327+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.787 | 1.58 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.994 | 0.37 |

| scv_a | 2.000 | 1.628 | 18.58 |

| scv_p | 2.000 | 1.911 | 4.44 |

| disturbance | 0.050 | 0.050 | 0.00 |

| load_cv | 0.200 | 0.342 | 70.76 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 135.720 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.200 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.118 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `22.7` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.791 |
| **P (Period/Due Date)** | 0.060 |
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
  "arrivals": 4006,
  "disturbances": 4006,
  "dynamic_world": 4006,
  "ptimes": 4006,
  "routing": 4006
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)