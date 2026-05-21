from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
import hashlib
import json
import os
import logging
import subprocess
import sys
from datetime import datetime

import math
import random
import threading

from loguru import logger

from dsbx.Gen import InputModel, run_generation_pipeline
from dsbx.Env import DynaSchedEnv
from dsbx.Eval.Metrics import evaluate_trajectory
from dsbx.Sim.Loader import load_instance_from_events

from .config import LLMCoderConfig
from .rules import PriorityRule, choose_action_by_rule


def _run_candidate_rollout_in_subprocess(
    *,
    events_file: Path,
    candidate_code: str,
    max_steps: int,
    episode: int,
    seed: int,
    rule_name: str,
    cfg: LLMCoderConfig,
) -> Optional[Dict[str, float]]:
    try:
        timeout = float(getattr(cfg, "eval_subprocess_timeout", 0.0) or 0.0)
    except Exception:
        timeout = 0.0
    if timeout <= 0.0:
        timeout = 120.0
    repo_root = Path(__file__).resolve().parents[3]
    payload: Dict[str, Any] = {
        "events_file": str(events_file),
        "candidate_code": str(candidate_code),
        "max_steps": int(max_steps),
        "episode": int(episode),
        "seed": int(seed),
        "rule_name": str(rule_name),
        "rlimit_cpu_seconds": float(timeout),
        "rlimit_nofile": 64,
        "rlimit_as_bytes": int(2 * 1024 * 1024 * 1024),
    }
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "dsbx.Agents.LLMCoder.subprocess_sandbox",
            ],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=float(timeout),
            cwd=str(repo_root),
        )
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None

    if proc.returncode != 0:
        return None
    try:
        obj = json.loads(proc.stdout or "")
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if not bool(obj.get("ok")):
        return None
    metrics = obj.get("metrics")
    if not isinstance(metrics, dict):
        return None
    out: Dict[str, float] = {}
    for k, v in metrics.items():
        try:
            out[str(k)] = float(v)
        except Exception:
            continue
    return out


_ROLLOUT_LOGGER: Optional[logging.Logger] = None
_ROLLOUT_LOGGER_LOCK = threading.Lock()


def _get_rollout_logger() -> logging.Logger:
    global _ROLLOUT_LOGGER
    with _ROLLOUT_LOGGER_LOCK:
        if _ROLLOUT_LOGGER is not None:
            return _ROLLOUT_LOGGER
        lg = logging.getLogger("dsbx.Agents.LLMCoder.rollout_eval")
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        if not lg.handlers:
            run_dir = os.environ.get("DYNA_SCHEDBENCH_RUN_LOG_DIR")
            if run_dir:
                log_dir = Path(run_dir)
            else:
                root = Path(__file__).resolve().parents[3]
                log_dir = root / "logs" / "llmcoder_rollout_eval"
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = log_dir / f"rollout_eval_{ts}.log"
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
            lg.addHandler(fh)
        _ROLLOUT_LOGGER = lg
        return lg


@dataclass
class EvalResult:
    baseline_value: float
    candidate_value: float
    relative_improvement: float
    accepted: bool
    episodes_used: int = 0
    effect_size: float = 0.0


@dataclass
class EvalInstance:
    model: InputModel
    events: List[Any]
    seed: int
    instance_dir: Path


@dataclass
class JMSEvalInstance:
    """Metadata for one JMS/GEN-Bench evaluation instance.

    This mirrors ``EvalInstance`` but does not depend on ``InputModel`` or an
    event list. It stores the JSONL path and logical seed; the instance semantics
    are fully defined by the JMSBench/GEN-Bench JSONL file.
    """

    instance_file: Path
    seed: int


