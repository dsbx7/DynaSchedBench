
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `5320e47b3173`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:44:32.224078+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.874 | 2.91 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.830 | 2.93 |

| scv_a | 2.000 | 2.009 | 0.46 |

| scv_p | 2.000 | 2.133 | 6.63 |

| disturbance | 0.050 | 0.053 | 6.07 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 150.474 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.207 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `23.4` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.808 |
| **P (Period/Due Date)** | 0.062 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.900 suggests horizon≈2941.176 (was 4411.765). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2846,
  "disturbances": 2846,
  "dynamic_world": 2846,
  "ptimes": 2846,
  "routing": 2846
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)