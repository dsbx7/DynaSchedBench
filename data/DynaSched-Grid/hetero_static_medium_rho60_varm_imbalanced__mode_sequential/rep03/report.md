
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `658358216d05`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:48:50.854643+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.578 | 3.63 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.094 | 2.38 |

| scv_a | 1.000 | 0.957 | 4.27 |

| scv_p | 1.000 | 1.202 | 20.17 |

| disturbance | 0.050 | 0.050 | 0.00 |

| load_cv | 0.400 | 0.474 | 18.60 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 54.817 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.196 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.118 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `19.1` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.647 |
| **P (Period/Due Date)** | 0.059 |
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
  "arrivals": 3988,
  "disturbances": 3988,
  "dynamic_world": 3988,
  "ptimes": 3988,
  "routing": 3988
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)