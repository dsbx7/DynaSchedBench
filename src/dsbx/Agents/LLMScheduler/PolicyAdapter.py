from __future__ import annotations

from typing import Any, Dict, List, Optional

from .policy import LLMPolicy

from dsbx.Agents.Base import BaseAgent


class LlmPolicyAgent(BaseAgent):
    """Thin adapter that lets an existing :class:`LLMPolicy` act as a BaseAgent.

    The underlying LLMPolicy is expected to follow the API defined in
    ``algorithms.llm_scheduler.policy.LLMPolicy`` and will be used as-is.
    """

    def __init__(self, policy: LLMPolicy) -> None:
        self.policy = policy

    def reset(self, scenario_info: Dict[str, Any] | None = None) -> None:  # noqa: D401
        """Reset the internal stats of the wrapped LLMPolicy."""

        # LLMPolicy.stats is a plain dict; resetting to empty is sufficient.
        try:
            self.policy.stats.clear()
        except Exception:
            # Be defensive: if stats isn't mutable for some reason, ignore.
            pass

    def act(
        self,
        obs: Dict[str, Any],
        legal_actions: List[Dict[str, Any]],
        env: Any,
    ) -> Optional[Dict[str, Any]]:
        return self.policy.decide(obs, legal_actions, env)

    def get_stats(self) -> Dict[str, Any]:  # noqa: D401
        """Return a shallow copy of the wrapped policy's stats dictionary."""

        try:
            data = dict(self.policy.stats)
        except Exception:
            data = {}
        return data
