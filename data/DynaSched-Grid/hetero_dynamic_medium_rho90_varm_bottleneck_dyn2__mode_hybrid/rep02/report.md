
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `f537ed2747db`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:27:26.128705+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.833 | 7.46 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.581 | 12.16 |

| scv_a | 1.000 | 1.033 | 3.26 |

| scv_p | 1.000 | 0.645 | 35.46 |

| disturbance | 0.200 | 0.242 | 21.15 |

| load_cv | 0.200 | 0.211 | 5.67 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 90.110 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.179 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.127 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `24.9` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.726 |
| **P (Period/Due Date)** | 0.054 |
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
  "arrivals": 3687,
  "disturbances": 3687,
  "dynamic_world": 3687,
  "ptimes": 3687,
  "routing": 3687
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)