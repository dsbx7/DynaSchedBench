
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `78d6888e63a1`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:22:26.682818+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.754 | 16.23 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 6.192 | 24.44 |

| scv_a | 2.000 | 2.058 | 2.89 |

| scv_p | 2.000 | 2.453 | 22.65 |

| disturbance | 0.100 | 0.118 | 17.86 |

| load_cv | 0.200 | 0.216 | 7.90 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 126.169 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.161 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.124 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `23.5` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.779 |
| **P (Period/Due Date)** | 0.049 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.900 suggests horizon≈680.024 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3643,
  "disturbances": 3643,
  "dynamic_world": 3643,
  "ptimes": 3643,
  "routing": 3643
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)