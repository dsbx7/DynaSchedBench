from __future__ import annotations

from typing import Protocol, Dict, Any, List, Optional


class BaseAgent(Protocol):
    """Minimal agent interface for dsbx.

    The design is intentionally light-weight: agents receive the current
    observation, the list of legal actions and a reference to the
    environment, and return either a selected action or ``None`` to indicate
    that no decision is taken (e.g. let the environment advance time).
    """

    def reset(self, scenario_info: Dict[str, Any] | None = None) -> None:
        """Reset any internal state for a new episode/scenario."""

    def act(
        self,
        obs: Dict[str, Any],
        legal_actions: List[Dict[str, Any]],
        env: Any,
    ) -> Optional[Dict[str, Any]]:
        """Choose an action from the legal action set.

        Parameters
        ----------
        obs:
            The observation dictionary returned by the environment.
        legal_actions:
            A list of legal actions; each action is expected to have at least
            ``job_id`` and ``machine_group`` fields (and optionally
            ``machine_candidates``).
        env:
            The environment instance; agents may use helper methods such as
            ``estimate_action_score`` or ``quick_rollout_score``.
        """

        raise NotImplementedError
