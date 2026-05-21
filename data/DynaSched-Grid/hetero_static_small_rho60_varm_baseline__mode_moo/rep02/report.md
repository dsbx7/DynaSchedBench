
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `9e5a672e1d1c`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:56:55.122129+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.625 | 4.23 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.832 | 2.89 |

| scv_a | 1.000 | 1.040 | 3.99 |

| scv_p | 1.000 | 1.013 | 1.35 |

| disturbance | 0.050 | 0.050 | 0.17 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 15.299 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.207 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.124 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `14.2` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.449 |
| **P (Period/Due Date)** | 0.062 |
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
  "arrivals": 4080,
  "disturbances": 4080,
  "dynamic_world": 4080,
  "ptimes": 4080,
  "routing": 4080
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)