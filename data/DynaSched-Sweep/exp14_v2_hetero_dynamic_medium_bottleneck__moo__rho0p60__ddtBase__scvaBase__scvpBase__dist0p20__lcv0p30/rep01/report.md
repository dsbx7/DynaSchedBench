
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `96c0c9873dff`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:37:54.606978+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.574 | 4.30 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.426 | 9.04 |

| scv_a | 1.000 | 0.960 | 4.04 |

| scv_p | 1.000 | 1.106 | 10.57 |

| disturbance | 0.200 | 0.201 | 0.36 |

| load_cv | 0.300 | 0.293 | 2.32 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 7.901 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.184 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.121 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `15.6` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.352 |
| **P (Period/Due Date)** | 0.056 |
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
  "arrivals": 2759,
  "disturbances": 2759,
  "dynamic_world": 2759,
  "ptimes": 2759,
  "routing": 2759
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)