class EvalEventsPool:
    """Persistent evaluation instance pool built via the full generation pipeline.

    Instances are stored under an InputModel-specific subdirectory. For a given
    ``base_seed`` and ``pool_size``, the generation pipeline is invoked only on
    first use, then subsequent evaluations reuse the generated model/events
    pairs without refreshing or rebuilding fast-path instances.
    """

    def __init__(self, model: InputModel, base_seed: int, pool_size: int) -> None:
        sandbox_logger = logger.bind(sandbox_eval=True)
        self._model = model
        self._base_seed = int(base_seed)
        self._pool_size = max(1, int(pool_size))
        self._instances: List[EvalInstance] = []
        self._lock = threading.Lock()
        self._refresh_event = threading.Event()
        self._refresh_event.set()
        self._rng = random.Random(int(base_seed))
        self._pending_refresh: int = 0
        self._refresh_thread: Optional[threading.Thread] = None
        self._num_generated_total: int = 0
        self._num_refreshes_total: int = 0
        self._min_seed_used: Optional[int] = None
        self._max_seed_used: Optional[int] = None

        # Persistent root: .../Agents/LLMCoder/sandbox_eval_pool/<model_key>/
        self._pool_root: Path = Path(__file__).resolve().parent / "sandbox_eval_pool"
        try:
            self._pool_root.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self._model_key: str = self._compute_model_key(model)
        self._model_root: Path = self._pool_root / self._model_key
        try:
            self._model_root.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        sandbox_logger.debug(
            "EvalEventsPool: initializing pool (pool_size={}, base_seed={}, model_key={}, root={})",
            self._pool_size,
            base_seed,
            self._model_key,
            self._model_root,
        )
        for i in range(self._pool_size):
            seed = self._base_seed + i
            inst = self._load_or_generate_instance(seed)
            self._instances.append(inst)
        sandbox_logger.debug(
            "EvalEventsPool: initialized with {} instances (num_generated_total={}, seed_range=[{}, {}])",
            len(self._instances),
            self._num_generated_total,
            self._min_seed_used,
            self._max_seed_used,
        )

    @staticmethod
    def _compute_model_key(model: InputModel) -> str:
        """Compute a stable key for the given InputModel for on-disk pooling."""

        try:
            meta = getattr(model, "meta", None)
            parts: List[str] = []
            if meta is not None:
                run_name = getattr(meta, "run_name", None)
                if run_name:
                    parts.append(str(run_name))
                scenario_id = getattr(meta, "scenario_id", None)
                if scenario_id:
                    parts.append(str(scenario_id))
                seed = getattr(meta, "seed", None)
                if seed is not None:
                    parts.append(f"seed{int(seed)}")
            if parts:
                return "_".join(parts)
        except Exception:
            pass

        # Fallback: short hash of the full model payload (stable across runs).
        try:
            data = model.model_dump()  # type: ignore[attr-defined]
        except Exception:
            data = {}
        try:
            payload = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
        except Exception:
            payload = repr(data).encode("utf-8")
        h = hashlib.sha1(payload).hexdigest()[:12]
        return f"model_{h}"

    def _load_or_generate_instance(self, seed: int) -> EvalInstance:
        """Load an existing instance for ``seed`` or generate a new one."""

        seed_dir = self._model_root / f"seed_{seed:04d}"
        events_file = seed_dir / "events.jsonl"

        if events_file.exists():
            with logger.contextualize(sandbox_eval=True):
                try:
                    model, events = load_instance_from_events(events_file)
                    logical_seed = seed
                    if self._min_seed_used is None or logical_seed < self._min_seed_used:
                        self._min_seed_used = logical_seed
                    if self._max_seed_used is None or logical_seed > self._max_seed_used:
                        self._max_seed_used = logical_seed
                    logger.debug(
                        "EvalEventsPool: loaded existing instance for seed={} from {}",
                        seed,
                        events_file,
                    )
                    return EvalInstance(model=model, events=events, seed=seed, instance_dir=seed_dir)
                except Exception as exc:
                    logger.warning(
                        "EvalEventsPool: failed to load existing instance for seed={} from {} ({}); regenerating.",
                        seed,
                        events_file,
                        exc,
                    )

        model_gen, events_gen = self._generate_instance_to_dir(seed_dir, seed)
        logical_seed = seed
        if self._min_seed_used is None or logical_seed < self._min_seed_used:
            self._min_seed_used = logical_seed
        if self._max_seed_used is None or logical_seed > self._max_seed_used:
            self._max_seed_used = logical_seed
        self._num_generated_total += 1
        return EvalInstance(model=model_gen, events=events_gen, seed=seed, instance_dir=seed_dir)
        
    def _generate_instance_to_dir(self, instance_dir: Path, seed: int) -> Tuple[InputModel, List[Any]]:
        """Run the full generation pipeline once for the given seed into ``instance_dir``.

        The call reuses ``InputModel.calibration`` settings as closely as
        possible, keeping evaluation instances aligned with ``dsbx-gen gen``
        when no extra command-line overrides are supplied.
        """

        with logger.contextualize(sandbox_eval=True):
            try:
                instance_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

            # Clone model and override meta.seed when possible so that each seed
            # corresponds to a distinct generated instance, while keeping the
            # original model untouched for the main environment.
            try:
                model_copy: InputModel = self._model.model_copy(deep=True)  # type: ignore[attr-defined]
            except Exception:
                model_copy = self._model
            try:
                meta = getattr(model_copy, "meta", None)
                if meta is not None:
                    setattr(meta, "seed", int(seed))
            except Exception:
                pass

            max_calib_steps: int = 25
            use_moo: bool = False
            use_hybrid: bool = False
            extra_kwargs: Dict[str, Any] = {}
            try:
                calib = getattr(model_copy, "calibration", None)
            except Exception:
                calib = None
            if calib is not None:
                try:
                    ms = getattr(calib, "max_steps", None)
                    if ms is not None:
                        max_calib_steps = int(ms)
                except Exception:
                    pass
                try:
                    mode = str(getattr(calib, "mode", "sequential") or "").lower()
                except Exception:
                    mode = "sequential"
                if mode == "moo":
                    use_moo = True
                elif mode == "hybrid":
                    use_hybrid = True

                for attr, key in [
                    ("moo_population_size", "moo_population_size"),
                    ("moo_n_generations", "moo_n_generations"),
                    ("hybrid_population_size", "hybrid_population_size"),
                    ("hybrid_n_generations", "hybrid_n_generations"),
                    ("hybrid_convergence_window", "hybrid_convergence_window"),
                    ("hybrid_convergence_tol", "hybrid_convergence_tol"),
                    ("hybrid_max_sequential_steps", "hybrid_max_sequential_steps"),
                    ("seq_early_stop_no_improve_steps", "seq_early_stop_no_improve_steps"),
                    ("seq_early_stop_relax_factor", "seq_early_stop_relax_factor"),
                    ("seq_min_relative_improvement", "seq_min_relative_improvement"),
                    ("seq_tol_rho_global", "seq_tol_rho_global"),
                    ("seq_tol_scv_a", "seq_tol_scv_a"),
                    ("seq_tol_scv_p", "seq_tol_scv_p"),
                    ("seq_tol_ddt", "seq_tol_ddt"),
                    ("seq_tol_disturbance", "seq_tol_disturbance"),
                    ("seq_tol_load_cv", "seq_tol_load_cv"),
                ]:
                    try:
                        val = getattr(calib, attr, None)
                    except Exception:
                        val = None
                    if val is not None:
                        extra_kwargs[key] = val

            logger.info(
                "EvalEventsPool: running generation pipeline for seed={} into {} (max_calib_steps={}, use_moo={}, use_hybrid={})",
                seed,
                instance_dir,
                max_calib_steps,
                use_moo,
                use_hybrid,
            )
            try:
                run_generation_pipeline(
                    model=model_copy,
                    output_path=instance_dir,
                    max_calib_steps=max_calib_steps,
                    use_moo=use_moo,
                    use_hybrid=use_hybrid,
                    **extra_kwargs,
                )
            except Exception as exc:
                logger.error(
                    "EvalEventsPool: run_generation_pipeline failed for seed={} at {}: {}",
                    seed,
                    instance_dir,
                    exc,
                )
                raise

            events_file = instance_dir / "events.jsonl"
            model_loaded, events = load_instance_from_events(events_file)
            logger.info(
                "EvalEventsPool: generated instance for seed={} with {} events at {}",
                seed,
                len(events),
                events_file,
            )
            return model_loaded, events

    def acquire_for_eval(self, max_episodes: int) -> List[EvalInstance]:
        """Return up to ``max_episodes`` instances sampled from the pool."""

        sandbox_logger = logger.bind(sandbox_eval=True)
        self._refresh_event.wait()
        with self._lock:
            if not self._instances:
                return []
            n = max(1, int(max_episodes))
            n = min(n, len(self._instances))
            indices = [self._rng.randrange(len(self._instances)) for _ in range(n)]
            sandbox_logger.debug(
                "EvalEventsPool: acquire_for_eval(max_episodes={}) -> using {} instances (pool_size={}, num_generated_total={}, seed_range=[{}, {}])",
                max_episodes,
                n,
                len(self._instances),
                self._num_generated_total,
                self._min_seed_used,
                self._max_seed_used,
            )
            return [self._instances[i] for i in indices]

    def request_refresh(self, num_to_refresh: int) -> None:
        """Refresh is disabled for persistent pools (kept for backward compatibility)."""

        sandbox_logger = logger.bind(sandbox_eval=True)
        num = int(num_to_refresh)
        if num <= 0:
            return
        sandbox_logger.debug(
            "EvalEventsPool: request_refresh(num_to_refresh={}) ignored (persistent pool; no refresh).",
            num,
        )


