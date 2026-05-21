
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `eb158580d755`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:55:33.742346+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.700 | 0.725 | 3.63 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.811 | 3.31 |

| scv_a | 2.000 | 2.112 | 5.62 |

| scv_p | 2.000 | 2.256 | 12.78 |

| disturbance | 0.100 | 0.106 | 6.35 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 8.413 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.208 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.050 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `13.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.361 |
| **P (Period/Due Date)** | 0.062 |
| **K (Conflict)** | 0.003 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.700 suggests horizon≈571.429 (was 952.381). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3769,
  "disturbances": 3769,
  "dynamic_world": 3769,
  "ptimes": 3769,
  "routing": 3769
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)