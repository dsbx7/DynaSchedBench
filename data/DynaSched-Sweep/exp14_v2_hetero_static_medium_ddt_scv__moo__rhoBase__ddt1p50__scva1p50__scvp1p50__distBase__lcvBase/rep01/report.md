
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `0c0f1b10095c`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:51:01.798902+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.607 | 1.13 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 1.500 | 1.479 | 1.37 |

| scv_a | 1.500 | 1.357 | 9.54 |

| scv_p | 1.500 | 1.314 | 12.43 |

| disturbance | 0.050 | 0.050 | 0.55 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 31.839 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.676 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.123 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `19.8` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.562 |
| **P (Period/Due Date)** | 0.170 |
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
  "arrivals": 2269,
  "disturbances": 2269,
  "dynamic_world": 2269,
  "ptimes": 2269,
  "routing": 2269
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)