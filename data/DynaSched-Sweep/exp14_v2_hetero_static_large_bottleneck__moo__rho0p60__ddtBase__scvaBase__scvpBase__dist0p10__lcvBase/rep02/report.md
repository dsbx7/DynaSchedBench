
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `c386fb10f12c`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:17:13.787222+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.525 | 12.44 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 9.105 | 82.97 |

| scv_a | 1.000 | 1.833 | 83.33 |

| scv_p | 1.000 | 0.681 | 31.93 |

| disturbance | 0.100 | 0.102 | 2.50 |

| load_cv | 0.200 | 0.438 | 119.16 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 59.687 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.110 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `20.4` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.660 |
| **P (Period/Due Date)** | 0.034 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


All input targets were within the feasible envelope. No projections were needed.


## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2410,
  "disturbances": 2410,
  "dynamic_world": 2410,
  "ptimes": 2410,
  "routing": 2410
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)