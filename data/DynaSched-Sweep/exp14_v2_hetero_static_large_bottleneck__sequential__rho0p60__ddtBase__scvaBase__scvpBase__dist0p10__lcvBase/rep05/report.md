
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `15a34ef6f4b7`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:04:32.991591+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.590 | 1.68 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.045 | 1.38 |

| scv_a | 1.000 | 0.995 | 0.50 |

| scv_p | 1.000 | 1.102 | 10.24 |

| disturbance | 0.100 | 0.100 | 0.00 |

| load_cv | 0.200 | 0.345 | 72.35 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 47.583 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.198 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `20.1` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.625 |
| **P (Period/Due Date)** | 0.059 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


All input targets were within the feasible envelope. No projections were needed.


## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2383,
  "disturbances": 2383,
  "dynamic_world": 2383,
  "ptimes": 2383,
  "routing": 2383
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)