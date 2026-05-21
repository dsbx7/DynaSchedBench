
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `24d761e77d53`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:55:21.270565+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.584 | 2.70 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.741 | 4.72 |

| scv_a | 1.000 | 0.996 | 0.43 |

| scv_p | 1.000 | 0.948 | 5.21 |

| disturbance | 0.050 | 0.050 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 96.618 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.211 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.119 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `21.5` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.737 |
| **P (Period/Due Date)** | 0.063 |
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
  "arrivals": 4076,
  "disturbances": 4076,
  "dynamic_world": 4076,
  "ptimes": 4076,
  "routing": 4076
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)