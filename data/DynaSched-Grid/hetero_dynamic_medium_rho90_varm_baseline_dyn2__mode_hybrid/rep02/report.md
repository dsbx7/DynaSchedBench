
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `d4878dfb8b40`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:25:41.148990+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.877 | 2.55 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.774 | 4.05 |

| scv_a | 1.000 | 1.002 | 0.19 |

| scv_p | 1.000 | 1.042 | 4.22 |

| disturbance | 0.200 | 0.208 | 3.99 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 99.080 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.209 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.122 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `25.5` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.741 |
| **P (Period/Due Date)** | 0.062 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.900 suggests horizon≈680.024 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3669,
  "disturbances": 3669,
  "dynamic_world": 3669,
  "ptimes": 3669,
  "routing": 3669
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)