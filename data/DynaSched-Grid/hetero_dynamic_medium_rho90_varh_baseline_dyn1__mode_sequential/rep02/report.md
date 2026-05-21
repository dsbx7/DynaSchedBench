
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `cb6b5ed59ec4`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:18:01.951409+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.874 | 2.89 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.164 | 3.78 |

| scv_a | 2.000 | 2.027 | 1.34 |

| scv_p | 2.000 | 1.871 | 6.43 |

| disturbance | 0.100 | 0.105 | 4.76 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 144.503 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.194 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.122 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `24.3` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.801 |
| **P (Period/Due Date)** | 0.058 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.900 suggests horizon≈680.024 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3618,
  "disturbances": 3618,
  "dynamic_world": 3618,
  "ptimes": 3618,
  "routing": 3618
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)