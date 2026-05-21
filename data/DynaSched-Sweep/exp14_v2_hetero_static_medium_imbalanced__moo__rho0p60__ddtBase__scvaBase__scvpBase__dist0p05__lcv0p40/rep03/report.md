
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `f50b6cc9f11f`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:33:57.193025+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.631 | 5.17 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.639 | 6.78 |

| scv_a | 1.000 | 1.021 | 2.15 |

| scv_p | 1.000 | 0.822 | 17.85 |

| disturbance | 0.050 | 0.083 | 65.91 |

| load_cv | 0.400 | 0.390 | 2.39 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 33.460 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.216 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.131 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `17.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.569 |
| **P (Period/Due Date)** | 0.064 |
| **K (Conflict)** | 0.007 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.600 suggests horizon≈1020.036 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2091,
  "disturbances": 2091,
  "dynamic_world": 2091,
  "ptimes": 2091,
  "routing": 2091
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)