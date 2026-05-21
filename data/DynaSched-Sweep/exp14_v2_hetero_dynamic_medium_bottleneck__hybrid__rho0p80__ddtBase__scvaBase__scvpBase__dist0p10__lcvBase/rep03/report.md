
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `d55a47671242`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:43:37.212655+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.646 | 19.28 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 7.832 | 57.40 |

| scv_a | 1.000 | 0.988 | 1.21 |

| scv_p | 1.000 | 0.820 | 18.02 |

| disturbance | 0.100 | 0.163 | 63.08 |

| load_cv | 0.200 | 0.281 | 40.50 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 17.367 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.128 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.118 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `15.5` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.468 |
| **P (Period/Due Date)** | 0.039 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.800 suggests horizon≈765.027 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2806,
  "disturbances": 2806,
  "dynamic_world": 2806,
  "ptimes": 2806,
  "routing": 2806
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)