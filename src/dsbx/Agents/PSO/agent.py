from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import random

from loguru import logger

from dsbx.Agents.Base import BaseAgent


class PSOAgent(BaseAgent):
    def __init__(
        self,
        swarm_size: int = 16,
        iterations: int = 8,
        inertia: float = 0.7,
        cognitive_coeff: float = 1.5,
        social_coeff: float = 1.5,
        rollout_steps: int = 0,
        random_seed: Optional[int] = None,
    ) -> None:
        self.swarm_size = max(4, int(swarm_size))
        self.iterations = max(1, int(iterations))
        self.inertia = float(inertia)
        self.cognitive_coeff = float(cognitive_coeff)
        self.social_coeff = float(social_coeff)
        self.rollout_steps = max(0, int(rollout_steps))

        if random_seed is not None:
            random.seed(random_seed)

        self._gbest_weights: Optional[List[float]] = None

    def reset(self, scenario_info: Dict[str, Any] | None = None) -> None:
        self._gbest_weights = None

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

        features_by_action, actions = self._extract_action_features(obs, legal_actions)
        if not actions:
            return legal_actions[0]

        dim = len(features_by_action[0])

        positions, velocities = self._init_swarm(dim)
        swarm_size = len(positions)

        pbest_pos: List[List[float]] = [list(p) for p in positions]
        pbest_fit: List[float] = [float("-inf")] * swarm_size

        gbest_pos: Optional[List[float]] = list(self._gbest_weights) if self._gbest_weights is not None else None
        gbest_fit: Optional[float] = None

        def eval_weights(w: List[float]) -> float:
            act = self._select_action_with_weights(w, actions, features_by_action)
            try:
                if self.rollout_steps > 0 and hasattr(env, "quick_rollout_score"):
                    score = float(env.quick_rollout_score(act, steps=self.rollout_steps))
                else:
                    score = float(env.estimate_action_score(act))
            except Exception as exc:
                logger.warning("PSOAgent: evaluation failed with error: {}", exc)
                score = 0.0
            return score

        for i in range(swarm_size):
            f = eval_weights(positions[i])
            pbest_fit[i] = f
            if gbest_fit is None or f > gbest_fit:
                gbest_fit = f
                gbest_pos = list(positions[i])

        if gbest_pos is None:
            return self._fallback_spt(obs, legal_actions)

        for _ in range(self.iterations):
            for i in range(swarm_size):
                x = positions[i]
                v = velocities[i]
                p = pbest_pos[i]

                new_v: List[float] = []
                new_x: List[float] = []
                for j in range(dim):
                    r1 = random.random()
                    r2 = random.random()
                    cognitive = self.cognitive_coeff * r1 * (p[j] - x[j])
                    social = self.social_coeff * r2 * (gbest_pos[j] - x[j])  # type: ignore[index]
                    vj = self.inertia * v[j] + cognitive + social
                    xj = x[j] + vj
                    new_v.append(vj)
                    new_x.append(xj)

                velocities[i] = new_v
                positions[i] = new_x

                f = eval_weights(new_x)
                if f > pbest_fit[i]:
                    pbest_fit[i] = f
                    pbest_pos[i] = list(new_x)
                if gbest_fit is None or f > gbest_fit:
                    gbest_fit = f
                    gbest_pos = list(new_x)

        if gbest_pos is None:
            logger.warning("PSOAgent: no valid fitness evaluated, falling back to SPT heuristic.")
            return self._fallback_spt(obs, legal_actions)

        self._gbest_weights = list(gbest_pos)
        return self._select_action_with_weights(gbest_pos, actions, features_by_action)

    def _extract_action_features(
        self,
        obs: Dict[str, Any],
        legal_actions: List[Dict[str, Any]],
    ) -> Tuple[List[List[float]], List[Dict[str, Any]]]:
        ready = obs.get("ready_ops", []) or []
        machines = obs.get("machines", {}) or {}
        dyn = obs.get("dynamic_summary", {}) or {}
        emergency_jobs = set(dyn.get("emergency_jobs") or []) if isinstance(dyn, dict) else set()

        ready_by_job: Dict[str, Dict[str, Any]] = {}
        for ro in ready:
            jid = str(ro.get("job_id"))
            if jid not in ready_by_job:
                ready_by_job[jid] = ro

        features_by_action: List[List[float]] = []
        actions: List[Dict[str, Any]] = []

        for a in legal_actions:
            jid = str(a.get("job_id"))
            ro = ready_by_job.get(jid, {})

            pt = float(ro.get("process_time", 0.0))
            rem_work = float(ro.get("remaining_work", 0.0))
            rem_ops = float(ro.get("remaining_ops", 0))
            flex = float(ro.get("flexibility", 1.0))
            priority = float(ro.get("priority", 0.0))
            is_emerg = 1.0 if jid in emergency_jobs else 0.0

            machine_candidates = a.get("machine_candidates") or []
            if machines and machine_candidates:
                earliest_free = min(float(machines.get(str(m_id), 0.0)) for m_id in machine_candidates)
            else:
                earliest_free = 0.0

            f_vec = [
                pt,
                rem_work,
                rem_ops,
                flex,
                priority,
                earliest_free,
                is_emerg,
            ]

            features_by_action.append(f_vec)
            actions.append(a)

        return features_by_action, actions

    def _select_action_with_weights(
        self,
        weights: List[float],
        actions: List[Dict[str, Any]],
        features_by_action: List[List[float]],
    ) -> Dict[str, Any]:
        best_idx = 0
        best_score: Optional[float] = None
        for i, feats in enumerate(features_by_action):
            s = 0.0
            for w, f in zip(weights, feats):
                s += w * f
            if best_score is None or s < best_score:
                best_score = s
                best_idx = i
        return actions[best_idx]

    def _init_swarm(self, dim: int) -> Tuple[List[List[float]], List[List[float]]]:
        positions: List[List[float]] = []
        velocities: List[List[float]] = []

        if self._gbest_weights is not None and len(self._gbest_weights) == dim:
            positions.append(list(self._gbest_weights))
            velocities.append([0.0 for _ in range(dim)])

        while len(positions) < self.swarm_size:
            pos = [random.uniform(-1.0, 1.0) for _ in range(dim)]
            vel = [0.0 for _ in range(dim)]
            positions.append(pos)
            velocities.append(vel)
        return positions, velocities

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
