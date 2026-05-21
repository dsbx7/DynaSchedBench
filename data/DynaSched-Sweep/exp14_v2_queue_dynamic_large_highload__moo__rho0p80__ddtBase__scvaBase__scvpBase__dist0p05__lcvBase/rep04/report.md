
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `33f68bbbb642`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:07:34.070188+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.808 | 0.97 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.761 | 4.32 |

| scv_a | 2.000 | 1.987 | 0.66 |

| scv_p | 2.000 | 1.983 | 0.86 |

| disturbance | 0.050 | 0.055 | 9.14 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 12.541 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.210 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.080 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `13.5` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.419 |
| **P (Period/Due Date)** | 0.063 |
| **K (Conflict)** | 0.004 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.800 suggests horizon≈1562.500 (was 4761.905). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2547,
  "disturbances": 2547,
  "dynamic_world": 2547,
  "ptimes": 2547,
  "routing": 2547
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)