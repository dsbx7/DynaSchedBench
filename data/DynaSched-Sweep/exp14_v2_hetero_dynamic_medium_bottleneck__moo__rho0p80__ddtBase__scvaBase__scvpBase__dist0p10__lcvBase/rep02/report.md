
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `aab49f49735f`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:38:26.102948+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.814 | 1.75 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 3.960 | 20.42 |

| scv_a | 1.000 | 4.378 | 337.82 |

| scv_p | 1.000 | 0.678 | 32.16 |

| disturbance | 0.100 | 0.115 | 15.48 |

| load_cv | 0.200 | 0.355 | 77.25 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 172.888 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.253 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.131 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `25.4` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.830 |
| **P (Period/Due Date)** | 0.074 |
| **K (Conflict)** | 0.007 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.800 suggests horizon≈765.027 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2765,
  "disturbances": 2765,
  "dynamic_world": 2765,
  "ptimes": 2765,
  "routing": 2765
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)