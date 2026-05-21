
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `94f6abd3b2a1`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:36:43.146908+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.759 | 5.18 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.148 | 3.46 |

| scv_a | 1.000 | 1.109 | 10.86 |

| scv_p | 1.000 | 1.078 | 7.82 |

| disturbance | 0.000 | 0.000 | 0.00 |

| load_cv | 0.400 | 0.414 | 3.61 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 102.578 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.194 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.122 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `20.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.746 |
| **P (Period/Due Date)** | 0.058 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.800 suggests horizon≈765.027 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2111,
  "disturbances": 2111,
  "dynamic_world": 2111,
  "ptimes": 2111,
  "routing": 2111
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)