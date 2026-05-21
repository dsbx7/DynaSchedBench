
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `fb5ed3e6c199`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:48:12.331749+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.577 | 3.76 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.012 | 0.73 |

| scv_a | 1.000 | 0.917 | 8.33 |

| scv_p | 1.000 | 1.088 | 8.80 |

| disturbance | 0.050 | 0.050 | 0.00 |

| load_cv | 0.200 | 0.399 | 99.54 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 11.955 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.200 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.125 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `13.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.412 |
| **P (Period/Due Date)** | 0.060 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.600 suggests horizon≈1020.036 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3979,
  "disturbances": 3979,
  "dynamic_world": 3979,
  "ptimes": 3979,
  "routing": 3979
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)