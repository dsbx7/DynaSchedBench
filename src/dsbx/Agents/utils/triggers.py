from __future__ import annotations

from collections import deque
from typing import Deque


class StepTrigger:
    """Simple trigger based on global decision step count.
    
    The implementation is intentionally conservative: it fires only after at
    least ``min_steps_between_updates`` decision points and avoids environment
    internals so it can be reused across scenarios.
    """

    def __init__(self, min_steps_between_updates: int = 500) -> None:
        self._min_steps = max(1, int(min_steps_between_updates))
        self._last_trigger_step = 0

    def reset(self) -> None:
        self._last_trigger_step = 0

    def should_trigger(self, global_step: int) -> bool:
        if global_step <= 0:
            return False
        if global_step - self._last_trigger_step < self._min_steps:
            return False
        self._last_trigger_step = global_step
        return True


class PerformanceTrigger:
    def __init__(self, window: int = 100, min_relative_change: float = 0.2) -> None:
        self._window = max(1, int(window))
        self._min_rel_change = max(0.0, float(min_relative_change))
        self._values: Deque[float] = deque()

    def reset(self) -> None:
        self._values.clear()

    def update(self, metric_value: float) -> None:
        try:
            v = float(metric_value)
        except Exception:
            return
        if not (v > float("-inf") and v < float("inf")):
            return
        self._values.append(v)
        while len(self._values) > self._window:
            self._values.popleft()

    def should_trigger(self, global_step: int) -> bool:
        if global_step <= 0:
            return False
        if len(self._values) < 2:
            return False
        current = self._values[-1]
        best = max(self._values)
        if best <= 0.0:
            return False
        rel_drop = (best - current) / abs(best)
        return rel_drop >= self._min_rel_change
