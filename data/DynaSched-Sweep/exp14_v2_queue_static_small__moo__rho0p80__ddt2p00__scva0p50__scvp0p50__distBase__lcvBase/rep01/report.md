
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `d113ecd23912`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T13:02:15.033698+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.800 | 0.778 | 2.81 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 2.000 | 1.951 | 2.45 |

| scv_a | 0.500 | 0.494 | 1.17 |

| scv_p | 0.500 | 0.556 | 11.29 |

| disturbance | 0.000 | 0.000 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 5.331 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.513 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.030 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `10.9` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.297 |
| **P (Period/Due Date)** | 0.136 |
| **K (Conflict)** | 0.002 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=50 with rho_global=0.800 suggests horizon≈208.333 (was 238.095). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 1554,
  "disturbances": 1554,
  "dynamic_world": 1554,
  "ptimes": 1554,
  "routing": 1554
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)