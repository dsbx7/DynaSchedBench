
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `649a494f98cc`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:58:07.696653+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.849 | 6.14 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.915 | 1.22 |

| scv_a | 1.000 | 1.101 | 10.13 |

| scv_p | 1.000 | 1.317 | 31.72 |

| disturbance | 0.050 | 0.050 | 0.00 |

| load_cv | 0.200 | 0.377 | 88.45 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 108.254 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.203 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.117 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `21.9` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.755 |
| **P (Period/Due Date)** | 0.061 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=100 with rho_global=0.800 suggests horizon≈382.514 (was 737.705). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 4139,
  "disturbances": 4139,
  "dynamic_world": 4139,
  "ptimes": 4139,
  "routing": 4139
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)