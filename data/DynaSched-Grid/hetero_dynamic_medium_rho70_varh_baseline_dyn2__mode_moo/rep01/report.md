
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `3803ecbbf558`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:12:33.750769+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.700 | 0.685 | 2.20 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.412 | 11.33 |

| scv_a | 2.000 | 1.989 | 0.57 |

| scv_p | 2.000 | 2.190 | 9.52 |

| disturbance | 0.200 | 0.195 | 2.35 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 151.388 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.227 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.119 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `27.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.809 |
| **P (Period/Due Date)** | 0.067 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.700 suggests horizon≈874.317 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3557,
  "disturbances": 3557,
  "dynamic_world": 3557,
  "ptimes": 3557,
  "routing": 3557
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)