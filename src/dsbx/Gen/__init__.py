"""Instance generation utilities for dsbx."""

from __future__ import annotations

import inspect
from typing import Any

from pydantic import BaseModel

from dsbx.Gen.core.constructor import FastPathConstructor
from dsbx.Gen.core.seed import SeedManager
from dsbx.Gen.io.dsl import load_input_model
from dsbx.Gen.models.inputs import InputModel
from dsbx.Gen.pipeline import run_generation_pipeline

try:  # pragma: no cover - defensive compatibility for older Pydantic releases
    _sig_model_dump_json = inspect.signature(BaseModel.model_dump_json)
    if "ensure_ascii" not in _sig_model_dump_json.parameters:
        _orig_model_dump_json = BaseModel.model_dump_json

        def _patched_model_dump_json(
            self: BaseModel,
            *args: Any,
            ensure_ascii: bool | None = None,
            **kwargs: Any,
        ) -> str:
            return _orig_model_dump_json(self, *args, **kwargs)

        BaseModel.model_dump_json = _patched_model_dump_json  # type: ignore[assignment]
except Exception:
    pass

__all__ = [
    "FastPathConstructor",
    "InputModel",
    "SeedManager",
    "load_input_model",
    "run_generation_pipeline",
]
