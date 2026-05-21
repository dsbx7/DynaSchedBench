from __future__ import annotations 

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union

from dotenv import load_dotenv

load_dotenv()

from loguru import logger

from dsbx.Env import DynaSchedEnv
from dsbx.Eval.Metrics import evaluate_trajectory
from dsbx.Logging import init_logging
from dsbx.Sim.Loader import load_instance_from_events
from dsbx.Agents.utils import (
    LLMClient,
    NullLLMClient,
    OpenAICompatClient,
    RetryingLLMClient,
    resolve_llm_endpoint,
)
from dsbx.Agents.LLMScheduler.config import ModelConfig
from dsbx.Agents.LLMScheduler.sampler import choose_by_env_score

from .agent import AsyncDualStreamAgent
from .config import LLMCoderConfig


def _load_jsonl_dict_records(path: Union[str, Path, None]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if path is None:
        return out
    try:
        p = Path(path)
    except Exception:
        return out
    if not p.is_file():
        return out
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except Exception:
        return out
    return out


def _get_client(
    model_cfg: Optional[ModelConfig] = None,
    *,
    llm_debug_dir: Optional[Union[str, Path]] = None,
) -> LLMClient:
    """Construct an LLM client using the shared ModelConfig-based builder.

    If no explicit ``ModelConfig`` is provided, this function uses the default
    ``ModelConfig()`` and lets ``build_llm_client_from_model_config`` resolve
    its fields together with environment variables. This keeps the configuration
    semantics aligned with ``LLMScheduler.runner``.
    """
    import os

    cfg = model_cfg or ModelConfig()

    provider = (
        str(
            getattr(cfg, "provider", None)
            or os.getenv("DYNA_SCHEDBENCH_LLM_PROVIDER")
            or "openai"
        )
    ).lower()
    model = getattr(cfg, "model_name", None) or os.getenv("DYNA_SCHEDBENCH_LLM_MODEL")

    base_url_override = getattr(cfg, "base_url", None)
    api_key, base_url = resolve_llm_endpoint(provider, base_url_override)

    timeout = float(getattr(cfg, "request_timeout", 30.0) or 30.0)
    max_tokens = int(getattr(cfg, "max_tokens", 512) or 512)

    if not api_key or not model:
        return NullLLMClient()

    if llm_debug_dir is not None:
        try:
            os.environ["DYNA_SCHEDBENCH_LLM_DEBUG_DIR"] = str(Path(llm_debug_dir))
        except Exception:
            pass
    else:
        try:
            os.environ.pop("DYNA_SCHEDBENCH_LLM_DEBUG_DIR", None)
        except Exception:
            pass

    base_client = OpenAICompatClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    return RetryingLLMClient(base_client)


def solve(
    events_path: Union[str, Path],
    cfg: Optional[LLMCoderConfig] = None,
    output_path: Optional[Union[str, Path]] = None,
    trajectory_path: Optional[Union[str, Path]] = None,
    eval_episodes: Optional[int] = None,
    eval_max_steps: Optional[int] = None,
    min_relative_improvement: Optional[float] = None,
    complexity_weight: Optional[float] = None,
    eval_pool_size: Optional[int] = None,
    eval_pool_refresh_per_eval: Optional[int] = None,
    eval_max_parallel_candidates: Optional[int] = None,
    agentic_max_iterations: Optional[int] = None,
    agentic_max_plans: Optional[int] = None,
    enable_eval: Optional[bool] = None,
    enable_codegen: Optional[bool] = None,
    debug_always_accept: Optional[bool] = None,
    use_meta_advisor: Optional[bool] = None,
    use_repository: Optional[bool] = None,
    use_performance_trigger: Optional[bool] = None,
    force_sync_codegen_interval: Optional[int] = None,
    force_sync_codegen_timeout: Optional[float] = None,
    force_sync_codegen_min_step: Optional[int] = None,
    model_cfg: Optional[ModelConfig] = None,
) -> Dict[str, Any]:
    """Run LLMCoder on a given events JSON and return results.

    This interface mirrors ``LLMScheduler.runner.solve``: it builds a
    ``DynaSchedEnv`` from ``events_path``, uses ``AsyncDualStreamAgent`` as the
    policy, returns algorithm metadata, Gantt data, evaluation metrics, and
    internal agent statistics, and can optionally write both the overall result
    and LLMCoder trajectory to disk.
    """

    cfg = cfg or LLMCoderConfig()

    if eval_episodes is not None:
        try:
            cfg.eval_episodes = int(eval_episodes)
        except Exception:
            logger.warning("Invalid eval_episodes override: {}", eval_episodes)
    if eval_max_steps is not None:
        try:
            cfg.eval_max_steps = int(eval_max_steps)
        except Exception:
            logger.warning("Invalid eval_max_steps override: {}", eval_max_steps)
    if min_relative_improvement is not None:
        try:
            cfg.min_relative_improvement = float(min_relative_improvement)
        except Exception:
            logger.warning(
                "Invalid min_relative_improvement override: {}",
                min_relative_improvement,
            )
    if complexity_weight is not None:
        try:
            cfg.complexity_weight = float(complexity_weight)
        except Exception:
            logger.warning("Invalid complexity_weight override: {}", complexity_weight)
    if eval_pool_size is not None:
        try:
            cfg.eval_pool_size = int(eval_pool_size)
        except Exception:
            logger.warning("Invalid eval_pool_size override: {}", eval_pool_size)
    if eval_pool_refresh_per_eval is not None:
        try:
            cfg.eval_pool_refresh_per_eval = int(eval_pool_refresh_per_eval)
        except Exception:
            logger.warning(
                "Invalid eval_pool_refresh_per_eval override: {}",
                eval_pool_refresh_per_eval,
            )
    if eval_max_parallel_candidates is not None:
        try:
            cfg.eval_max_parallel_candidates = int(eval_max_parallel_candidates)
        except Exception:
            logger.warning(
                "Invalid eval_max_parallel_candidates override: {}",
                eval_max_parallel_candidates,
            )
    if agentic_max_iterations is not None:
        try:
            cfg.agentic_max_iterations = int(agentic_max_iterations)
        except Exception:
            logger.warning(
                "Invalid agentic_max_iterations override: {}",
                agentic_max_iterations,
            )
    if agentic_max_plans is not None:
        try:
            cfg.agentic_max_plans = int(agentic_max_plans)
        except Exception:
            logger.warning("Invalid agentic_max_plans override: {}", agentic_max_plans)
    if enable_eval is not None:
        try:
            cfg.enable_eval = bool(enable_eval)
        except Exception:
            logger.warning("Invalid enable_eval override: {}", enable_eval)
    if enable_codegen is not None:
        try:
            cfg.enable_codegen = bool(enable_codegen)
        except Exception:
            logger.warning("Invalid enable_codegen override: {}", enable_codegen)
    if debug_always_accept is not None:
        try:
            cfg.debug_always_accept = bool(debug_always_accept)
        except Exception:
            logger.warning("Invalid debug_always_accept override: {}", debug_always_accept)
    if use_meta_advisor is not None:
        try:
            cfg.use_meta_advisor = bool(use_meta_advisor)
        except Exception:
            logger.warning("Invalid use_meta_advisor override: {}", use_meta_advisor)
    if use_repository is not None:
        try:
            cfg.use_repository = bool(use_repository)
        except Exception:
            logger.warning("Invalid use_repository override: {}", use_repository)
    if use_performance_trigger is not None:
        try:
            cfg.use_performance_trigger = bool(use_performance_trigger)
        except Exception:
            logger.warning(
                "Invalid use_performance_trigger override: {}",
                use_performance_trigger,
            )
    if force_sync_codegen_interval is not None:
        try:
            cfg.force_sync_codegen_interval = int(force_sync_codegen_interval)
        except Exception:
            logger.warning(
                "Invalid force_sync_codegen_interval override: {}",
                force_sync_codegen_interval,
            )
    if force_sync_codegen_timeout is not None:
        try:
            cfg.force_sync_codegen_timeout = float(force_sync_codegen_timeout)
        except Exception:
            logger.warning(
                "Invalid force_sync_codegen_timeout override: {}",
                force_sync_codegen_timeout,
            )
    if force_sync_codegen_min_step is not None:
        try:
            cfg.force_sync_codegen_min_step = int(force_sync_codegen_min_step)
        except Exception:
            logger.warning(
                "Invalid force_sync_codegen_min_step override: {}",
                force_sync_codegen_min_step,
            )

    llm_debug_dir = None
    if output_path is not None:
        try:
            llm_debug_dir = Path(output_path).parent
        except Exception:
            llm_debug_dir = None
    client = _get_client(model_cfg, llm_debug_dir=llm_debug_dir)

    events_path = Path(events_path)
    if events_path.is_dir():
        events_file = events_path / "events.jsonl"
    else:
        if events_path.suffix.lower() == ".jsonl":
            events_file = events_path
        else:
            events_file = events_path.with_name("events.jsonl")

    model, events = load_instance_from_events(events_file)
    env = DynaSchedEnv(model, events=events, auto_generate_events=False)

    agent = AsyncDualStreamAgent(llm_client=client, cfg=cfg)
    scenario_info: Dict[str, Any] = {"config_path": str(events_path)}
    agent.reset(scenario_info=scenario_info)

    obs = env.reset()
    done = env.done()
    steps = 0
    max_steps = env.total_operations() * 4 + 1000

    start_time_wall = time.perf_counter()

    while not done and steps < max_steps:
        legal = env.legal_actions()
        if not legal:
            obs = env.advance_if_idle()
            done = env.done()
            continue
        act = agent.act(obs, legal, env)
        if act is None:
            act = choose_by_env_score(legal, env, rollout_steps=0)
            if act is None:
                obs = env.advance_if_idle()
                done = env.done()
                continue
        obs, _, done, _ = env.step(act)
        steps += 1

    traj = env.get_trajectory()
    end_time_wall = time.perf_counter()
    runtime_seconds = float(end_time_wall - start_time_wall)
    metrics = evaluate_trajectory(traj)

    try:
        if isinstance(metrics, dict):
            metrics["runtime_seconds"] = float(runtime_seconds)
    except Exception:
        logger.warning("Failed to attach runtime_seconds to metrics")

    try:
        sim = getattr(env, "_sim", None)
        if sim is not None and hasattr(sim, "get_gantt"):
            gantt = sim.get_gantt()  # type: ignore[assignment]
        else:
            gantt = []
    except Exception:
        gantt = []

    try:
        agent_stats = agent.get_stats()
    except Exception:
        agent_stats = {}

    if isinstance(metrics, dict) and isinstance(agent_stats, dict) and agent_stats:
        try:
            metrics["agent_stats"] = agent_stats
        except Exception:
            logger.warning("Failed to attach agent_stats to metrics")

    result: Dict[str, Any] = {
        "algorithm": "llm-coder",
        "gantt": gantt,
        "metrics": metrics,
        "agent_stats": agent_stats,
        "policy_stats": agent_stats,
    }

    if trajectory_path is not None:
        try:
            from dsbx.Agents.LLMScheduler.logger import TrajectoryLogger

            worker = agent_stats.get("worker") if isinstance(agent_stats, dict) else None
            traj_events = []
            if isinstance(worker, dict):
                val = worker.get("trajectory")
                if isinstance(val, list):
                    traj_events = [x for x in val if isinstance(x, dict)]
                elif worker.get("trajectory_path"):
                    traj_events = _load_jsonl_dict_records(worker.get("trajectory_path"))

            force_sync_events = []
            if isinstance(agent_stats, dict):
                val_fs = agent_stats.get("force_sync_trajectory")
                if isinstance(val_fs, list):
                    force_sync_events = [x for x in val_fs if isinstance(x, dict)]
                elif agent_stats.get("force_sync_trajectory_path"):
                    force_sync_events = _load_jsonl_dict_records(agent_stats.get("force_sync_trajectory_path"))

            all_events = []
            if traj_events:
                all_events.extend(traj_events)
            if force_sync_events:
                all_events.extend(force_sync_events)

            logger_obj = TrajectoryLogger()
            for rec in all_events:
                logger_obj.append(rec)

            # Force trajectory filename to be llmcoder_trajectory.jsonl (matching RACE)
            path = Path(trajectory_path)
            if path.name != "llmcoder_trajectory.jsonl":
                path = path.parent / "llmcoder_trajectory.jsonl"
            
            path.parent.mkdir(parents=True, exist_ok=True)
            logger_obj.dump_jsonl(path)
            result["trajectory_log_path"] = str(path)
        except Exception as exc:
            logger.error("LLMCoder.runner: failed to dump trajectory JSONL: {}", exc)
            result["trajectory_log_path"] = None

    if output_path is not None:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

    return result


def solve_jms_instance(
    instance_path: Union[str, Path],
    cfg: Optional[LLMCoderConfig] = None,
    output_path: Optional[Union[str, Path]] = None,
    trajectory_path: Optional[Union[str, Path]] = None,
    eval_episodes: Optional[int] = None,
    eval_max_steps: Optional[int] = None,
    min_relative_improvement: Optional[float] = None,
    complexity_weight: Optional[float] = None,
    eval_pool_size: Optional[int] = None,
    eval_pool_refresh_per_eval: Optional[int] = None,
    eval_max_parallel_candidates: Optional[int] = None,
    agentic_max_iterations: Optional[int] = None,
    agentic_max_plans: Optional[int] = None,
    enable_eval: Optional[bool] = None,
    enable_codegen: Optional[bool] = None,
    debug_always_accept: Optional[bool] = None,
    use_meta_advisor: Optional[bool] = None,
    use_repository: Optional[bool] = None,
    use_performance_trigger: Optional[bool] = None,
    force_sync_codegen_interval: Optional[int] = None,
    force_sync_codegen_timeout: Optional[float] = None,
    force_sync_codegen_min_step: Optional[int] = None,
    model_cfg: Optional[ModelConfig] = None,
    write_debug_artifacts: bool = True,
) -> Dict[str, Any]:
    """Run LLMCoder on a JMS/GEN-Bench JSONL instance with the JMSSim backend.

    The semantics match ``solve`` on the InputModel+events path, except that the
    environment is built with :meth:`DynaSchedEnv.from_jms_jsonl` and uses
    :class:`JMSSimBackend` plus :class:`JMSSnapshotAdapter` for snapshot and
    action interfaces.
    """

    cfg = cfg or LLMCoderConfig()

    if eval_episodes is not None:
        try:
            cfg.eval_episodes = int(eval_episodes)
        except Exception:
            pass
    if eval_max_steps is not None:
        try:
            cfg.eval_max_steps = int(eval_max_steps)
        except Exception:
            pass
    if min_relative_improvement is not None:
        try:
            cfg.min_relative_improvement = float(min_relative_improvement)
        except Exception:
            pass
    if complexity_weight is not None:
        try:
            cfg.complexity_weight = float(complexity_weight)
        except Exception:
            pass
    if eval_pool_size is not None:
        try:
            cfg.eval_pool_size = int(eval_pool_size)
        except Exception:
            pass
    if eval_pool_refresh_per_eval is not None:
        try:
            cfg.eval_pool_refresh_per_eval = int(eval_pool_refresh_per_eval)
        except Exception:
            pass
    if eval_max_parallel_candidates is not None:
        try:
            cfg.eval_max_parallel_candidates = int(eval_max_parallel_candidates)
        except Exception:
            pass
    if agentic_max_iterations is not None:
        try:
            cfg.agentic_max_iterations = int(agentic_max_iterations)
        except Exception:
            pass
    if agentic_max_plans is not None:
        try:
            cfg.agentic_max_plans = int(agentic_max_plans)
        except Exception:
            pass
    if enable_eval is not None:
        try:
            cfg.enable_eval = bool(enable_eval)
        except Exception:
            pass
    if enable_codegen is not None:
        try:
            cfg.enable_codegen = bool(enable_codegen)
        except Exception:
            pass
    if debug_always_accept is not None:
        try:
            cfg.debug_always_accept = bool(debug_always_accept)
        except Exception:
            pass
    if use_meta_advisor is not None:
        try:
            cfg.use_meta_advisor = bool(use_meta_advisor)
        except Exception:
            pass
    if use_repository is not None:
        try:
            cfg.use_repository = bool(use_repository)
        except Exception:
            pass
    if use_performance_trigger is not None:
        try:
            cfg.use_performance_trigger = bool(use_performance_trigger)
        except Exception:
            pass
    if force_sync_codegen_interval is not None:
        try:
            cfg.force_sync_codegen_interval = int(force_sync_codegen_interval)
        except Exception:
            pass
    if force_sync_codegen_timeout is not None:
        try:
            cfg.force_sync_codegen_timeout = float(force_sync_codegen_timeout)
        except Exception:
            pass
    if force_sync_codegen_min_step is not None:
        try:
            cfg.force_sync_codegen_min_step = int(force_sync_codegen_min_step)
        except Exception:
            pass

    llm_debug_dir = None
    if write_debug_artifacts and output_path is not None:
        try:
            llm_debug_dir = Path(output_path).parent
        except Exception:
            llm_debug_dir = None
    client = _get_client(model_cfg, llm_debug_dir=llm_debug_dir)

    instance_path = Path(instance_path)
    if not instance_path.is_file():
        raise FileNotFoundError(f"JMS/GEN-Bench JSONL instance not found: {instance_path}")

    env_traj_path = None
    if write_debug_artifacts:
        if output_path is not None:
            try:
                env_traj_path = Path(output_path).parent / "env_trajectory.jsonl"
            except Exception:
                env_traj_path = None
        elif trajectory_path is not None:
            try:
                env_traj_path = Path(trajectory_path).parent / "env_trajectory.jsonl"
            except Exception:
                env_traj_path = None

    # Initialize logging (like RACE's runner_jms.py)
    try:
        run_id = instance_path.stem
    except Exception:
        run_id = None
    
    init_logging(
        component="A",
        command="run_jms",
        log_level="INFO",
        run_id=run_id,
    )

    env = DynaSchedEnv.from_jms_jsonl(
        instance_path,
        track_trajectory=bool(write_debug_artifacts),
        traj_stream_path=env_traj_path,
    )

    agent = AsyncDualStreamAgent(llm_client=client, cfg=cfg)
    scenario_info: Dict[str, Any] = {"config_path": str(instance_path)}
    agent.reset(scenario_info=scenario_info)

    obs = env.reset()
    done = env.done()
    steps = 0
    max_steps = env.total_operations() * 4 + 1000

    start_time_wall = time.perf_counter()

    while not done and steps < max_steps:
        legal = env.legal_actions()
        if not legal:
            obs = env.advance_if_idle()
            done = env.done()
            continue
        act = agent.act(obs, legal, env)
        if act is None:
            act = choose_by_env_score(legal, env, rollout_steps=0)
            if act is None:
                obs = env.advance_if_idle()
                done = env.done()
                continue
        obs, _, done, _ = env.step(act)
        steps += 1

    traj = env.get_trajectory()
    end_time_wall = time.perf_counter()
    runtime_seconds = float(end_time_wall - start_time_wall)
    metrics = evaluate_trajectory(traj)
    try:
        env.close()
    except Exception:
        pass

    try:
        if isinstance(metrics, dict):
            metrics["runtime_seconds"] = float(runtime_seconds)
    except Exception:
        pass

    try:
        sim = getattr(env, "_sim", None)
        if sim is not None and hasattr(sim, "get_gantt"):
            gantt = sim.get_gantt()  # type: ignore[assignment]
        else:
            gantt = []
    except Exception:
        gantt = []

    try:
        agent_stats = agent.get_stats()
    except Exception:
        agent_stats = {}

    if isinstance(metrics, dict) and isinstance(agent_stats, dict) and agent_stats:
        try:
            metrics["agent_stats"] = agent_stats
        except Exception:
            pass

    result: Dict[str, Any] = {
        "algorithm": "llm-coder-jms",
        "gantt": gantt,
        "metrics": metrics,
        "agent_stats": agent_stats,
        "policy_stats": agent_stats,
    }

    if write_debug_artifacts and trajectory_path is not None:
        try:
            from dsbx.Agents.LLMScheduler.logger import TrajectoryLogger

            worker = agent_stats.get("worker") if isinstance(agent_stats, dict) else None
            traj_events = []
            if isinstance(worker, dict):
                val = worker.get("trajectory")
                if isinstance(val, list):
                    traj_events = [x for x in val if isinstance(x, dict)]
                elif worker.get("trajectory_path"):
                    traj_events = _load_jsonl_dict_records(worker.get("trajectory_path"))

            force_sync_events = []
            if isinstance(agent_stats, dict):
                val_fs = agent_stats.get("force_sync_trajectory")
                if isinstance(val_fs, list):
                    force_sync_events = [x for x in val_fs if isinstance(x, dict)]
                elif agent_stats.get("force_sync_trajectory_path"):
                    force_sync_events = _load_jsonl_dict_records(agent_stats.get("force_sync_trajectory_path"))

            all_events = []
            if traj_events:
                all_events.extend(traj_events)
            if force_sync_events:
                all_events.extend(force_sync_events)

            logger_obj = TrajectoryLogger()
            for rec in all_events:
                logger_obj.append(rec)

            # Force trajectory filename to be llmcoder_trajectory.jsonl (matching RACE)
            path = Path(trajectory_path)
            if path.name != "llmcoder_trajectory.jsonl":
                path = path.parent / "llmcoder_trajectory.jsonl"
            
            path.parent.mkdir(parents=True, exist_ok=True)
            logger_obj.dump_jsonl(path)
            result["trajectory_log_path"] = str(path)
        except Exception as exc:
            logger.error("LLMCoder.runner_jms: failed to dump trajectory JSONL: {}", exc)
            result["trajectory_log_path"] = None

    if output_path is not None:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

    return result
