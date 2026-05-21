
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `20ebef41115c`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:28:43.226544+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.510 | 36.28 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.815 | 16.87 |

| scv_a | 1.000 | 1.112 | 11.17 |

| scv_p | 1.000 | 2.010 | 100.96 |

| disturbance | 0.100 | 0.096 | 4.02 |

| load_cv | 0.200 | 0.319 | 59.64 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 10.972 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.172 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `14.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.399 |
| **P (Period/Due Date)** | 0.052 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.800 suggests horizon≈3308.824 (was 4411.765). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2425,
  "disturbances": 2425,
  "dynamic_world": 2425,
  "ptimes": 2425,
  "routing": 2425
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)