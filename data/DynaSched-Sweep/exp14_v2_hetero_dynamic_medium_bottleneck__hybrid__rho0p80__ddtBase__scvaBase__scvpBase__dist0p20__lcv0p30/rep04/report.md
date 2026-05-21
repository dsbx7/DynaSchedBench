
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `1a525a933f5f`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:45:40.504765+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.763 | 4.68 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.599 | 12.53 |

| scv_a | 1.000 | 1.099 | 9.87 |

| scv_p | 1.000 | 1.260 | 25.96 |

| disturbance | 0.200 | 0.220 | 9.75 |

| load_cv | 0.300 | 0.307 | 2.48 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 106.777 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.179 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.112 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `25.6` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.753 |
| **P (Period/Due Date)** | 0.054 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.800 suggests horizon≈765.027 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2822,
  "disturbances": 2822,
  "dynamic_world": 2822,
  "ptimes": 2822,
  "routing": 2822
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)