class JMSEvalPool:
    """Evaluation pool based on JMSBench/GEN-Bench JSONL files.

    The pool uses ``static_info`` from the current JMS instance as the structural
    template, resamples ``dynamic_events`` by seed through the JMS-like generator,
    and evaluates baseline and candidate rules on JSONL instances with the same
    JMSSim semantics as the main environment.
    """

    def __init__(self, static_info: Dict[str, Any], base_seed: int, pool_size: int, *, suite: str) -> None:
        self._static_info: Dict[str, Any] = dict(static_info or {})
        self._base_seed: int = int(base_seed)
        self._pool_size: int = max(0, int(pool_size))
        self._suite: str = str(suite)
        self._instances: List[JMSEvalInstance] = []

        self._pool_root: Path = Path(__file__).resolve().parent / "sandbox_eval_pool_jms"
        try:
            self._pool_root.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        self._model_key: str = self._compute_model_key(self._static_info, self._suite)
        self._model_root: Path = self._pool_root / self._model_key
        try:
            self._model_root.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        if not self._static_info or self._pool_size <= 0:
            return

        for i in range(self._pool_size):
            seed = self._base_seed + i
            inst = self._load_or_generate_instance(seed)
            self._instances.append(inst)

    @staticmethod
    def _compute_model_key(static_info: Dict[str, Any], suite: str) -> str:
        try:
            payload = {
                "suite": str(suite),
                "static_info": static_info,
            }
            data = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        except Exception:
            data = repr(static_info).encode("utf-8")
        h = hashlib.sha1(data).hexdigest()[:12]
        return f"jms_{suite}_{h}"

    def _load_or_generate_instance(self, seed: int) -> JMSEvalInstance:
        seed_dir = self._model_root / f"seed_{seed:04d}"
        inst_file = seed_dir / "instance.jsonl"

        if inst_file.exists():
            return JMSEvalInstance(instance_file=inst_file, seed=seed)

        try:
            seed_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        try:
            from toolsj.trainset.jms_like_generation import build_instance as _jms_build_instance  # type: ignore[import]
        except Exception:
            payload: Dict[str, Any] = {}
        else:
            try:
                payload = _jms_build_instance(self._static_info, int(seed), str(self._suite))  # type: ignore[assignment]
            except Exception:
                payload = {}

        try:
            with inst_file.open("w", encoding="utf-8") as f:
                if payload:
                    json.dump(payload, f, ensure_ascii=False)
                f.write("\n")
        except Exception:
            pass

        return JMSEvalInstance(instance_file=inst_file, seed=seed)

    def acquire_for_eval(self, max_episodes: int) -> List[JMSEvalInstance]:
        """Return up to ``max_episodes`` JMS eval instances sampled from the pool."""

        if not self._instances:
            return []
        n = max(1, int(max_episodes))
        n = min(n, len(self._instances))
        rng = random.Random(int(self._base_seed))
        idxs = [rng.randrange(len(self._instances)) for _ in range(n)]
        return [self._instances[i] for i in idxs]

    def request_refresh(self, num_to_refresh: int) -> None:
        """Refresh is disabled for JMS eval pools (kept for backward compatibility)."""

        sandbox_logger = logger.bind(sandbox_eval=True)
        num = int(num_to_refresh)
        if num <= 0:
            return
        sandbox_logger.debug(
            "JMSEvalPool: request_refresh(num_to_refresh={}) ignored (persistent JMS pool; no refresh).",
            num,
        )

