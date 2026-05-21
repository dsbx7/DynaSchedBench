
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `ed047ada105a`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T12:55:40.560786+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.400 | 0.401 | 0.29 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 1.500 | 1.464 | 2.43 |

| scv_a | 0.500 | 0.517 | 3.37 |

| scv_p | 1.500 | 1.425 | 5.01 |

| disturbance | 0.000 | 0.000 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 1.320 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.683 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.030 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `7.7` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.135 |
| **P (Period/Due Date)** | 0.171 |
| **K (Conflict)** | 0.002 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=50 with rho_global=0.400 suggests horizon≈416.667 (was 238.095). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 1243,
  "disturbances": 1243,
  "dynamic_world": 1243,
  "ptimes": 1243,
  "routing": 1243
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)