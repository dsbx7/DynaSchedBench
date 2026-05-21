
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `51fcac11a224`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T17:12:33.975753+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.898 | 0.21 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.779 | 16.14 |

| scv_a | 2.000 | 1.987 | 0.67 |

| scv_p | 2.000 | 1.283 | 35.85 |

| disturbance | 0.150 | 0.134 | 10.74 |

| load_cv | 0.300 | 0.451 | 50.21 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 129.109 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.173 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.150 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `25.2` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.783 |
| **P (Period/Due Date)** | 0.052 |
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
  "arrivals": 2902,
  "disturbances": 2902,
  "dynamic_world": 2902,
  "ptimes": 2902,
  "routing": 2902
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)