def _run_single_rollout(
    model: InputModel,
    events,
    rule: PriorityRule,
    max_steps: int,
    *,
    episode: int,
    seed: int,
    rollout_label: str,
    rule_name: str,
    instance_dir: Optional[Path] = None,
) -> Dict[str, float]:
    rollout_logger = _get_rollout_logger()
    with logger.contextualize(sandbox_eval=True):
        events_list = list(events) if events is not None else []
        env = DynaSchedEnv(model, events=events_list, auto_generate_events=False)
        obs = env.reset()
        done = env.done()
        steps = 0
        idle_advances = 0
        last_time = float(obs.get("time", 0.0) if isinstance(obs, dict) else 0.0)

        rollout_logger.info(
            "rollout_start episode=%s seed=%s label=%s rule=%s max_steps=%s instance_dir=%s num_events=%s",
            episode,
            seed,
            rollout_label,
            rule_name,
            int(max_steps),
            str(instance_dir) if instance_dir is not None else None,
            len(events_list),
        )

        while (not done) and steps < max_steps:
            legal = env.legal_actions()
            if not legal:
                prev_t = last_time
                obs = env.advance_if_idle()
                idle_advances += 1
                done = env.done()
                try:
                    last_time = float(obs.get("time", 0.0) if isinstance(obs, dict) else prev_t)
                except Exception:
                    last_time = prev_t
                rollout_logger.debug(
                    "idle_advance episode=%s seed=%s label=%s idle_advances=%s time=%.6f done=%s",
                    episode,
                    seed,
                    rollout_label,
                    idle_advances,
                    float(last_time),
                    bool(done),
                )
                if (not done) and abs(last_time - prev_t) < 1e-9:
                    rollout_logger.warning(
                        "idle_stall episode=%s seed=%s label=%s time=%.6f (no progress after advance_if_idle), breaking",
                        episode,
                        seed,
                        rollout_label,
                        float(last_time),
                    )
                    break
                continue

            act = choose_action_by_rule(rule, obs, legal, env, rule_name=rule_name)
            if act is None:
                prev_t = last_time
                obs = env.advance_if_idle()
                idle_advances += 1
                done = env.done()
                try:
                    last_time = float(obs.get("time", 0.0) if isinstance(obs, dict) else prev_t)
                except Exception:
                    last_time = prev_t
                rollout_logger.debug(
                    "act_none episode=%s seed=%s label=%s idle_advances=%s time=%.6f done=%s",
                    episode,
                    seed,
                    rollout_label,
                    idle_advances,
                    float(last_time),
                    bool(done),
                )
                continue

            timing = None
            try:
                sim = getattr(env, "_sim", None)
                if sim is not None and hasattr(sim, "get_action_timing"):
                    timing = sim.get_action_timing(act)
            except Exception:
                timing = None

            obs, reward, done, info = env.step(act)
            steps += 1
            try:
                last_time = float(obs.get("time", last_time) if isinstance(obs, dict) else last_time)
            except Exception:
                pass

            rollout_logger.debug(
                "step episode=%s seed=%s label=%s step=%s time=%.6f done=%s action=%s timing=%s",
                episode,
                seed,
                rollout_label,
                steps,
                float(last_time),
                bool(done),
                {
                    "job_id": act.get("job_id"),
                    "machine_group": act.get("machine_group"),
                    "machine_id": act.get("machine_id"),
                },
                timing,
            )

        traj = env.get_trajectory()
        metrics = evaluate_trajectory(traj)

        snap = None
        try:
            snap = traj.last_snapshot
        except Exception:
            snap = None

        num_jobs_total = None
        num_jobs_completed = None
        num_jobs_cancelled = None
        final_time = None
        if snap is not None:
            try:
                final_time = float(getattr(snap, "time", None))
            except Exception:
                final_time = None
            try:
                jobs = list(getattr(snap, "jobs", []) or [])
                num_jobs_total = len(jobs)
                num_jobs_completed = sum(1 for j in jobs if getattr(j, "status", None) == "completed")
                num_jobs_cancelled = sum(1 for j in jobs if getattr(j, "status", None) == "cancelled")
            except Exception:
                pass

        rollout_logger.info(
            "rollout_end episode=%s seed=%s label=%s rule=%s steps=%s idle_advances=%s done=%s final_time=%s makespan=%s num_jobs_total=%s num_jobs_completed=%s num_jobs_cancelled=%s",
            episode,
            seed,
            rollout_label,
            rule_name,
            int(steps),
            int(idle_advances),
            bool(done),
            final_time,
            metrics.get("makespan") if isinstance(metrics, dict) else None,
            num_jobs_total,
            num_jobs_completed,
            num_jobs_cancelled,
        )

        return metrics


