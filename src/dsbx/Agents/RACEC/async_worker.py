from __future__ import annotations

import math
import os
import random
import queue
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import Any, Dict, Optional, List
from concurrent.futures import ThreadPoolExecutor

from loguru import logger

from dsbx.Agents.utils import LLMClient
from dsbx.Gen import InputModel
from dsbx.Agents.LLMScheduler.logger import TrajectoryLogger
from dsbx.Eval.Metrics import METRIC_ALL_KEYS

from .config import LLMCoderConfig
from .rules import PriorityRule, RuleWithMeta
from .coder import LLMCoder
from .sandbox_eval import evaluate_candidate_rule, EvalEventsPool
from .repository import RuleRepository
from .meta import MetaConfigAdvisor
from .explanation import build_rule_explanation, RefactorAgent
from .agentic import PlannerAgent, CriticAgent, TaskMemory, CandidateRecord
from .evolutionary import CrossoverOperator, MutationOperator
from .population import PopulationManager
from .feedback import FeedbackHistory
from .baseline_heuristics import BaselineHeuristicLibrary


@dataclass
class CoderTask:
    model: InputModel
    baseline_rule: PriorityRule
    model_summary: Dict[str, Any]
    obs_example: Dict[str, Any]
    baseline_name: str
    step: int


_VALID_METRICS_SET = {str(x) for x in METRIC_ALL_KEYS}


