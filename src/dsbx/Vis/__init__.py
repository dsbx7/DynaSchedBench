"""dsbx.Vis

Visualization utilities for DynaSchedBench trajectories and metrics.

This package provides a small set of plotting helpers:

- Gantt charts from a :class:`Trajectory`
- Metric curves from metrics JSON or trajectory objects

The goal is to offer *good defaults* while keeping the API simple and
script-friendly.
"""

from __future__ import annotations

from .Gantt import plot_gantt_from_trajectory  # noqa: F401
from .JobGantt import plot_job_gantt_from_trajectory  # noqa: F401
from .MetricsCurves import plot_metric_over_time  # noqa: F401

__all__ = [
    "plot_gantt_from_trajectory",
    "plot_job_gantt_from_trajectory",
    "plot_metric_over_time",
]
