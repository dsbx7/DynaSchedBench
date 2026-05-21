
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `be8fe7ed6e27`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:04:07.725715+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.583 | 2.90 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 2.500 | 2.527 | 1.07 |

| scv_a | 0.500 | 0.507 | 1.42 |

| scv_p | 1.500 | 1.439 | 4.04 |

| disturbance | 0.050 | 0.050 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 11.589 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.396 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.123 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `14.4` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.407 |
| **P (Period/Due Date)** | 0.110 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.600 suggests horizon≈1020.036 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2361,
  "disturbances": 2361,
  "dynamic_world": 2361,
  "ptimes": 2361,
  "routing": 2361
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)