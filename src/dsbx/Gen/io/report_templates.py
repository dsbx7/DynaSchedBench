REPORT_MD_TEMPLATE = """
# DJSS Bench Generation Report

## Summary

- **Instance Hash**: `{{ input_hash[:12] }}`
- **Generator Version**: `{{ version }}`
- **Generation Timestamp**: `{{ generation_timestamp }}`

## Target vs. Observed Metrics

| Metric       | Target | Observed | Error (%) |
|--------------|--------|----------|-----------|
{% for name, value in target_metrics.items() %}
| {{ name }} | {{ "%.3f"|format(value) }} | {{ "%.3f"|format(observed_metrics.get(name, 0.0)) }} | {{ "%.2f"|format(errors.get(name, 0.0) * 100) }} |
{% endfor %}

## Structural Stress Index (SSI) - Difficulty Scale

This section quantifies the intrinsic difficulty of the generated instance, independent of any scheduling algorithm.

| Stress Index | Value | Interpretation |
|--------------|-------|----------------|
| **C (Congestion)** | {{ "%.3f"|format(ssi.get('C', 0.0)) }} | Measures queuing pressure from load and variability. (>3 is high stress) |
| **P (Period/Due Date)** | {{ "%.3f"|format(ssi.get('P', 0.0)) }} | Measures due date tightness. (>1 implies high lateness risk) |
| **K (Conflict)** | {{ "%.3f"|format(ssi.get('K', 0.0)) }} | (Placeholder) Measures routing contention. |
| **S (Stochastic)** | {{ "%.3f"|format(ssi.get('S', 0.0)) }} | (Placeholder) Measures disruption from breakdowns, etc. |

- **Overall Difficulty Score**: `{{ "%.1f"|format(difficulty_score) }}` / 100 ({{ difficulty_category }})

### Normalized SSI (0-1)

| Stress Index | Normalized (0-1) |
|--------------|------------------|
| **C (Congestion)** | {{ "%.3f"|format(ssi_norm.get('C', 0.0)) }} |
| **P (Period/Due Date)** | {{ "%.3f"|format(ssi_norm.get('P', 0.0)) }} |
| **K (Conflict)** | {{ "%.3f"|format(ssi_norm.get('K', 0.0)) }} |
| **S (Stochastic)** | {{ "%.3f"|format(ssi_norm.get('S', 0.0)) }} |

---
{% if comparison_report %}
## Explainable Comparison Report

{{ comparison_report }}
{% endif %}
## Feasibility & Projections

{% if projections %}
The following automatic projections were applied to ensure a feasible instance:
{% for proj in projections %}
- `{{ proj }}`
{% endfor %}
{% else %}
All input targets were within the feasible envelope. No projections were needed.
{% endif %}

## Reproducibility

To reproduce this exact instance, use the following seed map and version `{{ version }}`.

```json
{{ seed_map | tojson(indent=2) }}
```

## Instance Dynamics Visualization

The following chart visualizes the evolution of key metrics over the simulation horizon.

![Instance Time Series Metrics](time_series.png)
"""