
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `80bae07b4d0f`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:58:05.077928+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.700 | 0.706 | 0.90 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.803 | 3.49 |

| scv_a | 1.000 | 0.959 | 4.06 |

| scv_p | 1.000 | 1.572 | 57.24 |

| disturbance | 0.100 | 0.121 | 21.02 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 5.450 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.208 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.050 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `11.7` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.300 |
| **P (Period/Due Date)** | 0.062 |
| **K (Conflict)** | 0.003 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.700 suggests horizon≈571.429 (was 952.381). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3785,
  "disturbances": 3785,
  "dynamic_world": 3785,
  "ptimes": 3785,
  "routing": 3785
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)