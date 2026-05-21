
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `687b47ea2e2f`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T13:01:30.499807+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.600 | 0.08 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 2.500 | 2.344 | 6.24 |

| scv_a | 1.500 | 1.280 | 14.67 |

| scv_p | 0.500 | 0.353 | 29.31 |

| disturbance | 0.000 | 0.000 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 2.720 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.427 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.030 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `8.2` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.211 |
| **P (Period/Due Date)** | 0.117 |
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
  "arrivals": 1528,
  "disturbances": 1528,
  "dynamic_world": 1528,
  "ptimes": 1528,
  "routing": 1528
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)