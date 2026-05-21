
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `f0564afe8076`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:20:00.651957+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.700 | 0.638 | 8.85 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 1.487 | 70.12 |

| scv_a | 1.000 | 10.005 | 900.51 |

| scv_p | 1.000 | 2.006 | 100.60 |

| disturbance | 0.200 | 0.212 | 6.19 |

| load_cv | 0.200 | 0.407 | 103.51 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 343.147 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.673 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.115 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `33.1` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.940 |
| **P (Period/Due Date)** | 0.169 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.700 suggests horizon≈874.317 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3611,
  "disturbances": 3611,
  "dynamic_world": 3611,
  "ptimes": 3611,
  "routing": 3611
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)