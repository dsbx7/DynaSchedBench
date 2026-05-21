from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import random

from loguru import logger

from dsbx.Agents.Base import BaseAgent


class DEAgent(BaseAgent):
    def __init__(
        self,
        population_size: int = 16,
        generations: int = 8,
        mutation_scale: float = 0.5,
        crossover_prob: float = 0.9,
        rollout_steps: int = 0,
        random_seed: Optional[int] = None,
    ) -> None:
        self.population_size = max(4, int(population_size))
        self.generations = max(1, int(generations))
        self.mutation_scale = float(mutation_scale)
        self.crossover_prob = float(crossover_prob)
        self.rollout_steps = max(0, int(rollout_steps))

        if random_seed is not None:
            random.seed(random_seed)

        self._best_weights: Optional[List[float]] = None

    def reset(self, scenario_info: Dict[str, Any] | None = None) -> None:
        self._best_weights = None

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
        size = len(population)
        fitness: List[float] = [float("-inf")] * size

        best_weights: Optional[List[float]] = None
        best_fitness: Optional[float] = None

        def eval_ind(idx: int) -> float:
            if fitness[idx] != float("-inf"):
                return fitness[idx]
            w = population[idx]
            f = self._evaluate_individual(w, actions, features_by_action, env)
            fitness[idx] = f
            return f

        for _ in range(self.generations):
            new_population: List[List[float]] = []
            new_fitness: List[float] = []

            for i in range(size):
                idxs = list(range(size))
                idxs.remove(i)
                if len(idxs) < 3:
                    base = list(population[i])
                    trial = list(base)
                else:
                    a, b, c = random.sample(idxs, 3)
                    base = population[a]
                    vec_b = population[b]
                    vec_c = population[c]

                    mutant: List[float] = []
                    for xb, xc in zip(vec_b, vec_c):
                        mutant.append(0.0 + self.mutation_scale * (xb - xc))

                    trial: List[float] = []
                    j_rand = random.randrange(dim)
                    for j in range(dim):
                        if random.random() < self.crossover_prob or j == j_rand:
                            trial.append(mutant[j])
                        else:
                            trial.append(population[i][j])

                f_target = eval_ind(i)
                f_trial = self._evaluate_individual(trial, actions, features_by_action, env)

                if f_trial >= f_target:
                    new_population.append(trial)
                    new_fitness.append(f_trial)
                    f_use = f_trial
                    w_use = trial
                else:
                    new_population.append(list(population[i]))
                    new_fitness.append(f_target)
                    f_use = f_target
                    w_use = population[i]

                if best_fitness is None or f_use > best_fitness:
                    best_fitness = f_use
                    best_weights = list(w_use)

            population = new_population
            fitness = new_fitness

        if best_weights is None:
            logger.warning("DEAgent: no valid fitness evaluated, falling back to SPT heuristic.")
            return self._fallback_spt(obs, legal_actions)

        self._best_weights = list(best_weights)
        return self._select_action_with_weights(best_weights, actions, features_by_action)

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
            logger.warning("DEAgent: evaluation failed with error: {}", exc)
            score = 0.0
        return score

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

    def _init_population(self, dim: int) -> List[List[float]]:
        pop: List[List[float]] = []

        if self._best_weights is not None and len(self._best_weights) == dim:
            pop.append(list(self._best_weights))

        while len(pop) < self.population_size:
            ind = [random.uniform(-1.0, 1.0) for _ in range(dim)]
            pop.append(ind)
        return pop

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
