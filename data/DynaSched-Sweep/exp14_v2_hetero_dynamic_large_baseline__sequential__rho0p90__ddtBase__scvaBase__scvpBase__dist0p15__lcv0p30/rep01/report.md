
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `63e6bccc70cb`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:44:34.111539+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.837 | 7.04 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.772 | 4.10 |

| scv_a | 2.000 | 1.964 | 1.79 |

| scv_p | 2.000 | 2.096 | 4.80 |

| disturbance | 0.150 | 0.160 | 6.68 |

| load_cv | 0.300 | 0.287 | 4.30 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 148.479 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.210 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.150 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `26.0` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.805 |
| **P (Period/Due Date)** | 0.062 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.158 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.900 suggests horizon≈2941.176 (was 4411.765). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 2859,
  "disturbances": 2859,
  "dynamic_world": 2859,
  "ptimes": 2859,
  "routing": 2859
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)