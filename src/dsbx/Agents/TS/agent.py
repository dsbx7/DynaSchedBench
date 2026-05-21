from __future__ import annotations

from typing import Any, Dict, List, Optional
import math
import random

from loguru import logger

from dsbx.Agents.Base import BaseAgent


class TSAgent(BaseAgent):
    def __init__(
        self,
        max_iterations: int = 64,
        tabu_tenure: int = 5,
        rollout_steps: int = 0,
        random_seed: Optional[int] = None,
    ) -> None:
        self.max_iterations = max(1, int(max_iterations))
        self.tabu_tenure = max(1, int(tabu_tenure))
        self.rollout_steps = max(0, int(rollout_steps))

        if random_seed is not None:
            random.seed(random_seed)

    def reset(self, scenario_info: Dict[str, Any] | None = None) -> None:
        return

    def act(
        self,
        obs: Dict[str, Any],
        legal_actions: List[Dict[str, Any]],
        env: Any,
    ) -> Optional[Dict[str, Any]]:
        if not legal_actions:
            return None

        if not (hasattr(env, "estimate_action_score") or hasattr(env, "quick_rollout_score")):
            return self._fallback_spt(obs, legal_actions)

        n = len(legal_actions)
        if n == 1:
            return legal_actions[0]

        value_cache: Dict[int, float] = {}

        def eval_action(idx: int) -> float:
            if idx in value_cache:
                return value_cache[idx]
            act = legal_actions[idx]
            try:
                if self.rollout_steps > 0 and hasattr(env, "quick_rollout_score"):
                    v = float(env.quick_rollout_score(act, steps=self.rollout_steps))
                else:
                    v = float(env.estimate_action_score(act))
            except Exception as exc:
                logger.warning("TSAgent: evaluation failed with error: {}", exc)
                v = 0.0
            value_cache[idx] = v
            return v

        current_idx = random.randrange(n)
        current_val = eval_action(current_idx)
        best_idx = current_idx
        best_val = current_val

        tabu_list: List[int] = []

        for _ in range(self.max_iterations):
            best_move_idx: Optional[int] = None
            best_move_val: Optional[float] = None

            for i in range(n):
                v = eval_action(i)

                if i in tabu_list and not (best_val is None or v > best_val):
                    continue

                if best_move_idx is None or v > best_move_val:  # type: ignore[operator]
                    best_move_idx = i
                    best_move_val = v

            if best_move_idx is None:
                break

            current_idx = best_move_idx
            current_val = best_move_val if best_move_val is not None else current_val

            if current_val > best_val:
                best_val = current_val
                best_idx = current_idx

            tabu_list.append(current_idx)
            if len(tabu_list) > self.tabu_tenure:
                tabu_list.pop(0)

        return legal_actions[best_idx]

    def _fallback_spt(
        self,
        obs: Dict[str, Any],
        legal_actions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        ready = obs.get("ready_ops", []) or []
        pt_by_job: Dict[str, float] = {}
        for ro in ready:
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
            best_action = legal_actions[0]
        return best_action
