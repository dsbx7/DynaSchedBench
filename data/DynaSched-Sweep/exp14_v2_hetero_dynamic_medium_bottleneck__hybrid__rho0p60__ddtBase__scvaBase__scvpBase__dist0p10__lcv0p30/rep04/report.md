
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `8e0eb4aea1da`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:41:56.689103+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.592 | 1.30 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.795 | 3.63 |

| scv_a | 1.000 | 1.019 | 1.87 |

| scv_p | 1.000 | 1.064 | 6.38 |

| disturbance | 0.100 | 0.106 | 6.31 |

| load_cv | 0.300 | 0.279 | 7.02 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 5.559 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.209 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.122 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.100 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `11.9` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.303 |
| **P (Period/Due Date)** | 0.062 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.105 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.600 suggests horizon≈1020.036 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2792,
  "disturbances": 2792,
  "dynamic_world": 2792,
  "ptimes": 2792,
  "routing": 2792
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)