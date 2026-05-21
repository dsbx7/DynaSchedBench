
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `984061a12aec`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:30:32.597493+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.871 | 3.19 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.879 | 1.95 |

| scv_a | 2.000 | 1.980 | 1.01 |

| scv_p | 2.000 | 1.895 | 5.26 |

| disturbance | 0.150 | 0.156 | 4.28 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 19.886 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.205 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.080 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.150 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `17.8` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.489 |
| **P (Period/Due Date)** | 0.061 |
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
  "arrivals": 2579,
  "disturbances": 2579,
  "dynamic_world": 2579,
  "ptimes": 2579,
  "routing": 2579
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)