
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `fe09b8cccdd4`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T13:11:02.172467+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.909 | 0.95 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 2.000 | 1.991 | 0.44 |

| scv_a | 1.000 | 0.952 | 4.83 |

| scv_p | 1.000 | 1.104 | 10.37 |

| disturbance | 0.000 | 0.000 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 20.149 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.502 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.080 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `15.7` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.491 |
| **P (Period/Due Date)** | 0.134 |
| **K (Conflict)** | 0.004 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.900 suggests horizon≈1388.889 (was 4761.905). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 1835,
  "disturbances": 1835,
  "dynamic_world": 1835,
  "ptimes": 1835,
  "routing": 1835
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)