def _parse_objective_metrics(raw: Any, *, fallback_metric: str) -> List[str]:
    focus: List[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                focus.append(item.strip())
            elif isinstance(item, (int, float)):
                focus.append(str(item))
    elif isinstance(raw, str):
        parts = [p.strip() for p in raw.replace(";", ",").split(",")]
        focus.extend([p for p in parts if p])
    filtered: List[str] = []
    seen: set[str] = set()
    for m in focus:
        if not m:
            continue
        if m not in _VALID_METRICS_SET:
            continue
        if m in seen:
            continue
        seen.add(m)
        filtered.append(m)
    if not filtered:
        return [str(fallback_metric)]
    return filtered


def _select_objective_metric(
    model: InputModel,
    cfg: LLMCoderConfig,
    step: int,
    *,
    iteration: int = 0,
) -> str:
    fallback = str(getattr(cfg, "objective_metric", "makespan"))
    metrics = _parse_objective_metrics(getattr(cfg, "objective_metrics", None), fallback_metric=fallback)
    if len(metrics) <= 1:
        return metrics[0]
    try:
        meta = getattr(model, "meta", None)
        base_seed = int(getattr(meta, "seed", 0) or 0)
    except Exception:
        base_seed = 0
    rng = random.Random(int(base_seed) + int(step) + int(iteration))
    return str(rng.choice(metrics))


class AsyncCoderWorker:
    def __init__(self, llm_client: LLMClient, cfg: LLMCoderConfig) -> None:
        self._cfg = cfg
        self._llm_client = llm_client
        self._task_q: "queue.Queue[CoderTask]" = queue.Queue(maxsize=1)
        self._ready_q: "queue.Queue[RuleWithMeta]" = queue.Queue()
        self._coder = LLMCoder(llm_client, cfg)
        self._planner = PlannerAgent(llm_client, cfg)
        self._critic = CriticAgent(llm_client, cfg)
        self._n_tasks_processed = 0
        self._n_candidates_total = 0
        self._n_candidates_valid = 0
        self._n_eval_calls = 0
        self._n_rules_selected = 0
        self._n_rules_repo_added = 0
        self._last_best_eval: Dict[str, Any] = {}
        self._next_candidate_index: int = 0
        traj_dir = (os.getenv("DYNA_SCHEDBENCH_LLM_DEBUG_DIR") or "").strip()
        traj_path = Path(traj_dir) / "worker_trajectory.jsonl" if traj_dir else None
        self._traj_logger = TrajectoryLogger(file_path=traj_path)
        self._eval_events_pool: Optional[EvalEventsPool] = None
        repo_path = getattr(cfg, "repository_path", None)
        use_repo = bool(getattr(cfg, "use_repository", True))
        self._repo = RuleRepository(path=repo_path) if use_repo else None
        use_meta = bool(getattr(cfg, "use_meta_advisor", True))
        self._meta = MetaConfigAdvisor() if use_meta else None
        self._refactor = RefactorAgent(llm_client, cfg)
        
        # Initialize evolutionary operators
        self._crossover_operator: Optional[CrossoverOperator] = None
        self._mutation_operator: Optional[MutationOperator] = None
        self._population_manager: Optional[PopulationManager] = None
        self._generation = 0
        
        if getattr(cfg, "enable_evolution", True):
            self._crossover_operator = CrossoverOperator(llm_client, cfg)
            self._mutation_operator = MutationOperator(llm_client, cfg)
            max_pop_size = int(getattr(cfg, "max_population_size", 50))
            min_diversity = float(getattr(cfg, "min_diversity_threshold", 0.3))
            self._population_manager = PopulationManager(
                max_size=max_pop_size,
                min_diversity=min_diversity
            )
            logger.info(
                "AsyncCoderWorker: evolutionary operators initialized (max_pop_size={}, min_diversity={})",
                max_pop_size,
                min_diversity
            )
        
        self._running = True
        self._thread = Thread(target=self._loop, daemon=True)
        logger.info("LLMCoder worker: starting background thread")
        self._thread.start()

    def reset(self) -> None:
        try:
            while True:
                self._task_q.get_nowait()
        except queue.Empty:
            pass
        try:
            while True:
                self._ready_q.get_nowait()
        except queue.Empty:
            pass
        self._n_tasks_processed = 0
        self._n_candidates_total = 0
        self._n_candidates_valid = 0
        self._n_eval_calls = 0
        self._n_rules_selected = 0
        self._n_rules_repo_added = 0
        self._last_best_eval = {}
        self._next_candidate_index = 0

    def submit_task(self, task: CoderTask) -> bool:
        if not self._cfg.enable_codegen:
            return False
        try:
            self._task_q.put(task, block=False)
            logger.info(
                f"LLMCoder worker: accepted task at step={task.step} baseline={task.baseline_name}"
            )
            return True
        except queue.Full:
            return False

    def poll_ready_rule(self) -> Optional[RuleWithMeta]:
        try:
            return self._ready_q.get_nowait()
        except queue.Empty:
            return None

    def _loop(self) -> None:
        while self._running:
            try:
                task = self._task_q.get(timeout=0.5)
            except queue.Empty:
                continue
            self._n_tasks_processed += 1
            try:
                logger.debug(
                    "LLMCoder worker: picked up task at step={} baseline='{}'",
                    task.step,
                    task.baseline_name,
                )
                self._handle_task(task)
            except Exception as e:  # pragma: no cover - defensive
                logger.error(f"LLMCoder worker: unexpected error while handling task: {e}")

    def _handle_task(self, task: CoderTask) -> None:
        try:
            if self._meta is not None:
                self._meta.tune_inplace(task.model_summary, self._cfg)
        except Exception as exc:
            logger.warning("AsyncCoderWorker: meta.tune_inplace failed: {}", exc)
        max_iter = int(getattr(self._cfg, "agentic_max_iterations", 1))
        if max_iter <= 1:
            self._handle_task_single_pass(task)
        else:
            self._handle_task_agentic(task, max_iter)

    def _handle_task_single_pass(self, task: CoderTask) -> None:
        metric_main = _select_objective_metric(task.model, self._cfg, task.step, iteration=0)
        candidates = self._coder.build_candidates(
            model_summary=task.model_summary,
            obs_example=task.obs_example,
            baseline_name=task.baseline_name,
            objective_metric=metric_main,
        )
        num_candidates = len(candidates)
        self._n_candidates_total += num_candidates
        if not candidates:
            logger.warning("LLMCoder worker: no valid candidate rule generated")
            return
        if not self._cfg.enable_eval:
            best = self._select_best_by_complexity(candidates)
            logger.info(
                "LLMCoder worker: enable_eval=False, selecting rule '{}' by minimal complexity",
                best.name,
            )
            self._n_candidates_valid += num_candidates
            self._n_rules_selected += 1
            self._ready_q.put(best)
            return
        best_rule: Optional[RuleWithMeta] = None
        best_res = None
        best_score = float("-inf")
        events_pool = self._get_or_create_eval_pool(task.model)
        max_parallel = int(getattr(self._cfg, "eval_max_parallel_candidates", 0) or 0)
        if max_parallel > 1 and num_candidates > 1:
            max_workers = min(max_parallel, num_candidates)
            logger.debug(
                "LLMCoder worker: evaluating {} candidates in parallel with {} workers (single_pass)",
                num_candidates,
                max_workers,
            )
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(
                        evaluate_candidate_rule,
                        model=task.model,
                        baseline_rule=task.baseline_rule,
                        candidate_rule=cand.rule,
                        candidate_code=(cand.rule.info.get("code") if isinstance(getattr(cand.rule, "info", None), dict) else None),
                        cfg=self._cfg,
                        events_pool=events_pool,
                        objective_metric=metric_main,
                    )
                    for cand in candidates
                ]
            self._n_eval_calls += num_candidates
            results: List[Optional[Any]] = [f.result() for f in futures]
            cand_iter = zip(candidates, results)
        else:
            cand_iter = []
            for cand in candidates:
                self._n_eval_calls += 1
                cand_code = None
                try:
                    info = getattr(cand.rule, "info", None)
                    if isinstance(info, dict):
                        cand_code = info.get("code")
                except Exception:
                    cand_code = None
                res = evaluate_candidate_rule(
                    model=task.model,
                    baseline_rule=task.baseline_rule,
                    candidate_rule=cand.rule,
                    candidate_code=cand_code,
                    cfg=self._cfg,
                    events_pool=events_pool,
                    objective_metric=metric_main,
                )
                cand_iter.append((cand, res))
        for cand, res in cand_iter:
            eval_dict: Dict[str, Any] = {}
            if res is not None:
                eval_dict = {
                    "baseline_value": res.baseline_value,
                    "candidate_value": res.candidate_value,
                    "relative_improvement": res.relative_improvement,
                    "accepted": res.accepted,
                    "episodes_used": getattr(res, "episodes_used", 0),
                    "effect_size": getattr(res, "effect_size", 0.0),
                }
            if res is None or not res.accepted:
                logger.info(
                    "LLMCoder worker: candidate '{}' rejected by sandbox eval",
                    cand.name,
                )
                self._append_log(
                    {
                        "event": "candidate_evaluated",
                        "mode": "single_pass",
                        "step": task.step,
                        "baseline_name": task.baseline_name,
                        "candidate": {
                            "name": cand.name,
                            "eval": eval_dict,
                            "accepted": False,
                        },
                    }
                )
                continue
            self._n_candidates_valid += 1
            info = dict(cand.info)
            complexity_score = self._extract_complexity_score_from_info(info)
            normalized_complexity = math.log1p(max(complexity_score, 0.0))
            score = float(res.relative_improvement) - float(self._cfg.complexity_weight) * normalized_complexity
            logger.info(
                "LLMCoder worker: candidate '{}' accepted by sandbox eval (rel_improve={:.6f}, complexity_score={:.6f}, normalized_complexity={:.6f}, combined_score={:.6f})",
                cand.name,
                res.relative_improvement,
                complexity_score,
                normalized_complexity,
                score,
            )
            self._append_log(
                {
                    "event": "candidate_evaluated",
                    "mode": "single_pass",
                    "step": task.step,
                    "baseline_name": task.baseline_name,
                    "candidate": {
                        "name": cand.name,
                        "eval": eval_dict,
                        "accepted": True,
                        "complexity_score": complexity_score,
                        "normalized_complexity": normalized_complexity,
                        "combined_score": score,
                    },
                }
            )
            if score > best_score:
                best_score = score
                best_res = res
                best_rule = RuleWithMeta(rule=cand.rule, name=cand.name, info=info)
        logger.debug(
            "LLMCoder worker: after evaluation loop best_rule={} best_score={:.6f}",
            getattr(best_rule, "name", None),
            best_score,
        )
        if best_rule is None or best_res is None:
            logger.info("LLMCoder worker: all candidate rules rejected by sandbox eval")
            self._append_log(
                {
                    "event": "rule_search_failed",
                    "mode": "single_pass",
                    "step": task.step,
                    "baseline_name": task.baseline_name,
                }
            )
            return
        self._finalize_and_enqueue_best(task, best_rule, best_res, best_score, agentic_summary=None)

    def _get_baseline_code(self, baseline_name: str, baseline_rule: PriorityRule) -> Optional[str]:
        """Get baseline strategy code from repository or BaselineHeuristicLibrary.
        
        Args:
            baseline_name: Name of the baseline rule
            baseline_rule: The baseline rule object
            
        Returns:
            Python code string for the baseline strategy, or None if not found
        """
        # First, try to get code from the baseline rule's info (if it came from repository)
        try:
            info = getattr(baseline_rule, "info", None)
            if isinstance(info, dict):
                code = info.get("code")
                if isinstance(code, str) and code.strip():
                    logger.debug(
                        "AsyncCoderWorker: retrieved baseline code from rule info for '{}'",
                        baseline_name
                    )
                    return code
        except Exception:
            pass
        
        # Second, try to get from BaselineHeuristicLibrary
        code = BaselineHeuristicLibrary.get_heuristic_code(baseline_name)
        if code:
            logger.debug(
                "AsyncCoderWorker: retrieved baseline code from BaselineHeuristicLibrary for '{}'",
                baseline_name
            )
            return code
        
        logger.debug(
            "AsyncCoderWorker: no baseline code found for '{}'",
            baseline_name
        )
        return None

    def _handle_task_agentic(self, task: CoderTask, max_iter: int) -> None:
        if not self._cfg.enable_eval:
            self._handle_task_single_pass(task)
            return
        
        # Create feedback history for this task
        try:
            feedback_history = FeedbackHistory(
                max_history=int(getattr(self._cfg, "feedback_history_size", 10))
            )
        except Exception as exc:
            logger.error("LLMCoder worker: failed to create feedback history: {}", exc)
            feedback_history = None
        
        memory = TaskMemory()
        history: Dict[str, Any] = {}
        best_rule: Optional[RuleWithMeta] = None
        best_res = None
        best_score = float("-inf")
        
        # Get baseline code for planner
        baseline_code = self._get_baseline_code(task.baseline_name, task.baseline_rule)
        
        for it in range(max_iter):
            memory.iteration = it
            metric_main = _select_objective_metric(task.model, self._cfg, task.step, iteration=it)
            try:
                plans = self._planner.plan_strategies(
                    model_summary=task.model_summary,
                    obs_example=task.obs_example,
                    baseline_name=task.baseline_name,
                    history=history,
                    feedback_history=feedback_history,
                    objective_metric=metric_main,
                    baseline_code=baseline_code,
                )
            except Exception as e:
                logger.error(f"LLMCoder worker: PlannerAgent error: {e}")
                plans = []
            logger.debug(
                "LLMCoder worker: [agentic iter=%d] planner produced %d plans: %s",
                it,
                len(plans),
                [getattr(p, "name", None) for p in plans],
            )
            candidates = self._coder.build_candidates_from_plans(
                model_summary=task.model_summary,
                obs_example=task.obs_example,
                baseline_name=task.baseline_name,
                plans=plans,
                objective_metric=metric_main,
            )
            num_candidates = len(candidates)
            self._n_candidates_total += num_candidates
            logger.debug(
                "LLMCoder worker: [agentic iter=%d] generated %d candidates from plans",
                it,
                num_candidates,
            )
            
            # Apply evolutionary operations if enabled
            offspring = []
            if self._cfg.enable_evolution and self._repo is not None:
                try:
                    offspring = self._apply_evolutionary_operations(
                        candidates=candidates,
                        task=task
                    )
                    logger.info(
                        "LLMCoder worker: [agentic iter=%d] generated {} offspring through evolution",
                        it,
                        len(offspring)
                    )
                except Exception as exc:
                    logger.error(
                        "LLMCoder worker: [agentic iter=%d] evolutionary operations failed: {}",
                        it,
                        exc
                    )
            
            # Combine candidates and offspring for evaluation
            all_candidates = candidates + offspring
            
            if not all_candidates:
                logger.warning("LLMCoder worker: no valid candidate rule generated in agentic iteration %d", it)
                break
            records: List[CandidateRecord] = []
            scores: Dict[int, float] = {}
            candidate_summaries: List[Dict[str, Any]] = []
            accepted_count = 0
            best_rel_improvement_accepted = float("-inf")
            events_pool = self._get_or_create_eval_pool(task.model)
            entries: List[CandidateRecord] = []
            for cand in all_candidates:
                idx = self._next_candidate_index
                self._next_candidate_index += 1
                rec = CandidateRecord(index=idx, rule=cand, iteration=it)
                entries.append(rec)
            max_parallel = int(getattr(self._cfg, "eval_max_parallel_candidates", 0) or 0)
            if max_parallel > 1 and len(entries) > 1:
                max_workers = min(max_parallel, len(entries))
                logger.debug(
                    "LLMCoder worker: evaluating {} candidates in parallel with {} workers (agentic, iter={})",
                    len(entries),
                    max_workers,
                    it,
                )
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [
                        executor.submit(
                            evaluate_candidate_rule,
                            model=task.model,
                            baseline_rule=task.baseline_rule,
                            candidate_rule=rec.rule.rule,
                            candidate_code=(rec.rule.info.get("code") if isinstance(getattr(rec.rule, "info", None), dict) else None),
                            cfg=self._cfg,
                            events_pool=events_pool,
                            objective_metric=metric_main,
                        )
                        for rec in entries
                    ]
                self._n_eval_calls += len(entries)
                results_agentic: List[Optional[Any]] = [f.result() for f in futures]
                rec_iter = zip(entries, candidates, results_agentic)
            else:
                rec_iter = []
                for rec, cand in zip(entries, all_candidates):
                    self._n_eval_calls += 1
                    cand_code = None
                    try:
                        info = getattr(cand.rule, "info", None)
                        if isinstance(info, dict):
                            cand_code = info.get("code")
                    except Exception:
                        cand_code = None
                    res = evaluate_candidate_rule(
                        model=task.model,
                        baseline_rule=task.baseline_rule,
                        candidate_rule=cand.rule,
                        candidate_code=cand_code,
                        cfg=self._cfg,
                        events_pool=events_pool,
                        objective_metric=metric_main,
                    )
                    rec_iter.append((rec, cand, res))

            for rec, cand, res in rec_iter:
                records.append(rec)
                rec.eval_result = res
                info = dict(cand.info)
                eval_dict: Dict[str, Any] = {}
                if res is not None:
                    eval_dict = {
                        "baseline_value": res.baseline_value,
                        "candidate_value": res.candidate_value,
                        "relative_improvement": res.relative_improvement,
                        "accepted": res.accepted,
                        "episodes_used": getattr(res, "episodes_used", 0),
                        "effect_size": getattr(res, "effect_size", 0.0),
                    }
                complexity_score = self._extract_complexity_score_from_info(info)
                if res is not None and res.accepted:
                    self._n_candidates_valid += 1
                    accepted_count += 1
                    try:
                        rel_imp = float(getattr(res, "relative_improvement", float("-inf")))
                        if rel_imp > best_rel_improvement_accepted:
                            best_rel_improvement_accepted = rel_imp
                    except Exception:
                        pass
                    normalized_complexity = math.log1p(max(complexity_score, 0.0))
                    score = float(res.relative_improvement) - float(self._cfg.complexity_weight) * normalized_complexity
                    scores[rec.index] = score
                    if score > best_score:
                        best_score = score
                        best_res = res
                        best_rule = RuleWithMeta(rule=cand.rule, name=cand.name, info=info)
                    logger.info(
                        "LLMCoder worker: [iter=%d] candidate '%s' accepted by sandbox eval (rel_improve={:.6f}, complexity_score={:.6f}, combined_score={:.6f})",
                        it,
                        cand.name,
                        res.relative_improvement,
                        complexity_score,
                        score,
                    )
                else:
                    logger.info(
                        "LLMCoder worker: [iter=%d] candidate '%s' rejected by sandbox eval",
                        it,
                        cand.name,
                    )
                plan_info = info.get("plan") if isinstance(info, dict) else None
                candidate_summaries.append(
                    {
                        "index": rec.index,
                        "name": cand.name,
                        "plan": plan_info,
                        "complexity": info.get("complexity") if isinstance(info, dict) else None,
                        "eval": eval_dict,
                    }
                )
            memory.add_candidates(records)
            logger.debug(
                "LLMCoder worker: [agentic iter=%d] candidate_summaries=%s",
                it,
                candidate_summaries,
            )
            best_rec = memory.update_best_by_score(scores)
            history = {
                "iteration": it,
                "num_candidates": len(records),
                "best_score": best_score,
                "objective_metric": metric_main,
                "max_iterations": max_iter,
                "remaining_iterations": max(0, int(max_iter) - (int(it) + 1)),
                "agentic_min_relative_improvement": float(
                    getattr(self._cfg, "agentic_min_relative_improvement", 0.0) or 0.0
                ),
                "best_relative_improvement": (
                    float(best_rel_improvement_accepted)
                    if best_rel_improvement_accepted > float("-inf")
                    else None
                ),
                "accepted_count": int(accepted_count),
            }
            critic_result = None
            agentic_threshold = float(getattr(self._cfg, "agentic_min_relative_improvement", 0.0) or 0.0)
            early_stop_triggered = (
                accepted_count > 0
                and best_rel_improvement_accepted > float("-inf")
                and float(best_rel_improvement_accepted) >= float(agentic_threshold)
            )
            if early_stop_triggered:
                logger.info(
                    "LLMCoder worker: [agentic iter=%d] early-stop triggered (best_rel_improve=%.6f >= threshold=%.6f), skipping critic",
                    it,
                    float(best_rel_improvement_accepted),
                    float(agentic_threshold),
                )
            else:
                try:
                    critic_result = self._critic.analyze(
                        baseline_name=task.baseline_name,
                        model_summary=task.model_summary,
                        candidate_summaries=candidate_summaries,
                        history=history,
                        feedback_history=feedback_history,
                        objective_metric=metric_main,
                    )
                except Exception as e:
                    logger.error("LLMCoder worker: CriticAgent failed, using fallback behavior: {}", e)
                    critic_result = None
                    # Fallback: if we have accepted candidates, continue one more iteration
                    # Otherwise, stop iterations
                    if accepted_count > 0:
                        logger.info(
                            "LLMCoder worker: [agentic iter=%d] critic failed but {} candidates accepted, will continue if iterations remain",
                            it,
                            accepted_count
                        )
                    else:
                        logger.warning(
                            "LLMCoder worker: [agentic iter=%d] critic failed and no candidates accepted, stopping iterations",
                            it
                        )

            critic_info: Optional[Dict[str, Any]] = None
            if early_stop_triggered:
                critic_info = {
                    "continue_iterations": False,
                    "feedbacks": [],
                    "early_stop": {
                        "best_rel_improve": float(best_rel_improvement_accepted),
                        "threshold": float(agentic_threshold),
                    },
                }
            if critic_result is not None:
                fb_list: List[Dict[str, Any]] = []
                try:
                    for fb in critic_result.feedbacks:
                        fb_list.append(
                            {
                                "candidate_index": getattr(fb, "candidate_index", None),
                                "candidate_name": getattr(fb, "candidate_name", None),
                                "verdict": getattr(fb, "verdict", None),
                                "reason": getattr(fb, "reason", ""),
                                "suggested_changes": dict(getattr(fb, "suggested_changes", {}) or {}),
                            }
                        )
                except Exception:
                    fb_list = []
                critic_info = {
                    "continue_iterations": bool(getattr(critic_result, "continue_iterations", False)),
                    "feedbacks": fb_list,
                }

            logger.debug(
                "LLMCoder worker: [agentic iter=%d] critic_info=%s",
                it,
                critic_info,
            )

            self._append_log(
                {
                    "event": "agentic_iteration",
                    "mode": "agentic",
                    "step": task.step,
                    "iteration": it,
                    "baseline_name": task.baseline_name,
                    "num_candidates": len(records),
                    "best_score_so_far": best_score,
                    "scores": scores,
                    "candidates": candidate_summaries,
                    "critic": critic_info,
                }
            )
            if early_stop_triggered or critic_result is None or not critic_result.continue_iterations:
                break
        
        # Increment generation counter after completing iterations
        if self._population_manager is not None:
            self._population_manager.increment_generation()
            self._generation = self._population_manager.generation
            logger.debug(
                "LLMCoder worker: incremented generation to {}",
                self._generation
            )
        
        if best_rule is None or best_res is None:
            logger.info("LLMCoder worker: no accepted candidate rule after agentic iterations")
            self._append_log(
                {
                    "event": "rule_search_failed",
                    "mode": "agentic",
                    "step": task.step,
                    "baseline_name": task.baseline_name,
                }
            )
            return
        agentic_summary: Dict[str, Any] = {
            "iterations": memory.iteration + 1,
            "num_candidates": len(memory.candidates),
            "best_score": best_score,
        }
        logger.debug(
            "LLMCoder worker: agentic summary at step=%s baseline='%s': %s",
            task.step,
            task.baseline_name,
            agentic_summary,
        )
        self._finalize_and_enqueue_best(task, best_rule, best_res, best_score, agentic_summary=agentic_summary)

    def _select_best_by_complexity(self, candidates: List[RuleWithMeta]) -> RuleWithMeta:
        best = candidates[0]
        best_complexity = self._extract_complexity_score(best)
        for cand in candidates[1:]:
            cplx = self._extract_complexity_score(cand)
            if cplx < best_complexity:
                best = cand
                best_complexity = cplx
        return best

    def _extract_complexity_score(self, rule: RuleWithMeta) -> float:
        info = getattr(rule, "info", {}) or {}
        if not isinstance(info, dict):
            return 0.0
        complexity = info.get("complexity")
        if isinstance(complexity, dict):
            try:
                return float(complexity.get("complexity_score", 0.0))
            except Exception:
                return 0.0
        return 0.0

    def _extract_complexity_score_from_info(self, info: Dict[str, Any]) -> float:
        if not isinstance(info, dict):
            return 0.0
        complexity = info.get("complexity")
        if isinstance(complexity, dict):
            try:
                return float(complexity.get("complexity_score", 0.0))
            except Exception:
                return 0.0
        return 0.0

    def _finalize_and_enqueue_best(
        self,
        task: CoderTask,
        best_rule: RuleWithMeta,
        best_res: Any,
        best_score: float,
        agentic_summary: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._n_rules_selected += 1
        eval_info: Dict[str, Any] = {
            "baseline_value": best_res.baseline_value,
            "candidate_value": best_res.candidate_value,
            "relative_improvement": best_res.relative_improvement,
            "episodes_used": getattr(best_res, "episodes_used", 0),
            "effect_size": getattr(best_res, "effect_size", 0.0),
            "combined_score": best_score,
        }
        self._last_best_eval = dict(eval_info)
        info = dict(best_rule.info)
        info["eval"] = eval_info
        if agentic_summary is not None:
            try:
                info["agentic"] = dict(agentic_summary)
            except Exception:
                info["agentic"] = {"summary_error": True}
        try:
            explanation: Dict[str, Any] = {}
            try:
                if getattr(self, "_refactor", None) is not None:
                    explanation = self._refactor.explain(best_rule, eval_info=eval_info)
                else:
                    explanation = build_rule_explanation(best_rule)
            except Exception:
                explanation = build_rule_explanation(best_rule)
            if isinstance(explanation, dict):
                info["explanation"] = explanation
        except Exception as exc:
            logger.warning("AsyncCoderWorker: failed to attach explanation: {}", exc)
        best_rule.info = info
        self._append_log(
            {
                "event": "rule_selected",
                "step": task.step,
                "baseline_name": task.baseline_name,
                "rule_name": best_rule.name,
                "eval": eval_info,
                "agentic": agentic_summary,
                "model_summary": task.model_summary,
            }
        )
        try:
            if self._repo is not None:
                logger.debug(
                    "LLMCoder worker: calling RuleRepository.add_from_rule_with_genealogy for '{}'",
                    best_rule.name,
                )
                
                # Extract parent IDs and operation from rule info
                parent_ids = self._extract_parent_ids(best_rule)
                operation = best_rule.info.get("operation", "generated")
                
                # Add to repository with genealogy
                rule_id = self._repo.add_from_rule_with_genealogy(
                    best_rule,
                    task.model_summary,
                    parent_ids=parent_ids,
                    operation=operation,
                    generation=self._generation
                )
                
                self._n_rules_repo_added += 1
                logger.debug(
                    "LLMCoder worker: RuleRepository.add_from_rule_with_genealogy completed for '{}' (id={})",
                    best_rule.name,
                    rule_id
                )
                
                # Update population manager if available
                if self._population_manager is not None:
                    fitness = best_score
                    self._population_manager.add_individual(
                        best_rule,
                        fitness=fitness,
                        parent_ids=parent_ids,
                        operation=operation
                    )
                    logger.debug(
                        "LLMCoder worker: added rule '{}' to population manager (fitness={:.6f})",
                        best_rule.name,
                        fitness
                    )
        except Exception as e:
            logger.error(f"LLMCoder worker: error while updating repository: {e}")
        logger.info(
            "LLMCoder worker: best candidate '{}' selected (rel_improvement={:.6f}, combined_score={:.6f}), enqueuing for hot-swap",
            best_rule.name,
            best_res.relative_improvement,
            best_score,
        )
        self._ready_q.put(best_rule)

    def _apply_evolutionary_operations(
        self,
        candidates: List[RuleWithMeta],
        task: CoderTask
    ) -> List[RuleWithMeta]:
        """Apply crossover and mutation to generate offspring.
        
        Args:
            candidates: List of candidate rules from current generation
            task: The current coder task
        
        Returns:
            List of offspring rules generated through evolution
        """
        offspring = []
        
        # Check if evolutionary operators are available
        if self._crossover_operator is None or self._mutation_operator is None:
            logger.debug("AsyncCoderWorker: evolutionary operators not initialized, skipping evolution")
            return offspring
        
        # Get repository population
        if self._repo is None:
            logger.debug("AsyncCoderWorker: no repository available for evolution")
            return offspring
        
        try:
            repo_population = self._repo.get_population(
                max_size=self._cfg.max_population_size
            )
        except Exception as exc:
            logger.error("AsyncCoderWorker: failed to retrieve repository population: {}", exc)
            return offspring
        
        if not repo_population:
            logger.info("AsyncCoderWorker: empty repository, skipping evolutionary operations")
            return offspring
        
        if not candidates:
            logger.warning("AsyncCoderWorker: no candidates provided for evolution")
            return offspring
        
        logger.info(
            "AsyncCoderWorker: applying evolutionary operations (candidates={}, repo_population={})",
            len(candidates),
            len(repo_population)
        )
        
        # Prepare context for evolutionary operations
        try:
            context = {
                "model_summary": task.model_summary,
                "objective_metric": _select_objective_metric(task.model, self._cfg, task.step),
                "objective_mode": getattr(self._cfg, "objective_mode", "min"),
                "baseline_name": task.baseline_name
            }
        except Exception as exc:
            logger.error("AsyncCoderWorker: failed to prepare evolution context: {}", exc)
            return offspring
        
        # Crossover operations: select parents from different populations
        n_crossover = int(self._cfg.max_offspring_per_iteration * 
                          self._cfg.crossover_probability)
        
        crossover_success = 0
        crossover_failures = 0
        
        for i in range(n_crossover):
            try:
                # Select one parent from candidates and one from repository
                if not candidates or not repo_population:
                    logger.debug("AsyncCoderWorker: insufficient population for crossover")
                    break
                
                import random
                parent1 = random.choice(candidates)
                parent2 = random.choice(repo_population)
                
                logger.debug(
                    "AsyncCoderWorker: attempting crossover {} between '{}' and '{}'",
                    i + 1,
                    parent1.name,
                    parent2.name
                )
                
                child = self._crossover_operator.apply(
                    [parent1, parent2],
                    context=context
                )
                
                if child is not None:
                    logger.info(
                        "AsyncCoderWorker: crossover {} produced offspring '{}'",
                        i + 1,
                        child.name
                    )
                    offspring.append(child)
                    crossover_success += 1
                else:
                    logger.warning("AsyncCoderWorker: crossover {} failed to produce offspring", i + 1)
                    crossover_failures += 1
                    
            except Exception as exc:
                logger.error("AsyncCoderWorker: crossover operation {} failed: {}", i + 1, exc)
                crossover_failures += 1
        
        # Mutation operations: select parents from combined population
        n_mutation = int(self._cfg.max_offspring_per_iteration * 
                         self._cfg.mutation_probability)
        
        all_population = candidates + repo_population
        
        mutation_success = 0
        mutation_failures = 0
        
        for i in range(n_mutation):
            try:
                if not all_population:
                    logger.debug("AsyncCoderWorker: no population available for mutation")
                    break
                
                import random
                parent = random.choice(all_population)
                
                logger.debug(
                    "AsyncCoderWorker: attempting mutation {} of '{}'",
                    i + 1,
                    parent.name
                )
                
                # Identify weaknesses for mutation context
                try:
                    weaknesses = self._identify_weaknesses(parent)
                except Exception as exc:
                    logger.warning("AsyncCoderWorker: failed to identify weaknesses: {}", exc)
                    weaknesses = "No specific weaknesses identified"
                
                mutation_context = dict(context)
                mutation_context["weaknesses"] = weaknesses
                
                child = self._mutation_operator.apply(
                    [parent],
                    context=mutation_context
                )
                
                if child is not None:
                    logger.info(
                        "AsyncCoderWorker: mutation {} produced offspring '{}'",
                        i + 1,
                        child.name
                    )
                    offspring.append(child)
                    mutation_success += 1
                else:
                    logger.warning("AsyncCoderWorker: mutation {} failed to produce offspring", i + 1)
                    mutation_failures += 1
                    
            except Exception as exc:
                logger.error("AsyncCoderWorker: mutation operation {} failed: {}", i + 1, exc)
                mutation_failures += 1
        
        logger.info(
            "AsyncCoderWorker: evolutionary operations completed - {} offspring produced ({}/{} crossover, {}/{} mutation)",
            len(offspring),
            crossover_success,
            n_crossover,
            mutation_success,
            n_mutation
        )
        
        if crossover_failures > 0 or mutation_failures > 0:
            logger.warning(
                "AsyncCoderWorker: evolutionary operations had failures (crossover: {}, mutation: {})",
                crossover_failures,
                mutation_failures
            )
        
        return offspring

    def _select_from_population(self, population: List[Any]) -> Optional[Any]:
        """Select an individual from a population.
        
        Args:
            population: List of individuals (RuleIndividual or RuleWithMeta)
        
        Returns:
            Selected individual or None if population is empty
        """
        if not population:
            return None
        
        import random
        return random.choice(population)
    
    def _extract_parent_ids(self, rule: RuleWithMeta) -> Optional[List[str]]:
        """Extract parent IDs from a rule's genealogy information.
        
        Args:
            rule: The rule to extract parent IDs from
        
        Returns:
            List of parent IDs or None if not available
        """
        try:
            info = getattr(rule, "info", {}) or {}
            if not isinstance(info, dict):
                return None
            
            # Check for parent_ids directly in info
            parent_ids = info.get("parent_ids")
            if parent_ids and isinstance(parent_ids, list):
                return parent_ids
            
            # Check in genealogy
            genealogy = info.get("genealogy")
            if isinstance(genealogy, dict):
                parent_ids = genealogy.get("parent_ids")
                if parent_ids and isinstance(parent_ids, list):
                    return parent_ids
            
            return None
        except Exception:
            return None
    
    def _extract_fitness(self, rule: RuleWithMeta) -> float:
        """Extract fitness score from a rule's evaluation information.
        
        Args:
            rule: The rule to extract fitness from
        
        Returns:
            Fitness score (relative improvement) or 0.0 if not available
        """
        try:
            info = getattr(rule, "info", {}) or {}
            if not isinstance(info, dict):
                return 0.0
            
            eval_info = info.get("eval") or {}
            if not isinstance(eval_info, dict):
                return 0.0
            
            rel_improve = eval_info.get("relative_improvement", 0.0)
            return float(rel_improve) if rel_improve is not None else 0.0
        except Exception:
            return 0.0
    
    def _identify_weaknesses(self, rule: RuleWithMeta) -> str:
        """Identify weaknesses in a rule for mutation guidance.
        
        Args:
            rule: The rule to analyze
        
        Returns:
            String describing identified weaknesses
        """
        weaknesses = []
        
        try:
            info = getattr(rule, "info", {}) or {}
            if not isinstance(info, dict):
                return "No specific weaknesses identified"
            
            # Check evaluation metrics
            eval_info = info.get("eval") or {}
            if isinstance(eval_info, dict):
                rel_improve = eval_info.get("relative_improvement", 0.0)
                if rel_improve is not None:
                    try:
                        rel_improve_val = float(rel_improve)
                        if rel_improve_val < 0.05:
                            weaknesses.append("Low relative improvement compared to baseline")
                    except (ValueError, TypeError):
                        pass
            
            # Check complexity
            complexity = info.get("complexity")
            if isinstance(complexity, dict):
                complexity_score = complexity.get("complexity_score", 0)
                try:
                    if float(complexity_score) > 50:
                        weaknesses.append("High complexity may impact runtime performance")
                except (ValueError, TypeError):
                    pass
            elif isinstance(complexity, (int, float)):
                try:
                    if float(complexity) > 50:
                        weaknesses.append("High complexity may impact runtime performance")
                except (ValueError, TypeError):
                    pass
            
            # Generic weakness if none identified
            if not weaknesses:
                weaknesses.append("Consider exploring alternative feature combinations")
            
            return "; ".join(weaknesses)
        except Exception:
            return "No specific weaknesses identified"

    def _get_or_create_eval_pool(self, model: InputModel) -> EvalEventsPool:
        if self._eval_events_pool is not None:
            return self._eval_events_pool
        try:
            meta = getattr(model, "meta", None)
            base_seed = int(getattr(meta, "seed", 0) or 0)
        except Exception:
            base_seed = 0
        pool_size = int(getattr(self._cfg, "eval_pool_size", 32) or 32)
        self._eval_events_pool = EvalEventsPool(model, base_seed, pool_size)
        return self._eval_events_pool

    def _append_log(self, record: Dict[str, Any]) -> None:
        try:
            self._traj_logger.append(record)
        except Exception:
            logger.exception("AsyncCoderWorker: failed to append trajectory log record")

    def get_trajectory(self) -> List[Dict[str, Any]]:
        try:
            return self._traj_logger.to_list()
        except Exception:
            return []

    def get_stats(self) -> Dict[str, Any]:
        data = {
            "num_tasks_processed": self._n_tasks_processed,
            "num_candidates_total": self._n_candidates_total,
            "num_candidates_accepted": self._n_candidates_valid,
            "num_eval_calls": self._n_eval_calls,
            "num_rules_selected": self._n_rules_selected,
            "num_rules_repo_added": self._n_rules_repo_added,
            "last_best_eval": self._last_best_eval,
        }
        traj_path = self._traj_logger.path_str()
        if traj_path:
            data["trajectory_path"] = traj_path
        else:
            data["trajectory"] = self.get_trajectory()
        return data