def evaluate_candidate_rule(
    model: InputModel,
    baseline_rule: PriorityRule,
    candidate_rule: PriorityRule,
    cfg: LLMCoderConfig,
    candidate_code: Optional[str] = None,
    events_pool: Optional[EvalEventsPool] = None,
    objective_metric: Optional[str] = None,
) -> Optional[EvalResult]:
    if not cfg.enable_eval:
        return None
    sandbox_logger = logger.bind(sandbox_eval=True)
    cand_is_disabled = getattr(candidate_rule, "is_disabled", None)
    min_episodes = max(1, int(getattr(cfg, "eval_min_episodes", 1)))
    max_episodes = int(getattr(cfg, "eval_max_episodes", max(min_episodes, int(getattr(cfg, "eval_episodes", min_episodes)))))
    if max_episodes < min_episodes:
        max_episodes = min_episodes
    max_steps = max(1, int(cfg.eval_max_steps))
    alpha = float(getattr(cfg, "eval_significance_level", 0.05))
    min_effect = float(getattr(cfg, "eval_min_effect_size", 0.0))
    metric = str(objective_metric) if objective_metric is not None else str(cfg.objective_metric)
    mode = cfg.objective_mode.lower()
    debug_accept = bool(getattr(cfg, "debug_always_accept", False))
    sandbox_logger.info(
        "LLMCoder sandbox eval: starting evaluation (min_episodes={}, max_episodes={}, max_steps={}, metric='{}', mode='{}', alpha={:.4f}, debug_always_accept={}, use_pool={})",
        min_episodes,
        max_episodes,
        max_steps,
        metric,
        mode,
        alpha,
        debug_accept,
        bool(events_pool is not None),
    )
    baseline_vals: List[float] = []
    candidate_vals: List[float] = []
    accepted = False
    episodes_used = 0
    rel_improvement = 0.0
    effect_size = 0.0
    instances: Optional[List[EvalInstance]] = None
    if events_pool is not None:
        instances = events_pool.acquire_for_eval(max_episodes)
    else:
        try:
            meta = getattr(model, "meta", None)
            base_seed = int(getattr(meta, "seed", 0) or 0)
        except Exception:
            base_seed = 0
        tmp_pool = EvalEventsPool(model, base_seed, max_episodes)
        instances = tmp_pool.acquire_for_eval(max_episodes)
    loop_episodes = max_episodes
    if instances is not None:
        loop_episodes = min(max_episodes, len(instances))
    sandbox_logger.debug(
        "LLMCoder sandbox eval: prepared episodes (loop_episodes={}, have_pool_instances={}, max_episodes={})",
        loop_episodes,
        instances is not None,
        max_episodes,
    )
    for ep in range(loop_episodes):
        if callable(cand_is_disabled):
            try:
                if bool(cand_is_disabled()):
                    sandbox_logger.warning(
                        "LLMCoder sandbox eval: candidate rule disabled due to repeated errors; early stop at episode {} (episodes_used={})",
                        ep,
                        episodes_used,
                    )
                    break
            except Exception:
                pass
        if not instances:
            break
        inst = instances[ep]
        events = inst.events
        base_name = getattr(baseline_rule, "__name__", None) or baseline_rule.__class__.__name__
        cand_name = getattr(candidate_rule, "__name__", None) or candidate_rule.__class__.__name__
        m_base = _run_single_rollout(
            inst.model,
            events,
            baseline_rule,
            max_steps,
            episode=ep,
            seed=int(getattr(inst, "seed", 0) or 0),
            rollout_label="baseline",
            rule_name=str(base_name),
            instance_dir=getattr(inst, "instance_dir", None),
        )

        m_cand: Optional[Dict[str, float]] = None
        use_subprocess = bool(getattr(cfg, "eval_use_subprocess_sandbox", False))
        if use_subprocess and isinstance(candidate_code, str) and candidate_code.strip():
            try:
                inst_dir = getattr(inst, "instance_dir", None)
            except Exception:
                inst_dir = None
            events_file = None
            try:
                if isinstance(inst_dir, Path):
                    events_file = inst_dir / "events.jsonl"
            except Exception:
                events_file = None
            if isinstance(events_file, Path) and events_file.exists():
                m_cand = _run_candidate_rollout_in_subprocess(
                    events_file=events_file,
                    candidate_code=str(candidate_code),
                    max_steps=max_steps,
                    episode=ep,
                    seed=int(getattr(inst, "seed", 0) or 0),
                    rule_name=str(cand_name),
                    cfg=cfg,
                )
                if m_cand is None:
                    sandbox_logger.warning(
                        "LLMCoder sandbox eval: candidate subprocess rollout failed; rejecting candidate (episode={}, rule='{}')",
                        ep,
                        str(cand_name),
                    )
                    return None
        if m_cand is None:
            m_cand = _run_single_rollout(
                inst.model,
                events,
                candidate_rule,
                max_steps,
                episode=ep,
                seed=int(getattr(inst, "seed", 0) or 0),
                rollout_label="candidate",
                rule_name=str(cand_name),
                instance_dir=getattr(inst, "instance_dir", None),
            )
        bv = float(m_base.get(metric, 0.0))
        cv = float(m_cand.get(metric, 0.0))
        baseline_vals.append(bv)
        candidate_vals.append(cv)
        episodes_used = len(baseline_vals)
        sandbox_logger.debug(
            "LLMCoder sandbox eval: episode {} metric '{}' -> baseline={:.6f}, candidate={:.6f}",
            ep,
            metric,
            bv,
            cv,
        )
        if episodes_used < min_episodes:
            continue
        baseline_mean = sum(baseline_vals) / len(baseline_vals)
        candidate_mean = sum(candidate_vals) / len(candidate_vals)
        denom = abs(baseline_mean) if abs(baseline_mean) > 1e-9 else 1.0
        if mode == "max":
            rel_improvement = (candidate_mean - baseline_mean) / denom
        else:
            rel_improvement = (baseline_mean - candidate_mean) / denom
        effect_size, t_stat = _effect_size_and_t_stat(baseline_vals, candidate_vals, mode)
        t_threshold = _approximate_t_threshold(alpha)
        if bool(getattr(cfg, "eval_fail_fast", False)) and rel_improvement <= 0.0:
            sandbox_logger.info(
                "LLMCoder sandbox eval: fail-fast early reject after {} episodes (baseline={:.6f}, candidate={:.6f}, rel_improve={:.6f}, effect_size={:.6f}, t_stat={:.6f}, t_threshold={:.6f})",
                episodes_used,
                baseline_mean,
                candidate_mean,
                rel_improvement,
                effect_size,
                t_stat,
                t_threshold,
            )
            break
        if getattr(cfg, "debug_always_accept", False):
            accepted = True
            sandbox_logger.info(
                "LLMCoder sandbox eval: debug_always_accept=True, forced accept after {} episodes (baseline={:.6f}, candidate={:.6f}, rel_improve={:.6f}, effect_size={:.6f}, t_stat={:.6f})",
                episodes_used,
                baseline_mean,
                candidate_mean,
                rel_improvement,
                effect_size,
                t_stat,
            )
            break
        if rel_improvement >= cfg.min_relative_improvement and effect_size >= min_effect and t_stat >= t_threshold:
            accepted = True
            sandbox_logger.info(
                "LLMCoder sandbox eval: early accept after {} episodes (baseline={:.6f}, candidate={:.6f}, rel_improve={:.6f}, effect_size={:.6f}, t_stat={:.6f}, t_threshold={:.6f})",
                episodes_used,
                baseline_mean,
                candidate_mean,
                rel_improvement,
                effect_size,
                t_stat,
                t_threshold,
            )
            break
    if not baseline_vals or not candidate_vals:
        return None
    if not accepted:
        baseline_mean = sum(baseline_vals) / len(baseline_vals)
        candidate_mean = sum(candidate_vals) / len(candidate_vals)
        denom = abs(baseline_mean) if abs(baseline_mean) > 1e-9 else 1.0
        if mode == "max":
            rel_improvement = (candidate_mean - baseline_mean) / denom
        else:
            rel_improvement = (baseline_mean - candidate_mean) / denom
        effect_size, t_stat = _effect_size_and_t_stat(baseline_vals, candidate_vals, mode)
        sandbox_logger.info(
            "LLMCoder sandbox eval: final evaluation after {} episodes (baseline={:.6f}, candidate={:.6f}, rel_improve={:.6f}, effect_size={:.6f}, t_stat={:.6f}, accepted={})",
            episodes_used,
            baseline_mean,
            candidate_mean,
            rel_improvement,
            effect_size,
            t_stat,
            False,
        )
    if events_pool is not None:
        refresh_n = int(getattr(cfg, "eval_pool_refresh_per_eval", 0) or 0)
        if refresh_n > 0:
            sandbox_logger.debug(
                "LLMCoder sandbox eval: requesting pool refresh after evaluation (refresh_n={})",
                refresh_n,
            )
            events_pool.request_refresh(refresh_n)
    return EvalResult(
        baseline_value=baseline_mean,
        candidate_value=candidate_mean,
        relative_improvement=rel_improvement,
        accepted=accepted,
        episodes_used=episodes_used,
        effect_size=effect_size,
    )


