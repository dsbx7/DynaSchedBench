"""dsbx.Eval

Evaluation utilities for dynamic scheduling trajectories.

This package starts with a lightweight trajectory representation that can be
produced by environments and simulators, and will be extended with
constraints and metric computation utilities.
"""

from __future__ import annotations

from .Trajectory import StepRecord, Trajectory  # noqa: F401

__all__ = ["StepRecord", "Trajectory"]
