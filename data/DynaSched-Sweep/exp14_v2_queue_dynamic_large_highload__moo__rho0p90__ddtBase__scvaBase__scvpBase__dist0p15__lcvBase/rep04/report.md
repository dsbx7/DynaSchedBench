
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `becb1774c80f`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:18:58.077667+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.886 | 1.60 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 2.850 | 42.73 |

| scv_a | 2.000 | 6.277 | 213.83 |

| scv_p | 2.000 | 2.167 | 8.36 |

| disturbance | 0.150 | 0.150 | 0.12 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 40.408 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.351 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.080 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.150 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `21.5` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.599 |
| **P (Period/Due Date)** | 0.099 |
| **K (Conflict)** | 0.004 |
| **S (Stochastic)** | 0.158 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.900 suggests horizon≈1388.889 (was 4761.905). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2562,
  "disturbances": 2562,
  "dynamic_world": 2562,
  "ptimes": 2562,
  "routing": 2562
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)