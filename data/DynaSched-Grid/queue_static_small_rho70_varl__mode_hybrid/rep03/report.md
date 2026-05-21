
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `2ffc8330bc70`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T16:28:15.224398+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.700 | 0.682 | 2.54 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 4.875 | 2.04 |

| scv_a | 0.250 | 0.265 | 5.96 |

| scv_p | 0.250 | 0.207 | 17.29 |

| disturbance | 0.000 | 0.000 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 2.653 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.205 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.030 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `6.8` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.208 |
| **P (Period/Due Date)** | 0.061 |
| **K (Conflict)** | 0.002 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


All input targets were within the feasible envelope. No projections were needed.


## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 4363,
  "disturbances": 4363,
  "dynamic_world": 4363,
  "ptimes": 4363,
  "routing": 4363
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)