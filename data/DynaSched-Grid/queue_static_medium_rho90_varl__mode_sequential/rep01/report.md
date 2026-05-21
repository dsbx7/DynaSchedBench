
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `76d4887bb891`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:24:55.432588+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.902 | 0.22 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.803 | 3.48 |

| scv_a | 0.250 | 0.249 | 0.47 |

| scv_p | 0.250 | 0.256 | 2.33 |

| disturbance | 0.000 | 0.000 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 11.521 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.208 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.050 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `11.8` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.407 |
| **P (Period/Due Date)** | 0.062 |
| **K (Conflict)** | 0.003 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.900 suggests horizon≈444.444 (was 952.381). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 4301,
  "disturbances": 4301,
  "dynamic_world": 4301,
  "ptimes": 4301,
  "routing": 4301
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)