def _run_single_rollout_jms(
    instance_file: Path,
    rule: PriorityRule,
    max_steps: int,
    *,
    episode: int,
    seed: int,
    rollout_label: str,
    rule_name: str,
) -> Dict[str, float]:
    """Run one rollout on a single JMS/GEN-Bench JSONL instance.

    The function follows ``_run_single_rollout`` structurally, but constructs the
    environment with ``DynaSchedEnv.from_jms_jsonl`` and bypasses InputModel plus
    events.jsonl completely.
    """

    rollout_logger = _get_rollout_logger()
    with logger.contextualize(sandbox_eval=True):
        env = DynaSchedEnv.from_jms_jsonl(instance_file, track_trajectory=True)
        obs = env.reset()
        done = env.done()
        steps = 0
        idle_advances = 0
        try:
            last_time = float(obs.get("time", 0.0) if isinstance(obs, dict) else 0.0)
        except Exception:
            last_time = 0.0

        rollout_logger.info(
            "rollout_start_jms episode=%s seed=%s label=%s rule=%s max_steps=%s instance_file=%s",
            episode,
            seed,
            rollout_label,
            rule_name,
            int(max_steps),
            str(instance_file),
        )

        while (not done) and steps < max_steps:
            legal = env.legal_actions()
            if not legal:
                prev_t = last_time
                obs = env.advance_if_idle()
                idle_advances += 1
                done = env.done()
                try:
                    last_time = float(obs.get("time", 0.0) if isinstance(obs, dict) else prev_t)
                except Exception:
                    last_time = prev_t
                rollout_logger.debug(
                    "idle_advance_jms episode=%s seed=%s label=%s idle_advances=%s time=%.6f done=%s",
                    episode,
                    seed,
                    rollout_label,
                    idle_advances,
                    float(last_time),
                    bool(done),
                )
                if (not done) and abs(last_time - prev_t) < 1e-9:
                    rollout_logger.warning(
                        "idle_stall_jms episode=%s seed=%s label=%s time=%.6f (no progress after advance_if_idle), breaking",
                        episode,
                        seed,
                        rollout_label,
                        float(last_time),
                    )
                    break
                continue

            act = choose_action_by_rule(rule, obs, legal, env, rule_name=rule_name)
            if act is None:
                prev_t = last_time
                obs = env.advance_if_idle()
                idle_advances += 1
                done = env.done()
                try:
                    last_time = float(obs.get("time", 0.0) if isinstance(obs, dict) else prev_t)
                except Exception:
                    last_time = prev_t
                rollout_logger.debug(
                    "act_none_jms episode=%s seed=%s label=%s idle_advances=%s time=%.6f done=%s",
                    episode,
                    seed,
                    rollout_label,
                    idle_advances,
                    float(last_time),
                    bool(done),
                )
                continue

            timing = None
            try:
                sim = getattr(env, "_sim", None)
                if sim is not None and hasattr(sim, "get_action_timing"):
                    timing = sim.get_action_timing(act)
            except Exception:
                timing = None

            obs, reward, done, info = env.step(act)
            steps += 1
            try:
                last_time = float(obs.get("time", last_time) if isinstance(obs, dict) else last_time)
            except Exception:
                pass

            rollout_logger.debug(
                "step_jms episode=%s seed=%s label=%s step=%s time=%.6f done=%s action=%s timing=%s",
                episode,
                seed,
                rollout_label,
                steps,
                float(last_time),
                bool(done),
                {
                    "job_id": act.get("job_id"),
                    "machine_group": act.get("machine_group"),
                    "machine_id": act.get("machine_id"),
                },
                timing,
            )

        traj = env.get_trajectory()
        metrics = evaluate_trajectory(traj)

        snap = None
        try:
            snap = traj.last_snapshot
        except Exception:
            snap = None

        num_jobs_total = None
        num_jobs_completed = None
        num_jobs_cancelled = None
        final_time = None
        if snap is not None:
            try:
                final_time = float(getattr(snap, "time", None))
            except Exception:
                final_time = None
            try:
                jobs = list(getattr(snap, "jobs", []) or [])
                num_jobs_total = len(jobs)
                num_jobs_completed = sum(1 for j in jobs if getattr(j, "status", None) == "completed")
                num_jobs_cancelled = sum(1 for j in jobs if getattr(j, "status", None) == "cancelled")
            except Exception:
                pass

        rollout_logger.info(
            "rollout_end_jms episode=%s seed=%s label=%s rule=%s steps=%s idle_advances=%s done=%s final_time=%s makespan=%s num_jobs_total=%s num_jobs_completed=%s num_jobs_cancelled=%s",
            episode,
            seed,
            rollout_label,
            rule_name,
            int(steps),
            int(idle_advances),
            bool(done),
            final_time,
            metrics.get("makespan") if isinstance(metrics, dict) else None,
            num_jobs_total,
            num_jobs_completed,
            num_jobs_cancelled,
        )

        return metrics


