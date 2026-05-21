from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from .Base import BaseAgent


class SPTAgent(BaseAgent):
    """A simple Shortest Processing Time (SPT) heuristic agent.
    
    At each decision point, the agent reads ``ready_ops`` from the observation,
    ranks legal actions by the processing time of the corresponding job's next
    operation, and chooses the shortest one. The observation already carries the
    ``process_time`` field for each ready operation, so the rule does not depend
    on additional environment helper methods.
    """

    def __init__(self) -> None:
        self._last_choice: Optional[Dict[str, Any]] = None
        self._step: int = 0
        logger.info("SPTAgent initialized")

    def reset(self, scenario_info: Dict[str, Any] | None = None) -> None:  # noqa: D401
        """Reset the heuristic (no internal state to clear)."""
        self._last_choice = None
        self._step = 0
        try:
            keys = list((scenario_info or {}).keys())[:10]
        except Exception:
            keys = []
        logger.info(
            "SPTAgent reset: scenario_info_keys={} (truncated)",
            keys,
        )

    def act(
        self,
        obs: Dict[str, Any],
        legal_actions: List[Dict[str, Any]],
        env: Any,
    ) -> Optional[Dict[str, Any]]:
        if not legal_actions:
            logger.debug("SPTAgent.act called with no legal actions")
            return None

        self._step += 1

        ready_ops = obs.get("ready_ops", []) or []
        current_time = None
        try:
            current_time = float(obs.get("time", 0.0))
        except Exception:
            current_time = None
        logger.debug(
            "SPTAgent.act: step={} time={} n_ready_ops={} n_legal_actions={}",
            self._step,
            current_time,
            len(ready_ops),
            len(legal_actions),
        )
        # Map job_id -> process_time for the *next* operation
        pt_by_job: Dict[str, float] = {}
        for ro in ready_ops:
            jid = str(ro.get("job_id"))
            pt = float(ro.get("process_time", 0.0))
            if jid not in pt_by_job or pt < pt_by_job[jid]:
                pt_by_job[jid] = pt

        best_action: Optional[Dict[str, Any]] = None
        best_pt = float("inf")
        for a in legal_actions:
            jid = str(a.get("job_id"))
            pt = pt_by_job.get(jid, float("inf"))
            if pt < best_pt:
                best_pt = pt
                best_action = a

        if best_action is None:
            logger.debug(
                "SPTAgent.act: no best_action found from ready_ops; falling back to first legal action",
            )
            best_action = legal_actions[0]

        try:
            sel_jid = str(best_action.get("job_id"))
        except Exception:
            sel_jid = "<unknown>"
        logger.debug(
            "SPTAgent.act: selected job_id={} best_pt={}",
            sel_jid,
            best_pt,
        )

        self._last_choice = best_action
        return best_action
