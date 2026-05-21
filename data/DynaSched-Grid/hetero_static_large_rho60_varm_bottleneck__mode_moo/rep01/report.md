
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `4721b626e2c2`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:23:28.301797+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.360 | 39.98 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.794 | 16.45 |

| scv_a | 1.000 | 1.333 | 33.26 |

| scv_p | 1.000 | 2.120 | 111.99 |

| disturbance | 0.050 | 0.034 | 32.34 |

| load_cv | 0.200 | 0.343 | 71.69 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 4.102 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.173 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `9.6` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.262 |
| **P (Period/Due Date)** | 0.052 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


All input targets were within the feasible envelope. No projections were needed.


## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3872,
  "disturbances": 3872,
  "dynamic_world": 3872,
  "ptimes": 3872,
  "routing": 3872
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)