def _effect_size_and_t_stat(baseline_vals: List[float], candidate_vals: List[float], mode: str) -> Tuple[float, float]:
    n_base = len(baseline_vals)
    n_cand = len(candidate_vals)
    if n_base == 0 or n_cand == 0:
        return 0.0, 0.0
    mean_base = sum(baseline_vals) / n_base
    mean_cand = sum(candidate_vals) / n_cand
    var_base = 0.0
    var_cand = 0.0
    if n_base > 1:
        var_base = sum((x - mean_base) ** 2 for x in baseline_vals) / (n_base - 1)
    if n_cand > 1:
        var_cand = sum((x - mean_cand) ** 2 for x in candidate_vals) / (n_cand - 1)
    if mode == "max":
        diff = mean_cand - mean_base
    else:
        diff = mean_base - mean_cand
    pooled_var_num = max((n_base - 1) * var_base + (n_cand - 1) * var_cand, 0.0)
    pooled_den = max(n_base + n_cand - 2, 1)
    pooled_std = math.sqrt(pooled_var_num / pooled_den) if pooled_den > 0 else 0.0
    if pooled_std <= 0.0:
        effect_size = float("inf") if diff > 0 else 0.0
    else:
        effect_size = diff / pooled_std
    denom_t = math.sqrt(var_base / max(n_base, 1) + var_cand / max(n_cand, 1)) if var_base > 0.0 or var_cand > 0.0 else 0.0
    if denom_t <= 0.0:
        t_stat = float("inf") if diff > 0 else 0.0
    else:
        t_stat = diff / denom_t
    return float(effect_size), float(t_stat)


def _approximate_t_threshold(alpha: float) -> float:
    a = float(alpha)
    if a <= 0.0:
        return 0.0
    if a <= 0.001:
        return 3.1
    if a <= 0.01:
        return 2.33
    if a <= 0.05:
        return 1.64
    if a <= 0.1:
        return 1.28
    if a <= 0.15:
        return 1.04
    if a <= 0.2:
        return 0.84
    if a <= 0.25:
        return 0.67
    return 0.0


