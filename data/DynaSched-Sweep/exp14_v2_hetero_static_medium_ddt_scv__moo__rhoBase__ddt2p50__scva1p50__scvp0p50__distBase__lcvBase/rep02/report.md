
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `4b94e4163f90`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:56:38.288706+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.574 | 4.35 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 2.500 | 1.999 | 20.02 |

| scv_a | 1.500 | 2.452 | 63.46 |

| scv_p | 0.500 | 0.622 | 24.33 |

| disturbance | 0.050 | 0.050 | 0.21 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 57.862 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.500 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.118 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `21.2` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.656 |
| **P (Period/Due Date)** | 0.133 |
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
  "arrivals": 2305,
  "disturbances": 2305,
  "dynamic_world": 2305,
  "ptimes": 2305,
  "routing": 2305
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)