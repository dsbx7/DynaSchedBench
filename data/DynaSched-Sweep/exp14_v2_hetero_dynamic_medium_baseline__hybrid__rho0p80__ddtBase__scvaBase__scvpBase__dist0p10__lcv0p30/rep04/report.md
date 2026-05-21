
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `d0751e70bcbe`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:36:10.260389+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.815 | 1.83 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.265 | 5.80 |

| scv_a | 1.000 | 1.028 | 2.83 |

| scv_p | 1.000 | 1.105 | 10.48 |

| disturbance | 0.100 | 0.108 | 8.14 |

| load_cv | 0.300 | 0.321 | 7.11 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 101.260 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.190 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.122 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `22.8` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.744 |
| **P (Period/Due Date)** | 0.057 |
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
  "arrivals": 2702,
  "disturbances": 2702,
  "dynamic_world": 2702,
  "ptimes": 2702,
  "routing": 2702
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)