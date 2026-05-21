
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `fafda2eddad5`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:34:50.430146+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.613 | 2.09 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.899 | 1.55 |

| scv_a | 1.000 | 0.989 | 1.11 |

| scv_p | 1.000 | 1.097 | 9.67 |

| disturbance | 0.100 | 0.120 | 20.37 |

| load_cv | 0.300 | 0.435 | 44.84 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 29.172 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.204 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.124 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `18.0` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.548 |
| **P (Period/Due Date)** | 0.061 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.600 suggests horizon≈1020.036 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2709,
  "disturbances": 2709,
  "dynamic_world": 2709,
  "ptimes": 2709,
  "routing": 2709
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)