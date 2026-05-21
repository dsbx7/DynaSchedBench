
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `1eb5732f98ff`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T13:02:12.574925+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.787 | 1.58 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 1.500 | 1.553 | 3.56 |

| scv_a | 1.500 | 1.504 | 0.29 |

| scv_p | 1.500 | 0.842 | 43.85 |

| disturbance | 0.000 | 0.000 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 8.047 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.644 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.030 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `13.0` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.354 |
| **P (Period/Due Date)** | 0.163 |
| **K (Conflict)** | 0.002 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=50 with rho_global=0.800 suggests horizon≈208.333 (was 238.095). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 1551,
  "disturbances": 1551,
  "dynamic_world": 1551,
  "ptimes": 1551,
  "routing": 1551
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)