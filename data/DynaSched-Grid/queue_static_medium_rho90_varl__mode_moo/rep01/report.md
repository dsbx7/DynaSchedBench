
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `e6b35287f5fc`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:26:34.239586+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.885 | 1.67 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.951 | 0.51 |

| scv_a | 0.250 | 0.244 | 2.47 |

| scv_p | 0.250 | 0.252 | 0.82 |

| disturbance | 0.000 | 0.000 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 9.598 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.202 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.050 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `11.1` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.380 |
| **P (Period/Due Date)** | 0.060 |
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
  "arrivals": 4304,
  "disturbances": 4304,
  "dynamic_world": 4304,
  "ptimes": 4304,
  "routing": 4304
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)