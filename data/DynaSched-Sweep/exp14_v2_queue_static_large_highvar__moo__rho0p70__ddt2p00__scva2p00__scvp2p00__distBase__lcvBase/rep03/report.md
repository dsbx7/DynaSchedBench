
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `152be27d12e7`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T13:35:33.456856+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.700 | 0.667 | 4.78 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 2.000 | 2.085 | 4.24 |

| scv_a | 2.000 | 1.894 | 5.29 |

| scv_p | 2.000 | 1.969 | 1.53 |

| disturbance | 0.000 | 0.000 | 0.00 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 5.861 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.480 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.080 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.000 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `11.1` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.310 |
| **P (Period/Due Date)** | 0.129 |
| **K (Conflict)** | 0.004 |
| **S (Stochastic)** | 0.000 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.700 suggests horizon≈1785.714 (was 4761.905). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 1891,
  "disturbances": 1891,
  "dynamic_world": 1891,
  "ptimes": 1891,
  "routing": 1891
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)