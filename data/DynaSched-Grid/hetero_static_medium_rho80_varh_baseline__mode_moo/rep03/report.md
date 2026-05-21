
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `bd4c14c67156`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:52:03.482990+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.821 | 2.63 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.043 | 1.36 |

| scv_a | 2.000 | 2.051 | 2.57 |

| scv_p | 2.000 | 2.393 | 19.66 |

| disturbance | 0.050 | 0.055 | 10.43 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 157.891 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.198 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.123 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `23.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.815 |
| **P (Period/Due Date)** | 0.059 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.800 suggests horizon≈765.027 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 4000,
  "disturbances": 4000,
  "dynamic_world": 4000,
  "ptimes": 4000,
  "routing": 4000
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)