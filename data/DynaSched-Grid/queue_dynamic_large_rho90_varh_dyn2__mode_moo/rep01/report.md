
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `048c23a4a5dc`
- **Generator Version**: `0.2.0`
- **Generation Timestamp**: `2025-12-18T14:53:03.458589+00:00`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|

| rho_global | 0.900 | 0.928 | 3.11 |

| rho_bottleneck | 0.000 | 0.000 | 0.00 |

| ddt | 4.976 | 3.843 | 22.76 |

| scv_a | 2.000 | 3.343 | 67.15 |

| scv_p | 2.000 | 2.042 | 2.09 |

| disturbance | 0.200 | 0.181 | 9.60 |


## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | 47.583 | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | 0.260 | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | 0.080 | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | 0.200 | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `22.9` / 100 (easy)

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | 0.625 |
| **P (Period/Due Date)** | 0.076 |
| **K (Conflict)** | 0.004 |
| **S (Stochastic)** | 0.211 |

---

## Feasibility & Projections


The following automatic projections were applied to ensure a feasible instance:

- `E_RATE_MATCH: jobs_total=1000 with rho_global=0.900 suggests horizon≈1388.889 (was 4761.905). Projected horizon to match targets.`



## Reproducibility

To reproduce this exact instance, use the following seed map and version `0.2.0`.

```json
{
  "arrivals": 3737,
  "disturbances": 3737,
  "dynamic_world": 3737,
  "ptimes": 3737,
  "routing": 3737
}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)