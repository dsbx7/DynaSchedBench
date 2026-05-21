
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `df91df1034f8`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T17:21:37.172390+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.700 | 0.716 | 2.27 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.125 | 2.99 |

| scv_a | 2.000 | 2.046 | 2.31 |

| scv_p | 2.000 | 2.155 | 7.73 |

| disturbance | 0.150 | 0.161 | 7.19 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 151.920 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.195 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.150 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `26.0` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.809 |
| **P (Period/Due Date)** | 0.059 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.158 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.700 suggests horizon≈3781.513 (was 4411.765). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2918,
  "disturbances": 2918,
  "dynamic_world": 2918,
  "ptimes": 2918,
  "routing": 2918
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)