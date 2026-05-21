"""Agent interfaces and lightweight baselines for dsbx."""

from __future__ import annotations

from dsbx.Agents.Base import BaseAgent
from dsbx.Agents.Heuristics import SPTAgent
from dsbx.Agents.Random import RandomAgent

try:
    from dsbx.Agents.LLMCoder import AsyncDualStreamAgent
except ImportError:  # pragma: no cover - optional LLM dependencies
    AsyncDualStreamAgent = None  # type: ignore[assignment]

try:
    from dsbx.Agents.LLMScheduler import LlmPolicyAgent
except ImportError:  # pragma: no cover - optional LLM dependencies
    LlmPolicyAgent = None  # type: ignore[assignment]

__all__ = ["BaseAgent", "RandomAgent", "SPTAgent"]
if AsyncDualStreamAgent is not None:
    __all__.append("AsyncDualStreamAgent")
if LlmPolicyAgent is not None:
    __all__.append("LlmPolicyAgent")
