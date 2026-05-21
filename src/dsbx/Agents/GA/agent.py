from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import math
import random

from loguru import logger

from dsbx.Agents.Base import BaseAgent


class GAAgent(BaseAgent):
    def __init__(
        self,
        population_size: int = 16,
        generations: int = 8,
        crossover_prob: float = 0.8,
        mutation_prob: float = 0.2,
        mutation_sigma: float = 0.5,
        rollout_steps: int = 0,
        random_seed: Optional[int] = None,
    ) -> None:
        self.population_size = max(4, int(population_size))
        self.generations = max(1, int(generations))
        self.crossover_prob = float(crossover_prob)
        self.mutation_prob = float(mutation_prob)
        self.mutation_sigma = float(mutation_sigma)
        self.rollout_steps = max(0, int(rollout_steps))

        if random_seed is not None:
            random.seed(random_seed)

        # Best weights carried across decision steps as a warm start
        self._best_weights: Optional[List[float]] = None

    def reset(self, scenario_info: Dict[str, Any] | None = None) -> None:
        self._best_weights = None

    # ------------------------------------------------------------------
    # Core GA-based decision
    # ------------------------------------------------------------------
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

        population = self._init_population(dim)
        fitness: List[float] = []
        best_weights: Optional[List[float]] = None
        best_fitness: Optional[float] = None

        for g in range(self.generations):
            fitness = []
            for w in population:
                f = self._evaluate_individual(w, actions, features_by_action, env)
                fitness.append(f)
                if best_fitness is None or f > best_fitness:
                    best_fitness = f
                    best_weights = list(w)

            if best_weights is None:
                break

            population = self._next_generation(population, fitness)

        if best_weights is None:
            logger.warning("GAAgent: no valid fitness evaluated, falling back to SPT heuristic.")
            return self._fallback_spt(obs, legal_actions)

        self._best_weights = list(best_weights)
        return self._select_action_with_weights(best_weights, actions, features_by_action)

    # ------------------------------------------------------------------
    # Feature extraction and evaluation
    # ------------------------------------------------------------------
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

    def _evaluate_individual(
        self,
        weights: List[float],
        actions: List[Dict[str, Any]],
        features_by_action: List[List[float]],
        env: Any,
    ) -> float:
        act = self._select_action_with_weights(weights, actions, features_by_action)

        try:
            if self.rollout_steps > 0 and hasattr(env, "quick_rollout_score"):
                score = float(env.quick_rollout_score(act, steps=self.rollout_steps))
            else:
                score = float(env.estimate_action_score(act))
        except Exception as exc:
            logger.warning("GAAgent: evaluation failed with error: {}", exc)
            score = 0.0
        return score

    def _select_action_with_weights(
        self,
        weights: List[float],
        actions: List[Dict[str, Any]],
        features_by_action: List[List[float]],
    ) -> Dict[str, Any]:
        best_idx = 0
        best_score = None
        for i, feats in enumerate(features_by_action):
            s = 0.0
            for w, f in zip(weights, feats):
                s += w * f
            if best_score is None or s < best_score:
                best_score = s
                best_idx = i
        return actions[best_idx]

    # ------------------------------------------------------------------
    # GA operators
    # ------------------------------------------------------------------
    def _init_population(self, dim: int) -> List[List[float]]:
        pop: List[List[float]] = []

        if self._best_weights is not None and len(self._best_weights) == dim:
            pop.append(list(self._best_weights))

        while len(pop) < self.population_size:
            ind = [random.uniform(-1.0, 1.0) for _ in range(dim)]
            pop.append(ind)
        return pop

    def _next_generation(self, population: List[List[float]], fitness: List[float]) -> List[List[float]]:
        size = len(population)
        if size == 0:
            return population

        elite_idx = max(range(size), key=lambda i: fitness[i])
        new_pop: List[List[float]] = [list(population[elite_idx])]

        def tournament() -> List[float]:
            i, j = random.randrange(size), random.randrange(size)
            if fitness[i] >= fitness[j]:
                return list(population[i])
            return list(population[j])

        while len(new_pop) < size:
            parent1 = tournament()
            parent2 = tournament()

            if random.random() < self.crossover_prob:
                child1, child2 = self._crossover(parent1, parent2)
            else:
                child1, child2 = parent1, parent2

            self._mutate(child1)
            if len(new_pop) < size:
                new_pop.append(child1)
            if len(new_pop) < size:
                self._mutate(child2)
                new_pop.append(child2)

        return new_pop

    def _crossover(self, p1: List[float], p2: List[float]) -> Tuple[List[float], List[float]]:
        if len(p1) != len(p2) or len(p1) <= 1:
            return list(p1), list(p2)

        point = random.randrange(1, len(p1))
        c1 = p1[:point] + p2[point:]
        c2 = p2[:point] + p1[point:]
        return c1, c2

    def _mutate(self, ind: List[float]) -> None:
        for i in range(len(ind)):
            if random.random() < self.mutation_prob:
                noise = random.gauss(0.0, self.mutation_sigma)
                ind[i] += noise

    # ------------------------------------------------------------------
    # Fallback heuristic
    # ------------------------------------------------------------------
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
