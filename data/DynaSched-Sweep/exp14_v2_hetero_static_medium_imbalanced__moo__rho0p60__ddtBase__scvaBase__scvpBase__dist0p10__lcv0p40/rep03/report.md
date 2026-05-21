
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `4369cd4ab5d6`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:35:42.622276+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.601 | 0.21 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.499 | 9.59 |

| scv_a | 1.000 | 1.363 | 36.32 |

| scv_p | 1.000 | 0.873 | 12.69 |

| disturbance | 0.100 | 0.100 | 0.23 |

| load_cv | 0.400 | 0.407 | 1.76 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 50.605 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.222 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.126 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `20.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.634 |
| **P (Period/Due Date)** | 0.066 |
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
  "arrivals": 2101,
  "disturbances": 2101,
  "dynamic_world": 2101,
  "ptimes": 2101,
  "routing": 2101
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)