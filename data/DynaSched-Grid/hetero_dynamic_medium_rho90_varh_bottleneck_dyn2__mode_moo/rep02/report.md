
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `17ce9410aeef`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:23:55.743846+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.979 | 8.79 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 2.551 | 48.74 |

| scv_a | 2.000 | 17.166 | 758.28 |

| scv_p | 2.000 | 5.069 | 153.47 |

| disturbance | 0.200 | 0.210 | 4.93 |

| load_cv | 0.200 | 0.286 | 43.08 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 418.198 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.392 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.121 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `32.4` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.971 |
| **P (Period/Due Date)** | 0.109 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.900 suggests horizon≈680.024 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3648,
  "disturbances": 3648,
  "dynamic_world": 3648,
  "ptimes": 3648,
  "routing": 3648
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)