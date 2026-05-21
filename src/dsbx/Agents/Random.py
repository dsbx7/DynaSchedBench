from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from loguru import logger

from dsbx.Agents.Base import BaseAgent


class RandomAgent(BaseAgent):
    def __init__(self, random_seed: Optional[int] = None):
        self._seed = random_seed
        self._rng = random.Random(random_seed)
        self._step: int = 0

        logger.info("RandomAgent initialized with random_seed={}", random_seed)

    def reset(self, scenario_info: Dict[str, Any] | None = None) -> None:
        self._step = 0
        if self._seed is not None:
            self._rng = random.Random(self._seed)
        else:
            self._rng = random.Random()

    def act(
        self,
        obs: Dict[str, Any],
        legal_actions: List[Dict[str, Any]],
        env: Any,
    ) -> Optional[Dict[str, Any]]:
        if not legal_actions:
            return None

        self._step += 1
        base_action = dict(self._rng.choice(legal_actions))

        mc = base_action.get("machine_candidates")
        if isinstance(mc, list) and mc:
            mid = self._rng.choice(mc)
            base_action["machine_id"] = mid

        return base_action
