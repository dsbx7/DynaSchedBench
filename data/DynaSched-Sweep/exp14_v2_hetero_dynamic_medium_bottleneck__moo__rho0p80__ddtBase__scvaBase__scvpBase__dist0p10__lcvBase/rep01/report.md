
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `444d78d48f92`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:38:27.111009+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.721 | 9.81 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 6.665 | 33.94 |

| scv_a | 1.000 | 1.781 | 78.08 |

| scv_p | 1.000 | 1.655 | 65.53 |

| disturbance | 0.100 | 0.116 | 16.38 |

| load_cv | 0.200 | 0.298 | 48.97 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 133.184 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.150 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.125 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `23.6` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.788 |
| **P (Period/Due Date)** | 0.046 |
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
  "arrivals": 2764,
  "disturbances": 2764,
  "dynamic_world": 2764,
  "ptimes": 2764,
  "routing": 2764
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)