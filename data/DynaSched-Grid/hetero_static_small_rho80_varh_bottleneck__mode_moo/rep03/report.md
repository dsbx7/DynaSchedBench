
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `369a0d2004b3`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:58:15.855811+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.818 | 2.29 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.003 | 19.55 |

| scv_a | 2.000 | 2.037 | 1.83 |

| scv_p | 2.000 | 1.533 | 23.37 |

| disturbance | 0.050 | 0.056 | 11.10 |

| load_cv | 0.200 | 0.201 | 0.65 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 89.220 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.250 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.129 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `21.4` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.724 |
| **P (Period/Due Date)** | 0.073 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=100 with rho_global=0.800 suggests horizon≈382.514 (was 737.705). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 4117,
  "disturbances": 4117,
  "dynamic_world": 4117,
  "ptimes": 4117,
  "routing": 4117
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)