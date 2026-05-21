
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `97e566e42a03`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:16:20.602082+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.700 | 0.701 | 0.08 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.042 | 1.33 |

| scv_a | 1.000 | 0.932 | 6.82 |

| scv_p | 1.000 | 0.821 | 17.88 |

| disturbance | 0.100 | 0.106 | 6.15 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 91.947 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.198 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.112 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `22.5` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.729 |
| **P (Period/Due Date)** | 0.059 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.700 suggests horizon≈874.317 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3588,
  "disturbances": 3588,
  "dynamic_world": 3588,
  "ptimes": 3588,
  "routing": 3588
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)