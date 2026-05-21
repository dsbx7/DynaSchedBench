
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `312bf821a2fe`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:58:07.183202+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.929 | 3.17 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 3.048 | 38.74 |

| scv_a | 2.000 | 1.970 | 1.50 |

| scv_p | 2.000 | 2.245 | 12.23 |

| disturbance | 0.100 | 0.120 | 20.48 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 40.370 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.328 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.050 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `20.0` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.599 |
| **P (Period/Due Date)** | 0.093 |
| **K (Conflict)** | 0.003 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.900 suggests horizon≈444.444 (was 952.381). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3798,
  "disturbances": 3798,
  "dynamic_world": 3798,
  "ptimes": 3798,
  "routing": 3798
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)