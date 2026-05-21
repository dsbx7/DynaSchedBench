
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `318258d59f92`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:58:29.444649+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.976 | 22.01 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.601 | 7.53 |

| scv_a | 2.000 | 1.494 | 25.28 |

| scv_p | 2.000 | 2.639 | 31.94 |

| disturbance | 0.050 | 0.050 | 0.00 |

| load_cv | 0.400 | 0.435 | 8.73 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 150.262 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.217 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.129 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `23.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.807 |
| **P (Period/Due Date)** | 0.065 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=100 with rho_global=0.800 suggests horizon≈382.514 (was 737.705). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 4129,
  "disturbances": 4129,
  "dynamic_world": 4129,
  "ptimes": 4129,
  "routing": 4129
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)