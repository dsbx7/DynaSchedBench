
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `8eeaaeb066ec`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:58:06.450266+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.700 | 0.693 | 1.04 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.762 | 4.31 |

| scv_a | 2.000 | 1.844 | 7.82 |

| scv_p | 2.000 | 2.184 | 9.21 |

| disturbance | 0.200 | 0.204 | 2.08 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 6.795 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.210 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.050 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `15.1` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.330 |
| **P (Period/Due Date)** | 0.063 |
| **K (Conflict)** | 0.003 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.700 suggests horizon≈571.429 (was 952.381). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3775,
  "disturbances": 3775,
  "dynamic_world": 3775,
  "ptimes": 3775,
  "routing": 3775
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)