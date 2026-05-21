
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `e899f596fa4a`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:43:56.957532+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.812 | 1.55 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.150 | 3.50 |

| scv_a | 1.000 | 1.006 | 0.64 |

| scv_p | 1.000 | 1.107 | 10.70 |

| disturbance | 0.100 | 0.106 | 6.06 |

| load_cv | 0.300 | 0.314 | 4.70 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 100.778 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.194 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.112 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `22.8` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.744 |
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
  "arrivals": 2809,
  "disturbances": 2809,
  "dynamic_world": 2809,
  "ptimes": 2809,
  "routing": 2809
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)