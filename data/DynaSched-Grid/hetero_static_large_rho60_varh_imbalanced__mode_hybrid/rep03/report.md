
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `72179d3dd8dd`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T15:17:43.793716+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.600 | 0.586 | 2.34 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 5.180 | 4.09 |

| scv_a | 2.000 | 1.971 | 1.46 |

| scv_p | 2.000 | 2.098 | 4.91 |

| disturbance | 0.050 | 0.050 | 0.00 |

| load_cv | 0.400 | 0.388 | 3.11 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 60.306 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.193 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.300 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.050 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `19.7` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.662 |
| **P (Period/Due Date)** | 0.058 |
| **K (Conflict)** | 0.015 |
| **S (Stochastic)** | 0.053 |

---

## Feasibility & Projections


All input targets were within the feasible envelope. No projections were needed.


## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3859,
  "disturbances": 3859,
  "dynamic_world": 3859,
  "ptimes": 3859,
  "routing": 3859
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)