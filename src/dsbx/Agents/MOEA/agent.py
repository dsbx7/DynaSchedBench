from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import random

from loguru import logger

from dsbx.Agents.Base import BaseAgent


class MOEAAgent(BaseAgent):
    """MOEA/D-style decomposition-based multi-objective EA over actions.
    
    At each decision point, the current legal actions form the search space.
    The objectives combine immediate action quality from
    ``env.estimate_action_score`` and a short-horizon rollout score. Random
    weight vectors decompose the objectives into scalar subproblems; the agent
    solves those subproblems over the discrete action set and executes the best
    scalarized action.
    """

    def __init__(
        self,
        population_size: int = 16,
        generations: int = 4,
        mutation_prob: float = 0.3,
        rollout_steps: int = 4,
        random_seed: Optional[int] = None,
    ) -> None:
        self.population_size = max(4, int(population_size))
        self.generations = max(1, int(generations))
        self.mutation_prob = float(mutation_prob)
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

        obj_cache: Dict[int, Tuple[float, float]] = {}

        def eval_action(idx: int) -> Tuple[float, float]:
            if idx in obj_cache:
                return obj_cache[idx]
            act = legal_actions[idx]
            try:
                f1 = float(env.estimate_action_score(act))
            except Exception as exc:
                logger.warning("MOEAAgent: estimate_action_score failed: {}", exc)
                f1 = 0.0
            if self.rollout_steps > 0 and hasattr(env, "quick_rollout_score"):
                try:
                    f2 = float(env.quick_rollout_score(act, steps=self.rollout_steps))
                except Exception as exc:
                    logger.warning("MOEAAgent: quick_rollout_score failed: {}", exc)
                    f2 = f1
            else:
                f2 = f1
            obj_cache[idx] = (f1, f2)
            return f1, f2

        for i in range(n):
            eval_action(i)

        vals1 = [obj_cache[i][0] for i in range(n)]
        vals2 = [obj_cache[i][1] for i in range(n)]
        min1, max1 = min(vals1), max(vals1)
        min2, max2 = min(vals2), max(vals2)
        span1 = (max1 - min1) or 1.0
        span2 = (max2 - min2) or 1.0

        best_idx: Optional[int] = None
        best_scalar: Optional[float] = None

        for _ in range(self.generations):
            for _ in range(self.population_size):
                w1 = random.random()
                w2 = 1.0 - w1

                local_best_idx: Optional[int] = None
                local_best_val: Optional[float] = None

                for i in range(n):
                    f1, f2 = obj_cache[i]
                    s = w1 * ((f1 - min1) / span1) + w2 * ((f2 - min2) / span2)
                    if local_best_val is None or s > local_best_val:
                        local_best_val = s
                        local_best_idx = i

                if local_best_idx is not None and local_best_val is not None:
                    if best_scalar is None or local_best_val > best_scalar:
                        best_scalar = local_best_val
                        best_idx = local_best_idx

        if best_idx is None:
            return legal_actions[random.randrange(n)]
        return legal_actions[best_idx]

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    def _init_population(self, n_actions: int) -> List[int]:
        pop: List[int] = []
        while len(pop) < self.population_size:
            pop.append(random.randrange(n_actions))
        return pop

    def _non_dominated_sort(
        self,
        indices: List[int],
        objs: Dict[int, Tuple[float, float]],
    ) -> List[List[int]]:
        S: Dict[int, List[int]] = {}
        n_dom: Dict[int, int] = {}
        fronts: List[List[int]] = [[]]

        for p in indices:
            S[p] = []
            n_dom[p] = 0
            fp1, fp2 = objs[p]
            for q in indices:
                if p == q:
                    continue
                fq1, fq2 = objs[q]
                if (fp1 >= fq1 and fp2 >= fq2) and (fp1 > fq1 or fp2 > fq2):
                    S[p].append(q)
                elif (fq1 >= fp1 and fq2 >= fp2) and (fq1 > fp1 or fq2 > fp2):
                    n_dom[p] += 1
            if n_dom[p] == 0:
                fronts[0].append(p)

        i = 0
        while i < len(fronts) and fronts[i]:
            next_front: List[int] = []
            for p in fronts[i]:
                for q in S[p]:
                    n_dom[q] -= 1
                    if n_dom[q] == 0:
                        next_front.append(q)
            i += 1
            if next_front:
                fronts.append(next_front)
        return fronts

    def _crowding_distance(
        self,
        front: List[int],
        objs: Dict[int, Tuple[float, float]],
    ) -> Dict[int, float]:
        if not front:
            return {}
        distance: Dict[int, float] = {i: 0.0 for i in front}
        for m in range(2):
            front_sorted = sorted(front, key=lambda i: objs[i][m])
            distance[front_sorted[0]] = float("inf")
            distance[front_sorted[-1]] = float("inf")
            min_m = objs[front_sorted[0]][m]
            max_m = objs[front_sorted[-1]][m]
            span = (max_m - min_m) or 1.0
            for i in range(1, len(front_sorted) - 1):
                prev_i = front_sorted[i - 1]
                next_i = front_sorted[i + 1]
                distance[front_sorted[i]] += (objs[next_i][m] - objs[prev_i][m]) / span
        return distance

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
