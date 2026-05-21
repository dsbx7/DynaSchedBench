
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `bf6ee6c5b5c0`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:44:20.564344+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.824 | 3.01 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.318 | 13.23 |

| scv_a | 1.000 | 1.966 | 96.56 |

| scv_p | 1.000 | 1.114 | 11.37 |

| disturbance | 0.100 | 0.106 | 6.11 |

| load_cv | 0.300 | 0.290 | 3.43 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 124.445 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.232 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.112 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `23.9` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.777 |
| **P (Period/Due Date)** | 0.068 |
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
  "arrivals": 2811,
  "disturbances": 2811,
  "dynamic_world": 2811,
  "ptimes": 2811,
  "routing": 2811
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)