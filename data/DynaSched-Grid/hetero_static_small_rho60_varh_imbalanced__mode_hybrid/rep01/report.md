
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `d6c9abdc7509`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:56:09.514416+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.553 | 7.87 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.835 | 17.27 |

| scv_a | 2.000 | 2.125 | 6.27 |

| scv_p | 2.000 | 2.322 | 16.09 |

| disturbance | 0.050 | 0.050 | 0.00 |

| load_cv | 0.400 | 0.412 | 3.02 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 25.158 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.171 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.114 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `15.9` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.525 |
| **P (Period/Due Date)** | 0.052 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=100 with rho_global=0.600 suggests horizon≈510.018 (was 737.705). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 4073,
  "disturbances": 4073,
  "dynamic_world": 4073,
  "ptimes": 4073,
  "routing": 4073
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)