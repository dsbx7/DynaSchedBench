
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `c7a83b6ace19`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:57:55.748488+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.614 | 2.31 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 1.500 | 1.498 | 0.16 |

| scv_a | 0.500 | 0.525 | 4.94 |

| scv_p | 0.500 | 0.494 | 1.24 |

| disturbance | 0.050 | 0.050 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 37.654 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.668 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.121 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `20.4` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.588 |
| **P (Period/Due Date)** | 0.168 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.600 suggests horizon≈1020.036 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2315,
  "disturbances": 2315,
  "dynamic_world": 2315,
  "ptimes": 2315,
  "routing": 2315
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)