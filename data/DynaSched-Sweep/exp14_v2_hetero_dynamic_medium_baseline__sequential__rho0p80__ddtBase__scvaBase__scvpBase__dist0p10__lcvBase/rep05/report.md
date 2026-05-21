
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `f62894b14e24`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:21:14.357503+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.808 | 1.05 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.193 | 4.36 |

| scv_a | 1.000 | 0.977 | 2.31 |

| scv_p | 1.000 | 1.194 | 19.39 |

| disturbance | 0.100 | 0.113 | 12.76 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 102.186 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.193 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.116 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `22.9` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.746 |
| **P (Period/Due Date)** | 0.058 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.800 suggests horizon≈765.027 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2618,
  "disturbances": 2618,
  "dynamic_world": 2618,
  "ptimes": 2618,
  "routing": 2618
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)