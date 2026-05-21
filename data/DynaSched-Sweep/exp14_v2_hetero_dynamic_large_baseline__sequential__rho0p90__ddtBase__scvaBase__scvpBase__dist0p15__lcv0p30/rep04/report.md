
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `e708fa3dbfd9`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:44:39.815648+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.838 | 6.93 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.932 | 0.88 |

| scv_a | 2.000 | 1.959 | 2.05 |

| scv_p | 2.000 | 2.168 | 8.42 |

| disturbance | 0.150 | 0.160 | 6.93 |

| load_cv | 0.300 | 0.335 | 11.64 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 150.120 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.203 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.150 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `26.0` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.807 |
| **P (Period/Due Date)** | 0.061 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.158 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.900 suggests horizon≈2941.176 (was 4411.765). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2862,
  "disturbances": 2862,
  "dynamic_world": 2862,
  "ptimes": 2862,
  "routing": 2862
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)