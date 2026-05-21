
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `f5605379fd9f`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:38:51.692631+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.581 | 3.22 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.262 | 5.75 |

| scv_a | 1.000 | 1.029 | 2.89 |

| scv_p | 1.000 | 1.005 | 0.45 |

| disturbance | 0.200 | 0.203 | 1.30 |

| load_cv | 0.300 | 0.328 | 9.27 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 10.579 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.190 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.123 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `16.7` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.394 |
| **P (Period/Due Date)** | 0.057 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.600 suggests horizon≈1020.036 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2761,
  "disturbances": 2761,
  "dynamic_world": 2761,
  "ptimes": 2761,
  "routing": 2761
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)