
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `a04e99908b5c`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T13:06:25.203738+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.577 | 3.83 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 1.500 | 1.508 | 0.51 |

| scv_a | 0.500 | 0.503 | 0.56 |

| scv_p | 0.500 | 0.487 | 2.68 |

| disturbance | 0.000 | 0.000 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 2.039 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.663 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.030 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `8.7` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.179 |
| **P (Period/Due Date)** | 0.167 |
| **K (Conflict)** | 0.002 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=50 with rho_global=0.600 suggests horizon≈277.778 (was 238.095). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 1657,
  "disturbances": 1657,
  "dynamic_world": 1657,
  "ptimes": 1657,
  "routing": 1657
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)