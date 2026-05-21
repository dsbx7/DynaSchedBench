
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `9501523eda1a`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:55:13.808493+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.573 | 4.57 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.894 | 1.64 |

| scv_a | 2.000 | 2.057 | 2.85 |

| scv_p | 2.000 | 2.103 | 5.14 |

| disturbance | 0.050 | 0.050 | 0.16 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 20.925 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.204 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.121 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `15.4` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.497 |
| **P (Period/Due Date)** | 0.061 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=100 with rho_global=0.600 suggests horizon≈510.018 (was 737.705). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 4053,
  "disturbances": 4053,
  "dynamic_world": 4053,
  "ptimes": 4053,
  "routing": 4053
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)