def evaluate_candidate_rule_jms(
    *,
    baseline_rule: PriorityRule,
    candidate_rule: PriorityRule,
    cfg: LLMCoderConfig,
    candidate_code: Optional[str] = None,
    events_pool: Optional[JMSEvalPool] = None,
    objective_metric: Optional[str] = None,
) -> Optional[EvalResult]:
    """Compare baseline and candidate rules on a JMS/GEN-Bench JSONL pool.

    This is semantically equivalent to :func:`evaluate_candidate_rule`, except
    evaluation instances come from :class:`JMSEvalPool` and each episode builds a
    JMSSim-backed environment with ``DynaSchedEnv.from_jms_jsonl`` rather than
    relying on InputModel or events.jsonl.
    """

    if not cfg.enable_eval:
        return None
    if events_pool is None:
        return None

    sandbox_logger = logger.bind(sandbox_eval=True)
    cand_is_disabled = getattr(candidate_rule, "is_disabled", None)
    min_episodes = max(1, int(getattr(cfg, "eval_min_episodes", 1)))
    max_episodes = int(
        getattr(cfg, "eval_max_episodes", max(min_episodes, int(getattr(cfg, "eval_episodes", min_episodes))))
    )
    if max_episodes < min_episodes:
        max_episodes = min_episodes
    max_steps = max(1, int(cfg.eval_max_steps))
    alpha = float(getattr(cfg, "eval_significance_level", 0.05))
    min_effect = float(getattr(cfg, "eval_min_effect_size", 0.0))
    metric = str(objective_metric) if objective_metric is not None else str(cfg.objective_metric)
    mode = cfg.objective_mode.lower()
    debug_accept = bool(getattr(cfg, "debug_always_accept", False))

    sandbox_logger.info(
        "LLMCoder JMS sandbox eval: starting evaluation (min_episodes={}, max_episodes={}, max_steps={}, metric='{}', mode='{}', alpha={:.4f}, debug_always_accept={})",
        min_episodes,
        max_episodes,
        max_steps,
        metric,
        mode,
        alpha,
        debug_accept,
    )

    instances = events_pool.acquire_for_eval(max_episodes)
    if not instances:
        sandbox_logger.warning("LLMCoder JMS sandbox eval: no JMS eval instances available; skipping eval.")
        return None

    baseline_vals: List[float] = []
    candidate_vals: List[float] = []
    accepted = False
    episodes_used = 0
    rel_improvement = 0.0
    effect_size = 0.0

    loop_episodes = min(max_episodes, len(instances))
    sandbox_logger.debug(
        "LLMCoder JMS sandbox eval: prepared episodes (loop_episodes={}, pool_size={})",
        loop_episodes,
        len(instances),
    )

    for ep in range(loop_episodes):
        if callable(cand_is_disabled):
            try:
                if bool(cand_is_disabled()):
                    sandbox_logger.warning(
                        "LLMCoder JMS sandbox eval: candidate rule disabled; early stop at episode {} (episodes_used={})",
                        ep,
                        episodes_used,
                    )
                    break
            except Exception:
                pass

        inst = instances[ep]
        inst_file = inst.instance_file

        base_name = getattr(baseline_rule, "__name__", None) or baseline_rule.__class__.__name__
        cand_name = getattr(candidate_rule, "__name__", None) or candidate_rule.__class__.__name__

        m_base = _run_single_rollout_jms(
            inst_file,
            baseline_rule,
            max_steps,
            episode=ep,
            seed=int(getattr(inst, "seed", 0) or 0),
            rollout_label="baseline",
            rule_name=str(base_name),
        )

        m_cand: Optional[Dict[str, float]] = None
        m_cand = _run_single_rollout_jms(
            inst_file,
            candidate_rule,
            max_steps,
            episode=ep,
            seed=int(getattr(inst, "seed", 0) or 0),
            rollout_label="candidate",
            rule_name=str(cand_name),
        )

        bv = float(m_base.get(metric, 0.0))
        cv = float(m_cand.get(metric, 0.0))
        baseline_vals.append(bv)
        candidate_vals.append(cv)
        episodes_used = len(baseline_vals)

        sandbox_logger.debug(
            "LLMCoder JMS sandbox eval: episode {} metric '{}' -> baseline={:.6f}, candidate={:.6f}",
            ep,
            metric,
            bv,
            cv,
        )

        if episodes_used < min_episodes:
            continue

        baseline_mean = sum(baseline_vals) / len(baseline_vals)
        candidate_mean = sum(candidate_vals) / len(candidate_vals)
        denom = abs(baseline_mean) if abs(baseline_mean) > 1e-9 else 1.0
        if mode == "max":
            rel_improvement = (candidate_mean - baseline_mean) / denom
        else:
            rel_improvement = (baseline_mean - candidate_mean) / denom

        effect_size, t_stat = _effect_size_and_t_stat(baseline_vals, candidate_vals, mode)
        t_threshold = _approximate_t_threshold(alpha)

        if bool(getattr(cfg, "eval_fail_fast", False)) and rel_improvement <= 0.0:
            sandbox_logger.info(
                "LLMCoder JMS sandbox eval: fail-fast early reject after {} episodes (baseline={:.6f}, candidate={:.6f}, rel_improve={:.6f}, effect_size={:.6f}, t_stat={:.6f}, t_threshold={:.6f})",
                episodes_used,
                baseline_mean,
                candidate_mean,
                rel_improvement,
                effect_size,
                t_stat,
                t_threshold,
            )
            break

        if getattr(cfg, "debug_always_accept", False):
            accepted = True
            sandbox_logger.info(
                "LLMCoder JMS sandbox eval: debug_always_accept=True, forced accept after {} episodes (baseline={:.6f}, candidate={:.6f}, rel_improve={:.6f}, effect_size={:.6f}, t_stat={:.6f})",
                episodes_used,
                baseline_mean,
                candidate_mean,
                rel_improvement,
                effect_size,
                t_stat,
            )
            break

        if rel_improvement >= cfg.min_relative_improvement and effect_size >= min_effect and t_stat >= t_threshold:
            accepted = True
            sandbox_logger.info(
                "LLMCoder JMS sandbox eval: early accept after {} episodes (baseline={:.6f}, candidate={:.6f}, rel_improve={:.6f}, effect_size={:.6f}, t_stat={:.6f}, t_threshold={:.6f})",
                episodes_used,
                baseline_mean,
                candidate_mean,
                rel_improvement,
                effect_size,
                t_stat,
                t_threshold,
            )
            break

    if not baseline_vals or not candidate_vals:
        return None

    if not accepted:
        baseline_mean = sum(baseline_vals) / len(baseline_vals)
        candidate_mean = sum(candidate_vals) / len(candidate_vals)
        denom = abs(baseline_mean) if abs(baseline_mean) > 1e-9 else 1.0
        if mode == "max":
            rel_improvement = (candidate_mean - baseline_mean) / denom
        else:
            rel_improvement = (baseline_mean - candidate_mean) / denom
        effect_size, t_stat = _effect_size_and_t_stat(baseline_vals, candidate_vals, mode)
        sandbox_logger.info(
            "LLMCoder JMS sandbox eval: final evaluation after {} episodes (baseline={:.6f}, candidate={:.6f}, rel_improve={:.6f}, effect_size={:.6f}, t_stat={:.6f}, accepted={})",
            episodes_used,
            baseline_mean,
            candidate_mean,
            rel_improvement,
            effect_size,
            t_stat,
            False,
        )

    return EvalResult(
        baseline_value=baseline_mean,
        candidate_value=candidate_mean,
        relative_improvement=rel_improvement,
        accepted=accepted,
        episodes_used=episodes_used,
        effect_size=effect_size,
    )
