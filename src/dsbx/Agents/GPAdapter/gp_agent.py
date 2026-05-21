from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from dsbx.Agents.Base import BaseAgent
from dsbx.Sim.Snapshot import JobSnapshot, Snapshot

from .features import _build_queue_stats, build_jobshop_attributes
from .lisp_rule import LispRule


@dataclass
class _Candidate:
    action: Dict[str, Any]
    job: JobSnapshot


class GPAgent(BaseAgent):
    """GP-rule-based dispatching agent for dsbx.

    This agent:
    - Takes a GP-evolved rule in Lisp form (same syntax as yimei.util.lisp.LispParser);
    - At each decision point, scores each legal action's job-operation using the
      rule with attributes approximated from the current Snapshot;
    - Selects the action with the lowest priority value (aligned with
      AbstractRule / SPT / LPT semantics in the original GP code base).

    The agent does **not** run GP evolution itself; it only evaluates a fixed
    rule, thus fully respecting the original algorithmic idea while adapting
    the state representation to dsbx.
    """

    def __init__(self, rule_expr: str) -> None:
        if not rule_expr or not isinstance(rule_expr, str):
            raise ValueError("GPAgent requires a non-empty Lisp rule expression string.")

        self._rule_expr = rule_expr
        self._rule = LispRule.from_lisp(rule_expr)

        self._step: int = 0

    # ------------------------------------------------------------------
    # BaseAgent API
    # ------------------------------------------------------------------
    def reset(self, scenario_info: Dict[str, Any] | None = None) -> None:  # noqa: D401
        """Reset internal counters for a new episode."""

        self._step = 0
        try:
            keys = list((scenario_info or {}).keys())[:10]
        except Exception:
            keys = []
        logger.info(
            "GPAgent.reset: scenario_info_keys={} (truncated)",
            keys,
        )

    def act(
        self,
        obs: Dict[str, Any],
        legal_actions: List[Dict[str, Any]],
        env: Any,
    ) -> Optional[Dict[str, Any]]:
        if not legal_actions:
            logger.debug("GPAgent.act: no legal_actions; returning None")
            return None

        try:
            self._step += 1
        except Exception:
            self._step = 1

        try:
            snap = env.get_snapshot()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("GPAgent.act: failed to get snapshot at step={}: {}", self._step, exc)
            return legal_actions[0]

        if not isinstance(snap, Snapshot):
            logger.warning(
                "GPAgent.act: env.get_snapshot() did not return Snapshot at step={}; got {}",
                self._step,
                type(snap),
            )
            return legal_actions[0]

        jobs_by_id: Dict[str, JobSnapshot] = {str(j.job_id): j for j in snap.jobs}

        candidates: List[_Candidate] = []
        for act in legal_actions:
            jid = str(act.get("job_id"))
            job = jobs_by_id.get(jid)
            if job is None:
                continue
            candidates.append(_Candidate(action=act, job=job))

        if not candidates:
            logger.warning(
                "GPAgent.act: no candidates matched jobs in snapshot at step={}; falling back to first legal action",
                self._step,
            )
            return legal_actions[0]

        queue_stats = _build_queue_stats(snap)

        best_score = float("inf")
        best_action: Optional[Dict[str, Any]] = None

        for cand in candidates:
            job = cand.job
            try:
                op_index = int(getattr(job, "current_op_index", 0))
            except Exception:
                op_index = 0
            if op_index < 0 or op_index >= len(job.ops):
                continue
            op = job.ops[op_index]

            machine_group = str(cand.action.get("machine_group"))

            attrs = build_jobshop_attributes(
                snapshot=snap,
                job=job,
                op=op,
                machine_group=machine_group,
                queue_stats=queue_stats,
            )

            score = self._rule.evaluate(attrs)

            if score < best_score:
                best_score = score
                best_action = cand.action

        if best_action is None:
            logger.warning(
                "GPAgent.act: no best_action found at step={}; falling back to first legal action",
                self._step,
            )
            return legal_actions[0]

        try:
            jid = str(best_action.get("job_id"))
        except Exception:
            jid = "<unknown>"

        logger.debug(
            "GPAgent.act: step={} selected job_id={} best_score={}",
            self._step,
            jid,
            best_score,
        )

        return best_action


__all__ = [
    "GPAgent",
]
