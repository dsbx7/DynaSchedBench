
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `48aca1b02fc2`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T13:15:01.612769+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.700 | 0.687 | 1.86 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 3.954 | 20.54 |

| scv_a | 2.000 | 3.183 | 59.13 |

| scv_p | 2.000 | 2.277 | 13.85 |

| disturbance | 0.200 | 0.208 | 4.15 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 182.759 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.253 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `28.5` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.839 |
| **P (Period/Due Date)** | 0.074 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.700 suggests horizon≈3781.513 (was 4411.765). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3414,
  "disturbances": 3414,
  "dynamic_world": 3414,
  "ptimes": 3414,
  "routing": 3414
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)