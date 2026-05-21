
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `856b5db1e22c`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T12:55:45.794077+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.603 | 0.50 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 2.000 | 1.998 | 0.11 |

| scv_a | 1.500 | 1.525 | 1.69 |

| scv_p | 0.500 | 0.491 | 1.85 |

| disturbance | 0.000 | 0.000 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 3.050 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.501 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.030 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `9.0` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.225 |
| **P (Period/Due Date)** | 0.133 |
| **K (Conflict)** | 0.002 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=50 with rho_global=0.600 suggests horizon≈277.778 (was 238.095). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 1326,
  "disturbances": 1326,
  "dynamic_world": 1326,
  "ptimes": 1326,
  "routing": 1326
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)