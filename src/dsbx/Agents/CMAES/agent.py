from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import math
import random

import numpy as np
from loguru import logger

from dsbx.Agents.Base import BaseAgent


class CMAESAgent(BaseAgent):
    """CMA-ES-like continuous optimizer over action scoring weights.
    
    At each decision point, the agent treats action-feature weights as
    continuous variables, searches for a weight vector with a diagonal
    covariance CMA-ES variant, and scores the current legal actions with it.
    """

    def __init__(
        self,
        population_size: int = 16,
        generations: int = 8,
        sigma0: float = 0.5,
        rollout_steps: int = 0,
        random_seed: Optional[int] = None,
    ) -> None:
        self.population_size = max(4, int(population_size))
        self.generations = max(1, int(generations))
        self.sigma0 = float(sigma0)
        self.rollout_steps = max(0, int(rollout_steps))

        if random_seed is not None:
            random.seed(random_seed)
            np.random.seed(random_seed)

        self._best_mean: Optional[List[float]] = None

    def reset(self, scenario_info: Dict[str, Any] | None = None) -> None:
        self._best_mean = None

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

        lam = self.population_size
        mu = max(1, lam // 2)
        weights = np.log(mu + 0.5) - np.log(np.arange(1, mu + 1))
        weights = weights / np.sum(weights)
        mu_eff = float(1.0 / np.sum(weights ** 2))

        c_sigma = (mu_eff + 2.0) / (dim + mu_eff + 5.0)
        d_sigma = 1.0 + 2.0 * max(0.0, math.sqrt((mu_eff - 1.0) / (dim + 1.0)) - 1.0) + c_sigma
        c_c = (4.0 + mu_eff / dim) / (dim + 4.0 + 2.0 * mu_eff / dim)
        c1 = 2.0 / ((dim + 1.3) ** 2 + mu_eff)
        c_mu = min(1.0 - c1, 2.0 * (mu_eff - 2.0 + 1.0 / mu_eff) / ((dim + 2.0) ** 2 + mu_eff))

        chi_n = math.sqrt(dim) * (1.0 - 1.0 / (4.0 * dim) + 1.0 / (21.0 * dim * dim))

        if self._best_mean is not None and len(self._best_mean) == dim:
            m = np.array(self._best_mean, dtype=float)
        else:
            m = np.zeros(dim, dtype=float)
        sigma = float(self.sigma0)

        C_diag = np.ones(dim, dtype=float)
        p_sigma = np.zeros(dim, dtype=float)
        p_c = np.zeros(dim, dtype=float)

        best_x: Optional[np.ndarray] = None
        best_fit: Optional[float] = None

        def eval_weights(w: np.ndarray) -> float:
            act = self._select_action_with_weights(w.tolist(), actions, features_by_action)
            try:
                if self.rollout_steps > 0 and hasattr(env, "quick_rollout_score"):
                    score = float(env.quick_rollout_score(act, steps=self.rollout_steps))
                else:
                    score = float(env.estimate_action_score(act))
            except Exception as exc:
                logger.warning("CMAESAgent: evaluation failed with error: {}", exc)
                score = 0.0
            return score

        for g in range(self.generations):
            zs = np.random.randn(lam, dim)
            sqrt_C = np.sqrt(C_diag)[None, :]
            ys = zs * sqrt_C
            xs = m[None, :] + sigma * ys

            fits = []
            for k in range(lam):
                f = eval_weights(xs[k])
                fits.append(f)
                if best_fit is None or f > best_fit:
                    best_fit = f
                    best_x = xs[k].copy()

            fits_arr = np.array(fits, dtype=float)
            idx_sorted = np.argsort(fits_arr)[::-1]

            idx_mu = idx_sorted[:mu]
            ys_mu = np.sum(weights[:, None] * ys[idx_mu], axis=0)

            m = m + sigma * ys_mu

            C_inv_sqrt = 1.0 / np.sqrt(C_diag)
            p_sigma = (1.0 - c_sigma) * p_sigma + math.sqrt(c_sigma * (2.0 - c_sigma) * mu_eff) * (C_inv_sqrt * ys_mu)

            norm_p_sigma = float(np.linalg.norm(p_sigma))
            h_thresh = (1.4 + 2.0 / (dim + 1.0)) * chi_n
            h_sigma = 1.0 if norm_p_sigma / math.sqrt(1.0 - (1.0 - c_sigma) ** (2.0 * (g + 1.0))) < h_thresh else 0.0

            p_c = (1.0 - c_c) * p_c + h_sigma * math.sqrt(c_c * (2.0 - c_c) * mu_eff) * ys_mu

            C_diag = (1.0 - c1 - c_mu) * C_diag + c1 * (p_c * p_c + (1.0 - h_sigma) * c_c * (2.0 - c_c) * C_diag)
            C_diag += c_mu * np.sum(weights[:, None] * (ys[idx_mu] ** 2), axis=0)
            C_diag = np.maximum(C_diag, 1e-12)

            sigma *= math.exp((c_sigma / d_sigma) * (norm_p_sigma / chi_n - 1.0))
            sigma = float(min(max(sigma, 1e-8), 5.0))

        if best_x is None:
            logger.warning("CMAESAgent: no valid fitness evaluated, falling back to SPT heuristic.")
            return self._fallback_spt(obs, legal_actions)

        self._best_mean = best_x.tolist()
        return self._select_action_with_weights(self._best_mean, actions, features_by_action)

    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
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
