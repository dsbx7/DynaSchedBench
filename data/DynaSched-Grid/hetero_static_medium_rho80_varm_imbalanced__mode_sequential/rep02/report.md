
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `458be1c2363d`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:53:08.753091+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.807 | 0.88 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.911 | 1.31 |

| scv_a | 1.000 | 1.033 | 3.34 |

| scv_p | 1.000 | 1.098 | 9.83 |

| disturbance | 0.050 | 0.050 | 0.00 |

| load_cv | 0.400 | 0.399 | 0.37 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 101.229 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.204 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.117 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `21.6` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.744 |
| **P (Period/Due Date)** | 0.061 |
| **K (Conflict)** | 0.006 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=200 with rho_global=0.800 suggests horizon≈765.027 (was 1107.468). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 4041,
  "disturbances": 4041,
  "dynamic_world": 4041,
  "ptimes": 4041,
  "routing": 4041
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)