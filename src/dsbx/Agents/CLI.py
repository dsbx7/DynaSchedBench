from __future__ import annotations

import json
import time
import resource
import sys
from pathlib import Path
from typing import Any, Dict, Optional

try:  # Best-effort .env loading for LLM API keys
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency
    load_dotenv = None  # type: ignore[assignment]

if load_dotenv is not None:  # pragma: no cover - trivial wrapper
    try:
        load_dotenv()  # Load variables from .env into os.environ for CLI runs
    except Exception:
        pass

import typer
from loguru import logger
from typing_extensions import Annotated

from dsbx.Gen import load_input_model
from dsbx.Logging import init_logging
from dsbx.Env import DynaSchedEnv
from dsbx.Eval import StepRecord, Trajectory
from dsbx.Eval.Metrics import evaluate_trajectory
from dsbx.Agents import SPTAgent
from dsbx.Agents.LLMCoder import AsyncDualStreamAgent
from dsbx.Agents.LLMCoder.config import LLMCoderConfig
from dsbx.Agents.LLMScheduler import (
    LlmPolicyAgent,
    LLMPolicy,
    OType,
    SType,
    SampleConfig,
)
from dsbx.Agents.LLMScheduler.config import CognitiveConfig, InfoLevel, InteractionMode, RefinementStrategy
from dsbx.Sim.Snapshot import Snapshot
from dsbx.Sim.Loader import load_instance_from_events
from dsbx.Sim.Events import PriorityChangeEvent


app = typer.Typer(
    name="dsbx-agent",
    help="Run agents on DynaSchedBench environments.",
    add_completion=False,
)


AVAILABLE_AGENTS = [
    ("spt", "Shortest Processing Time baseline agent."),
    ("random", "Uniform random baseline agent (samples from legal actions)."),
    ("pdr:<OP_RULE>:<MACHINE_RULE>", "PDR agent; see job/machine rules below."),
    ("gp-simplegp-best", "GP-based dispatching agent using a fixed best-of-run simplegp rule."),
    ("ga", "Genetic Algorithm-based online rescheduling agent."),
    ("de", "Differential Evolution-based online rescheduling agent."),
    ("pso", "Particle Swarm Optimization-based online rescheduling agent."),
    ("cmaes", "CMA-ES-based continuous optimization over action scoring weights."),
    ("sa", "Simulated Annealing-based online rescheduling agent."),
    ("ts", "Tabu Search-based online rescheduling agent."),
    ("moea", "MOEA/D-style decomposition-based multi-objective EA over actions."),
    ("nsga2", "NSGA-II multi-objective EA over actions."),
    ("llm-coder", "LLMCoder AsyncDualStreamAgent (LLM-assisted heuristic)."),
    (
        "llm-scheduler",
        "LLM-based scheduling policy with cognitive prompts (O1/O2/O3/O4 \u00d7 S1/S2/S3).",
    ),
]


def _print_available_agents() -> None:
    """Print a structured list of available agents and PDR rule options."""

    # Top-level agent entries
    print("Available agents:\n")
    for name, desc in AVAILABLE_AGENTS:
        print(f"  {name:<28} {desc}")

    print("\nPDR job selection rules (OP_RULE):")
    job_rules = [
        ("SPT", "Shortest Processing Time"),
        ("LPT", "Longest Processing Time"),
        ("MWKR", "Most Work Remaining"),
        ("LWKR", "Least Work Remaining"),
        ("MOPNR", "Most Operations Remaining"),
        ("LOPNR", "Least Operations Remaining"),
        ("FIFO", "First In First Out"),
        ("LIFO", "Last In First Out"),
    ]
    for code, desc in job_rules:
        print(f"  {code:<8} {desc}")

    print("\nPDR machine selection rules (MACHINE_RULE):")
    machine_rules = [
        ("LIT", "Least Idle Time (earliest available)"),
        ("LWL", "Least Workload"),
        ("SPT", "Shortest Processing Time on machine"),
    ]
    for code, desc in machine_rules:
        print(f"  {code:<8} {desc}")


def _build_gantt_from_snapshot(snap: Snapshot) -> Dict[str, Any]:
    machines = []
    for m in snap.machines:
        tasks = []
        for seg in m.schedule_segments:
            tasks.append(
                {
                    "job_id": seg.job_id,
                    "op_id": seg.op_id,
                    "start": float(seg.start),
                    "end": float(seg.end),
                    "is_frozen": bool(seg.is_frozen),
                }
            )
        machines.append(
            {
                "machine_id": m.machine_id,
                "group": m.group,
                "tasks": tasks,
            }
        )

    jobs = []
    for j in snap.jobs:
        ops = []
        for op in j.ops:
            if op.start_time is None or op.end_time is None:
                continue
            ops.append(
                {
                    "op_id": op.op_id,
                    "index": int(op.index),
                    "machine_group": op.machine_group,
                    "start": float(op.start_time),
                    "end": float(op.end_time),
                }
            )
        jobs.append(
            {
                "job_id": j.job_id,
                "family": j.family,
                "release_time": float(j.release_time),
                "due_date": float(j.due_date),
                "completion_time": float(j.completion_time) if j.completion_time is not None else None,
                "ops": ops,
            }
        )

    return {
        "time": float(snap.time),
        "machines": machines,
        "jobs": jobs,
    }


def _replay_trajectory_from_jsonl(env, traj_path: Path, initial_obs: Dict[str, Any]):
    """Replay a disk-backed summary trajectory JSONL on a fresh environment.

    Caller is expected to have just called ``env.reset()`` and to pass the
    initial observation as ``initial_obs``. This helper applies
    ``advance_if_idle`` and ``step(action)`` calls to mirror the summary
    records in ``traj_path`` and returns ``(steps_replayed, last_obs)``.
    """

    steps = 0
    obs = initial_obs

    try:
        with traj_path.open("r", encoding="utf-8") as f:  # type: ignore[arg-type]
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue

                rtype = rec.get("type")
                if rtype in {"header", "final_snapshot"}:
                    continue
                if rtype != "summary":
                    continue

                info = rec.get("info") or {}
                rec_type = info.get("type")
                has_decision = bool(rec.get("has_decision"))
                action_summary = rec.get("action")

                # Reset records correspond to env.reset() we already executed.
                if rec_type == "reset":
                    continue

                if rec_type == "advance":
                    try:
                        obs = env.advance_if_idle()
                        steps += 1
                    except Exception:
                        logger.exception(
                            "A.run: failed to replay advance_if_idle from trajectory"
                        )
                    continue

                if has_decision and isinstance(action_summary, dict):
                    act = {
                        "job_id": action_summary.get("job_id"),
                        "machine_group": action_summary.get("machine_group"),
                    }
                    mid = action_summary.get("machine_id")
                    if mid is not None:
                        act["machine_id"] = mid
                    try:
                        obs, _, _, _ = env.step(act)
                        steps += 1
                    except Exception:
                        logger.exception(
                            "A.run: failed to replay step(action) from trajectory"
                        )
                    continue
    except Exception:
        logger.exception("A.run: failed while replaying trajectory from {}", traj_path)

    return steps, obs


def _build_agent(agent_name: str, agent_params: Optional[Dict[str, Any]] = None) -> object:
    """Build an agent instance from name and optional parameters.
    
    Args:
        agent_name: Name of the agent (e.g., 'spt', 'pdr', 'pdr:SPT:LIT', 'llm')
        agent_params: Optional dictionary of agent-specific parameters
        
    Returns:
        Agent instance
    """
    if agent_params is None:
        agent_params = {}
    
    name = agent_name.lower()

    research_only_agents = {"dan", "iddqn", "ppo-oc", "ppo_oc", "hmpsac", "drlsa", "drlsa-routing"}
    if name in research_only_agents:
        raise typer.BadParameter(
            "This research agent is not included in the PyPI package. "
            "See research/agents/ for the original experiment assets."
        )
    
    # PDR agents: support format like "pdr:SPT:LIT" or just "pdr"
    if name.startswith("pdr"):
        from dsbx.Agents.PDRs import PDRAgent

        # Parse PDR rule parameters from agent name
        # Format: pdr:SPT:LIT or just pdr (defaults to SPT:LIT)
        parts = agent_name.split(":")
        op_rule = parts[1] if len(parts) > 1 else "SPT"
        machine_rule = parts[2] if len(parts) > 2 else "LIT"
        
        # Override with explicit params if provided
        op_rule = agent_params.get("op_rule", op_rule)
        machine_rule = agent_params.get("machine_rule", machine_rule)
        random_seed = agent_params.get("random_seed")
        
        return PDRAgent(op_rule=op_rule, machine_rule=machine_rule, random_seed=random_seed)
    
    if name == "spt":
        return SPTAgent()

    if name == "random":
        from dsbx.Agents.Random import RandomAgent

        random_seed = agent_params.get("random_seed")
        if random_seed is not None:
            try:
                random_seed = int(random_seed)
            except Exception:
                random_seed = None
        return RandomAgent(random_seed=random_seed)

    if name in ("gp-simplegp-best", "gp_simplegp_best"):
        from dsbx.Agents.GPAdapter import GPAgent

        # Best-of-run rule extracted from the Java simplegp out.stat file.
        rule_expr = "(- (min (max NWT WIQ) (- (+ (min SL PT) (min NIQ NINQ)) (max (min (min SL PT) W) (/ (/ (+ OWT WKR) (* rDD NOR)) (min (max WKR WIQ) (- rDD rDD)))))) (- (min (max (+ WKR NOR) (max NINQ NIQ)) (+ (- WKR rFDD) (+ WKR NINQ))) (+ PT (+ (min SL PT) (min NIQ NINQ)))))"

        return GPAgent(rule_expr=rule_expr)

    if name == "ga":
        from dsbx.Agents.GA import GAAgent

        kwargs: Dict[str, Any] = {}
        if agent_params.get("ga_population_size") is not None:
            kwargs["population_size"] = int(agent_params["ga_population_size"])
        if agent_params.get("ga_generations") is not None:
            kwargs["generations"] = int(agent_params["ga_generations"])
        if agent_params.get("ga_crossover_prob") is not None:
            kwargs["crossover_prob"] = float(agent_params["ga_crossover_prob"])
        if agent_params.get("ga_mutation_prob") is not None:
            kwargs["mutation_prob"] = float(agent_params["ga_mutation_prob"])
        if agent_params.get("ga_mutation_sigma") is not None:
            kwargs["mutation_sigma"] = float(agent_params["ga_mutation_sigma"])
        if agent_params.get("ga_rollout_steps") is not None:
            kwargs["rollout_steps"] = int(agent_params["ga_rollout_steps"])
        if agent_params.get("ga_random_seed") is not None:
            kwargs["random_seed"] = int(agent_params["ga_random_seed"])

        return GAAgent(**kwargs)
    
    if name == "de":
        from dsbx.Agents.DE import DEAgent

        kwargs_de: Dict[str, Any] = {}
        if agent_params.get("de_population_size") is not None:
            kwargs_de["population_size"] = int(agent_params["de_population_size"])
        if agent_params.get("de_generations") is not None:
            kwargs_de["generations"] = int(agent_params["de_generations"])
        if agent_params.get("de_mutation_scale") is not None:
            kwargs_de["mutation_scale"] = float(agent_params["de_mutation_scale"])
        if agent_params.get("de_crossover_prob") is not None:
            kwargs_de["crossover_prob"] = float(agent_params["de_crossover_prob"])
        if agent_params.get("de_rollout_steps") is not None:
            kwargs_de["rollout_steps"] = int(agent_params["de_rollout_steps"])
        if agent_params.get("de_random_seed") is not None:
            kwargs_de["random_seed"] = int(agent_params["de_random_seed"])

        return DEAgent(**kwargs_de)
    
    if name == "pso":
        from dsbx.Agents.PSO import PSOAgent

        kwargs_pso: Dict[str, Any] = {}
        if agent_params.get("pso_swarm_size") is not None:
            kwargs_pso["swarm_size"] = int(agent_params["pso_swarm_size"])
        if agent_params.get("pso_iterations") is not None:
            kwargs_pso["iterations"] = int(agent_params["pso_iterations"])
        if agent_params.get("pso_inertia") is not None:
            kwargs_pso["inertia"] = float(agent_params["pso_inertia"])
        if agent_params.get("pso_cognitive_coeff") is not None:
            kwargs_pso["cognitive_coeff"] = float(agent_params["pso_cognitive_coeff"])
        if agent_params.get("pso_social_coeff") is not None:
            kwargs_pso["social_coeff"] = float(agent_params["pso_social_coeff"])
        if agent_params.get("pso_rollout_steps") is not None:
            kwargs_pso["rollout_steps"] = int(agent_params["pso_rollout_steps"])
        if agent_params.get("pso_random_seed") is not None:
            kwargs_pso["random_seed"] = int(agent_params["pso_random_seed"])

        return PSOAgent(**kwargs_pso)
    
    if name == "cmaes":
        from dsbx.Agents.CMAES import CMAESAgent

        kwargs_cma: Dict[str, Any] = {}
        if agent_params.get("cmaes_population_size") is not None:
            kwargs_cma["population_size"] = int(agent_params["cmaes_population_size"])
        if agent_params.get("cmaes_generations") is not None:
            kwargs_cma["generations"] = int(agent_params["cmaes_generations"])
        if agent_params.get("cmaes_sigma0") is not None:
            kwargs_cma["sigma0"] = float(agent_params["cmaes_sigma0"])
        if agent_params.get("cmaes_rollout_steps") is not None:
            kwargs_cma["rollout_steps"] = int(agent_params["cmaes_rollout_steps"])
        if agent_params.get("cmaes_random_seed") is not None:
            kwargs_cma["random_seed"] = int(agent_params["cmaes_random_seed"])

        return CMAESAgent(**kwargs_cma)
    
    if name == "sa":
        from dsbx.Agents.SA import SAAgent

        kwargs_sa: Dict[str, Any] = {}
        if agent_params.get("sa_max_iterations") is not None:
            kwargs_sa["max_iterations"] = int(agent_params["sa_max_iterations"])
        if agent_params.get("sa_initial_temperature") is not None:
            kwargs_sa["initial_temperature"] = float(agent_params["sa_initial_temperature"])
        if agent_params.get("sa_cooling_rate") is not None:
            kwargs_sa["cooling_rate"] = float(agent_params["sa_cooling_rate"])
        if agent_params.get("sa_rollout_steps") is not None:
            kwargs_sa["rollout_steps"] = int(agent_params["sa_rollout_steps"])
        if agent_params.get("sa_random_seed") is not None:
            kwargs_sa["random_seed"] = int(agent_params["sa_random_seed"])

        return SAAgent(**kwargs_sa)
    
    if name == "ts":
        from dsbx.Agents.TS import TSAgent

        kwargs_ts: Dict[str, Any] = {}
        if agent_params.get("ts_max_iterations") is not None:
            kwargs_ts["max_iterations"] = int(agent_params["ts_max_iterations"])
        if agent_params.get("ts_tabu_tenure") is not None:
            kwargs_ts["tabu_tenure"] = int(agent_params["ts_tabu_tenure"])
        if agent_params.get("ts_rollout_steps") is not None:
            kwargs_ts["rollout_steps"] = int(agent_params["ts_rollout_steps"])
        if agent_params.get("ts_random_seed") is not None:
            kwargs_ts["random_seed"] = int(agent_params["ts_random_seed"])

        return TSAgent(**kwargs_ts)
    
    if name == "moea":
        from dsbx.Agents.MOEA import MOEAAgent

        kwargs_m: Dict[str, Any] = {}
        if agent_params.get("moea_population_size") is not None:
            kwargs_m["population_size"] = int(agent_params["moea_population_size"])
        if agent_params.get("moea_generations") is not None:
            kwargs_m["generations"] = int(agent_params["moea_generations"])
        if agent_params.get("moea_mutation_prob") is not None:
            kwargs_m["mutation_prob"] = float(agent_params["moea_mutation_prob"])
        if agent_params.get("moea_rollout_steps") is not None:
            kwargs_m["rollout_steps"] = int(agent_params["moea_rollout_steps"])
        if agent_params.get("moea_random_seed") is not None:
            kwargs_m["random_seed"] = int(agent_params["moea_random_seed"])

        return MOEAAgent(**kwargs_m)
    
    if name in ("nsga2", "nsga-ii"):
        from dsbx.Agents.NSGA2 import NSGA2Agent

        kwargs_n: Dict[str, Any] = {}
        if agent_params.get("nsga2_population_size") is not None:
            kwargs_n["population_size"] = int(agent_params["nsga2_population_size"])
        if agent_params.get("nsga2_generations") is not None:
            kwargs_n["generations"] = int(agent_params["nsga2_generations"])
        if agent_params.get("nsga2_mutation_prob") is not None:
            kwargs_n["mutation_prob"] = float(agent_params["nsga2_mutation_prob"])
        if agent_params.get("nsga2_rollout_steps") is not None:
            kwargs_n["rollout_steps"] = int(agent_params["nsga2_rollout_steps"])
        if agent_params.get("nsga2_random_seed") is not None:
            kwargs_n["random_seed"] = int(agent_params["nsga2_random_seed"])

        return NSGA2Agent(**kwargs_n)

    if name in ("llm-coder", "llm_coder", "llmcoder"):
        import os

        from dsbx.Agents.utils import (  # type: ignore[import]
            NullLLMClient as _NullLLMClient,
            OpenAICompatClient,
            RetryingLLMClient,
            resolve_llm_endpoint,
        )

        provider = (
            str(
                agent_params.get("llm_provider")
                or os.getenv("DYNA_SCHEDBENCH_LLM_PROVIDER")
                or "openai"
            )
        ).lower()
        model = agent_params.get("llm_model") or os.getenv("DYNA_SCHEDBENCH_LLM_MODEL", "gpt-5-nano-ca")
        base_url_override = agent_params.get("llm_base_url")

        api_key, base_url = resolve_llm_endpoint(provider, base_url_override)

        timeout = float(agent_params.get("llm_timeout") or 9999.0)

        if api_key:
            client = RetryingLLMClient(OpenAICompatClient(api_key=api_key, model=model, base_url=base_url, timeout=timeout))
        else:
            logger.warning(
                "No LLM API key found for provider '{}' (DYNA_SCHEDBENCH_LLM_API_KEY or provider-specific env); "
                "using NullLLMClient (AsyncDualStreamAgent will stay on fallback heuristic).",
                provider,
            )
            client = _NullLLMClient()

        coder_cfg = LLMCoderConfig()

        if agent_params.get("llm_temperature") is not None:
            coder_cfg.llm_temperature = float(agent_params["llm_temperature"])
        if agent_params.get("llm_top_p") is not None:
            coder_cfg.llm_top_p = float(agent_params["llm_top_p"])
        if agent_params.get("llm_top_k") is not None:
            coder_cfg.llm_top_k = int(agent_params["llm_top_k"])
        if agent_params.get("llm_timeout") is not None:
            coder_cfg.llm_timeout = float(agent_params["llm_timeout"])

        if agent_params.get("llm_coder_eval_max_steps") is not None:
            coder_cfg.eval_max_steps = int(agent_params["llm_coder_eval_max_steps"])
        if agent_params.get("llm_coder_eval_min_episodes") is not None:
            coder_cfg.eval_min_episodes = max(1, int(agent_params["llm_coder_eval_min_episodes"]))
        if agent_params.get("llm_coder_eval_max_episodes") is not None:
            coder_cfg.eval_max_episodes = max(1, int(agent_params["llm_coder_eval_max_episodes"]))
        if agent_params.get("llm_coder_eval_episodes") is not None:
            ep = int(agent_params["llm_coder_eval_episodes"])
            coder_cfg.eval_episodes = ep
            if agent_params.get("llm_coder_eval_min_episodes") is None and agent_params.get("llm_coder_eval_max_episodes") is None:
                coder_cfg.eval_min_episodes = max(1, ep)
                coder_cfg.eval_max_episodes = max(1, ep)
        if agent_params.get("llm_coder_eval_significance_level") is not None:
            coder_cfg.eval_significance_level = float(agent_params["llm_coder_eval_significance_level"])
        if agent_params.get("llm_coder_eval_min_effect_size") is not None:
            coder_cfg.eval_min_effect_size = float(agent_params["llm_coder_eval_min_effect_size"])
        if agent_params.get("llm_coder_eval_fail_fast") is not None:
            coder_cfg.eval_fail_fast = bool(agent_params["llm_coder_eval_fail_fast"])
        if agent_params.get("llm_coder_n_candidates") is not None:
            coder_cfg.n_candidates = int(agent_params["llm_coder_n_candidates"])
        if agent_params.get("llm_coder_objective_metrics") is not None:
            coder_cfg.objective_metrics = str(agent_params["llm_coder_objective_metrics"])
        if agent_params.get("llm_coder_max_steps_between_updates") is not None:
            coder_cfg.max_steps_between_updates = int(agent_params["llm_coder_max_steps_between_updates"])
        if agent_params.get("llm_coder_min_relative_improvement") is not None:
            coder_cfg.min_relative_improvement = float(agent_params["llm_coder_min_relative_improvement"])
        if agent_params.get("llm_coder_eval_pool_size") is not None:
            coder_cfg.eval_pool_size = int(agent_params["llm_coder_eval_pool_size"])
        if agent_params.get("llm_coder_eval_pool_refresh_per_eval") is not None:
            coder_cfg.eval_pool_refresh_per_eval = int(agent_params["llm_coder_eval_pool_refresh_per_eval"])
        if agent_params.get("llm_coder_eval_max_parallel_candidates") is not None:
            coder_cfg.eval_max_parallel_candidates = int(agent_params["llm_coder_eval_max_parallel_candidates"])
        if agent_params.get("llm_coder_force_sync_interval") is not None:
            coder_cfg.force_sync_codegen_interval = int(agent_params["llm_coder_force_sync_interval"])
        if agent_params.get("llm_coder_force_sync_timeout") is not None:
            coder_cfg.force_sync_codegen_timeout = float(agent_params["llm_coder_force_sync_timeout"])
        if agent_params.get("llm_coder_force_sync_min_step") is not None:
            coder_cfg.force_sync_codegen_min_step = int(agent_params["llm_coder_force_sync_min_step"])
        if agent_params.get("llm_coder_use_meta_advisor") is not None:
            coder_cfg.use_meta_advisor = bool(agent_params["llm_coder_use_meta_advisor"])
        if agent_params.get("llm_coder_use_performance_trigger") is not None:
            coder_cfg.use_performance_trigger = bool(agent_params["llm_coder_use_performance_trigger"])
        if agent_params.get("llm_coder_eval_use_subprocess_sandbox") is not None:
            coder_cfg.eval_use_subprocess_sandbox = bool(agent_params["llm_coder_eval_use_subprocess_sandbox"])
        if agent_params.get("llm_coder_eval_subprocess_timeout") is not None:
            coder_cfg.eval_subprocess_timeout = float(agent_params["llm_coder_eval_subprocess_timeout"])
        if agent_params.get("llm_coder_state_profile_window_size") is not None:
            coder_cfg.state_profile_window_size = int(agent_params["llm_coder_state_profile_window_size"])
        if agent_params.get("llm_coder_agentic_max_iterations") is not None:
            coder_cfg.agentic_max_iterations = int(agent_params["llm_coder_agentic_max_iterations"])
        if agent_params.get("llm_coder_use_repository") is not None:
            coder_cfg.use_repository = bool(agent_params["llm_coder_use_repository"])

        return AsyncDualStreamAgent(llm_client=client, cfg=coder_cfg)

    if name in ("llm-scheduler", "llm_scheduler", "llmscheduler"):
        import os

        from dsbx.Agents.utils import (  # type: ignore[import]
            NullLLMClient as _NullLLMClient,
            OpenAICompatClient,
            resolve_llm_endpoint,
        )

        provider = (
            str(
                agent_params.get("llm_provider")
                or os.getenv("DYNA_SCHEDBENCH_LLM_PROVIDER")
                or "openai"
            )
        ).lower()
        model = agent_params.get("llm_model") or os.getenv("DYNA_SCHEDBENCH_LLM_MODEL", "gpt-4o-mini")
        base_url_override = agent_params.get("llm_base_url")

        api_key, base_url = resolve_llm_endpoint(provider, base_url_override)

        timeout = float(agent_params.get("llm_timeout") or 9999.0)

        if api_key:
            client = OpenAICompatClient(api_key=api_key, model=model, base_url=base_url, timeout=timeout)
        else:
            logger.warning(
                "No LLM API key found for provider '{}' (DYNA_SCHEDBENCH_LLM_API_KEY or provider-specific env); "
                "using NullLLMClient (llm-scheduler will fall back to heuristic/env scoring).",
                provider,
            )
            client = _NullLLMClient()

        o_type = OType.O1
        s_type = SType.S1

        sample_cfg = SampleConfig()
        if agent_params.get("llm_temperature") is not None:
            sample_cfg.temperature = float(agent_params["llm_temperature"])
        if agent_params.get("llm_top_p") is not None:
            sample_cfg.top_p = float(agent_params["llm_top_p"])
        if agent_params.get("llm_top_k") is not None:
            sample_cfg.top_k = int(agent_params["llm_top_k"])
        if agent_params.get("llm_sched_n_samples") is not None:
            sample_cfg.n = int(agent_params["llm_sched_n_samples"])
        if agent_params.get("llm_sched_rollout_steps") is not None:
            sample_cfg.rollout_steps = int(agent_params["llm_sched_rollout_steps"])

        # Cognitive configuration (info level, interaction mode, pruning, few-shot, etc.)
        cog_cfg = CognitiveConfig()

        info_level_str = agent_params.get("llm_sched_info_level")
        if info_level_str is not None:
            code = str(info_level_str).upper()
            if code in {"L1", "LEVEL1", "1"}:
                cog_cfg.info_level = InfoLevel.LEVEL_1_MYOPIC
            elif code in {"L2", "LEVEL2", "2"}:
                cog_cfg.info_level = InfoLevel.LEVEL_2_STATISTICAL
            elif code in {"L3", "LEVEL3", "3"}:
                cog_cfg.info_level = InfoLevel.LEVEL_3_STRUCTURAL
            else:  # pragma: no cover - defensive
                raise RuntimeError(
                    f"Invalid llm-scheduler info level '{info_level_str}'. Expected one of: L1, L2, L3."
                )

        mode_str = agent_params.get("llm_sched_mode")
        if mode_str is not None:
            m = str(mode_str).lower()
            if m in {"direct", "d"}:
                cog_cfg.mode = InteractionMode.DIRECT
            elif m in {"cot", "chain-of-thought", "chain_of_thought"}:
                cog_cfg.mode = InteractionMode.COT
            elif m in {"tool", "tool_use", "tool-use", "tools"}:
                cog_cfg.mode = InteractionMode.TOOL_USE
            else:  # pragma: no cover - defensive
                raise RuntimeError(
                    f"Invalid llm-scheduler interaction mode '{mode_str}'. Expected one of: direct, cot, tool."
                )

        if agent_params.get("llm_sched_use_few_shot") is not None:
            cog_cfg.use_few_shot = bool(agent_params["llm_sched_use_few_shot"])
        if agent_params.get("llm_sched_max_examples") is not None:
            cog_cfg.max_examples = int(agent_params["llm_sched_max_examples"])
        if agent_params.get("llm_sched_max_candidates") is not None:
            try:
                _mc = int(agent_params["llm_sched_max_candidates"])
            except Exception:
                _mc = cog_cfg.max_candidate_actions
            cog_cfg.max_candidate_actions = _mc
        if agent_params.get("llm_sched_prompt_variant") is not None:
            try:
                cog_cfg.prompt_variant = str(agent_params["llm_sched_prompt_variant"])
            except Exception:
                cog_cfg.prompt_variant = ""
        if agent_params.get("llm_sched_select_machine") is not None:
            cog_cfg.select_machine = bool(agent_params["llm_sched_select_machine"])

        ref_str = agent_params.get("llm_sched_refinement")
        if ref_str is not None:
            code = str(ref_str).strip().upper()
            if code in {"GREEDY", "G"}:
                cog_cfg.refinement = RefinementStrategy.GREEDY
            elif code in {"REFLECTION", "REFLECT", "R"}:
                cog_cfg.refinement = RefinementStrategy.REFLECTION
            elif code in {"BEST_OF_N", "BEST-OF-N", "BESTOFN", "B"}:
                cog_cfg.refinement = RefinementStrategy.BEST_OF_N
            else:  # pragma: no cover - defensive
                raise RuntimeError(
                    f"Invalid llm-scheduler refinement '{ref_str}'. Expected one of: greedy, reflection, best-of-n."
                )
        if agent_params.get("llm_sched_reflection_rounds") is not None:
            cog_cfg.reflection_rounds = int(agent_params["llm_sched_reflection_rounds"])
        if agent_params.get("llm_sched_voting_n") is not None:
            cog_cfg.voting_n = int(agent_params["llm_sched_voting_n"])
        if agent_params.get("llm_sched_reflection_temperature") is not None:
            try:
                cog_cfg.reflection_temperature = float(agent_params["llm_sched_reflection_temperature"])
            except Exception:
                pass
        if agent_params.get("llm_sched_best_of_n_temperature") is not None:
            try:
                cog_cfg.best_of_n_temperature = float(agent_params["llm_sched_best_of_n_temperature"])
            except Exception:
                pass

        policy = LLMPolicy(o_type, s_type, client, sample_cfg, cognitive_cfg=cog_cfg)
        return LlmPolicyAgent(policy)

    if name.startswith("llm"):
        raise RuntimeError(
            "The generic 'llm' agent is no longer supported because it depended on "
            "the external algorithms.llm_scheduler package. Please use 'llm-coder' "
            "or 'spt' instead.",
        )
    
    raise ValueError(f"Unknown agent name: {agent_name}")


@app.command(name="list-agents")
def list_agents() -> None:
    """List available agents and PDR rule options for the A CLI.

    This command prints:
    - Built-in agent names (e.g., ``spt``, ``pdr:SPT:LIT``, ``llm-coder``);
    - The generic PDR agent pattern ``pdr:<OP_RULE>:<MACHINE_RULE>``;
    - All supported OP_RULE and MACHINE_RULE values with a short description.

    It does not run any simulation.
    """

    _print_available_agents()


@app.command(name="agent-help")
def agent_help(
    agent: Annotated[
        str,
        typer.Argument(
            help="Agent name to describe (e.g., 'spt', 'pdr', 'llm-coder', 'llm-scheduler').",
        ),
    ],
) -> None:
    """Show which CLI parameters are relevant for a given agent."""

    name = agent.lower()

    if name == "spt":
        print("Agent 'spt' (Shortest Processing Time).")
        print("\nUses only global options of 'dsbx-agent run':")
        print("  -d / --dir, -o / --output, -a / --agent, --max-steps")
        print("\nNo extra agent-specific parameters.")
        return

    if name.startswith("pdr"):
        print("Agent 'pdr:<OP_RULE>:<MACHINE_RULE>' (priority dispatching rule).")
        print("\nEncodes its behaviour in the agent name itself:")
        print("  pdr:<OP_RULE>:<MACHINE_RULE>")
        print("See 'A list-agents' for all OP_RULE and MACHINE_RULE options.")
        print("\nNo extra agent-specific CLI options besides:")
        print("  -d / --dir, -o / --output, -a / --agent, --max-steps")
        return

    if name in ("ga",):
        print("Agent 'ga' (Genetic Algorithm-based online rescheduling).")
        print("\nGA options:")
        print("  --ga-population-size INT         Population size per decision (default: 16).")
        print("  --ga-generations INT             Number of GA generations per decision (default: 8).")
        print("  --ga-crossover-prob FLOAT        Crossover probability (default: 0.8).")
        print("  --ga-mutation-prob FLOAT         Mutation probability per gene (default: 0.2).")
        print("  --ga-mutation-sigma FLOAT        Stddev of Gaussian mutation noise (default: 0.5).")
        print("  --ga-rollout-steps INT           Use quick_rollout_score with given steps; 0=estimate_action_score.")
        print("  --ga-random-seed INT             Random seed for GA sampling (optional).")
        return

    if name in ("de",):
        print("Agent 'de' (Differential Evolution-based online rescheduling).")
        print("\nDE options:")
        print("  --de-population-size INT         Population size per decision (default: 16).")
        print("  --de-generations INT             Number of DE generations per decision (default: 8).")
        print("  --de-mutation-scale FLOAT        Differential mutation scale factor F (default: 0.5).")
        print("  --de-crossover-prob FLOAT        Crossover probability CR (default: 0.9).")
        print("  --de-rollout-steps INT           If >0, use quick_rollout_score(steps); else estimate_action_score.")
        print("  --de-random-seed INT             Random seed for DE sampling (optional).")
        return

    if name in ("pso",):
        print("Agent 'pso' (Particle Swarm Optimization-based online rescheduling).")
        print("\nPSO options:")
        print("  --pso-swarm-size INT             Swarm size per decision (default: 16).")
        print("  --pso-iterations INT             Number of PSO iterations per decision (default: 8).")
        print("  --pso-inertia FLOAT              Inertia weight w (default: 0.7).")
        print("  --pso-cognitive-coeff FLOAT      Cognitive coefficient c1 (default: 1.5).")
        print("  --pso-social-coeff FLOAT         Social coefficient c2 (default: 1.5).")
        print("  --pso-rollout-steps INT          If >0, use quick_rollout_score(steps); else estimate_action_score.")
        print("  --pso-random-seed INT            Random seed for PSO sampling (optional).")
        return

    if name in ("cmaes",):
        print("Agent 'cmaes' (CMA-ES-based continuous optimization over action scoring weights).")
        print("\nCMA-ES options:")
        print("  --cmaes-population-size INT      Population size per decision (default: 16).")
        print("  --cmaes-generations INT          Number of CMA-ES generations per decision (default: 8).")
        print("  --cmaes-sigma0 FLOAT             Initial global step size sigma0 (default: 0.5).")
        print("  --cmaes-rollout-steps INT        If >0, use quick_rollout_score(steps); else estimate_action_score.")
        print("  --cmaes-random-seed INT          Random seed for CMA-ES sampling (optional).")
        return

    if name in ("sa",):
        print("Agent 'sa' (Simulated Annealing-based online rescheduling).")
        print("\nSA options:")
        print("  --sa-max-iterations INT          Max SA iterations per decision (default: 64).")
        print("  --sa-initial-temperature FLOAT   Initial temperature (default: 1.0).")
        print("  --sa-cooling-rate FLOAT          Geometric cooling rate per iteration (default: 0.95).")
        print("  --sa-rollout-steps INT           If >0, use quick_rollout_score(steps); else estimate_action_score.")
        print("  --sa-random-seed INT             Random seed for SA sampling (optional).")
        return

    if name in ("ts",):
        print("Agent 'ts' (Tabu Search-based online rescheduling).")
        print("\nTS options:")
        print("  --ts-max-iterations INT          Max TS iterations per decision (default: 64).")
        print("  --ts-tabu-tenure INT             Length of tabu list (default: 5).")
        print("  --ts-rollout-steps INT           If >0, use quick_rollout_score(steps); else estimate_action_score.")
        print("  --ts-random-seed INT             Random seed for TS sampling (optional).")
        return

    if name in ("moea",):
        print("Agent 'moea' (MOEA/D-style decomposition-based multi-objective EA over actions).")
        print("\nMOEA/D options:")
        print("  --moea-population-size INT       Number of weight vectors / subproblems per decision (default: 16).")
        print("  --moea-generations INT           Number of weight resampling rounds per decision (default: 4).")
        print("  --moea-mutation-prob FLOAT       (Reserved) Mutation probability, kept for compatibility.")
        print("  --moea-rollout-steps INT         Second objective: quick_rollout_score(steps); 0=only estimate_action_score.")
        print("  --moea-random-seed INT           Random seed for MOEA/D weight sampling (optional).")
        return

    if name in ("nsga2", "nsga-ii"):
        print("Agent 'nsga2' (NSGA-II multi-objective EA over actions).")
        print("\nNSGA-II options:")
        print("  --nsga2-population-size INT      Population size per decision (default: 16).")
        print("  --nsga2-generations INT          Number of EA generations per decision (default: 4).")
        print("  --nsga2-mutation-prob FLOAT      Mutation probability when sampling new actions.")
        print("  --nsga2-rollout-steps INT        Second objective: quick_rollout_score(steps); 0=only estimate_action_score.")
        print("  --nsga2-random-seed INT          Random seed for NSGA-II sampling (optional).")
        return


    if name in ("llm-coder", "llm_coder", "llmcoder"):
        print("Agent 'llm-coder' (LLMCoder AsyncDualStreamAgent).")
        print("\nGeneral LLM options:")
        print("  --llm-provider TEXT               LLM HTTP provider: openai, dashscope, chatanywhere, local, vllm.")
        print("  --llm-model TEXT                  Override LLM model name.")
        print("  --llm-base-url TEXT               Override LLM HTTP base URL.")
        print("  --llm-temperature FLOAT           Sampling temperature.")
        print("  --llm-top-p FLOAT                 Top-p for nucleus sampling.")
        print("  --llm-top-k INT                   Top-k for sampling.")
        print("  --llm-timeout FLOAT               Timeout (seconds) for LLM calls.")
        print("\nLLMCoder-specific options:")
        print("  --llm-coder-eval-max-steps INT            Max steps per evaluation episode.")
        print("  --llm-coder-eval-episodes INT             Number of evaluation episodes.")
        print("  --llm-coder-n-candidates INT              Number of candidates generated per codegen call.")
        print("  --llm-coder-objective-metrics TEXT        Comma-separated metric keys for Scheme C (randomly pick one per iteration).")
        print("  --llm-coder-max-steps-between-updates INT Max env steps between rule updates.")
        print("  --llm-coder-min-relative-improvement FLOAT Min relative improvement to accept new rule.")
        print("  --llm-coder-eval-pool-size INT            Size of sandbox evaluation events pool.")
        print("  --llm-coder-eval-pool-refresh-per-eval INT Number of pool entries refreshed after each evaluation.")
        print("  --llm-coder-eval-max-parallel-candidates INT Max number of candidates evaluated in parallel.")
        return
 
    if name in ("llm-scheduler", "llm_scheduler", "llmscheduler"):
        print("Agent 'llm-scheduler' (LLM-based scheduling policy with cognitive prompts).")
        print("\nGeneral LLM options:")
        print("  --llm-provider TEXT               LLM HTTP provider: openai, dashscope, chatanywhere, local, vllm.")
        print("  --llm-model TEXT                  Override LLM model name.")
        print("  --llm-base-url TEXT               Override base URL for the LLM HTTP API (e.g. https://api.openai.com/v1).")
        print("  --llm-temperature FLOAT           Sampling temperature for LLM calls (where supported).")
        print("  --llm-top-p FLOAT                 Top-p for nucleus sampling (where supported).")
        print("  --llm-top-k INT                   Top-k for sampling (where supported).")
        print("  --llm-timeout FLOAT               Timeout in seconds for LLM HTTP requests.")
        print("  --llm-base-url TEXT               Override LLM HTTP base URL.")
        print("  --llm-temperature FLOAT           Sampling temperature.")
        print("  --llm-top-p FLOAT                 Top-p for nucleus sampling.")
        print("  --llm-top-k INT                   Top-k for sampling.")
        print("  --llm-timeout FLOAT               Timeout (seconds) for LLM calls.")
        print("\nLLM Scheduler-specific options:")
        print("  --llm-sched-n-samples INT         Number of samples per LLM call.")
        print("  --llm-sched-rollout-steps INT     Rollout steps for env-based scoring / fallback.")
        print("  --llm-sched-info-level [L1|L2|L3] Info level for cognitive prompts (myopic/statistical/structural).")
        print("  --llm-sched-mode [direct|cot|tool] Interaction mode: direct, chain-of-thought, or tool-use.")
        print("  --llm-sched-use-few-shot / --no-llm-sched-use-few-shot")
        print("                                    Enable or disable few-shot examples in prompts.")
        print("  --llm-sched-max-examples INT      Max number of few-shot examples to include.")
        print("  --llm-sched-max-candidates INT   Max number of candidate actions shown to the LLM per decision (0 = no limit).")
        print("  --llm-sched-select-machine / --no-llm-sched-select-machine")
        print("                                    Model actions at machine granularity (job_id+group+machine).")
        return

    print(f"Unknown agent '{agent}'. Use 'A list-agents' to see available agents.")
    raise typer.Exit(code=1)


@app.command(name="run")
def run_agent(
    instance_dir: Annotated[
        Path,
        typer.Option(
            "-d",
            "--dir",
            exists=True,
            readable=True,
            help="Path to a generated instance directory (output of `dsbx-gen gen`).",
        ),
    ],
    out_dir: Annotated[
        Path,
        typer.Option("-o", "--output", help="Directory to store trajectory, metrics, and gantt."),
    ],
    save_trajectory: Annotated[
        bool,
        typer.Option(
            "--save-trajectory/--no-save-trajectory",
            help="Whether to write trajectory.json to the output directory.",
        ),
    ] = True,
    save_trajectory_light: Annotated[
        bool,
        typer.Option(
            "--save-trajectory-light/--no-save-trajectory-light",
            help="Whether to stream-write trajectory_light.jsonl (for resume/replay).",
        ),
    ] = True,
    agent: Annotated[
        str,
        typer.Option(
            "-a",
            "--agent",
            help=(
                "Agent name: e.g. 'spt', 'pdr:SPT:LIT', or 'llm-coder'. "
                "For generic PDR agents, use the pattern 'pdr:<OP_RULE>:<MACHINE_RULE>'."
            ),
        ),
    ] = "pdr:SPT:LIT",
    max_steps: Annotated[
        int,
        typer.Option(help="Maximum number of decision steps to take (safety bound)."),
    ] = 10_000,
    random_seed: Annotated[
        Optional[int],
        typer.Option(
            "--random-seed",
            help="Optional random seed for stochastic baselines (e.g., RandomAgent) and tie-breaking.",
        ),
    ] = None,
    llm_provider: Annotated[
        Optional[str],
        typer.Option(
            "--llm-provider",
            help=(
                "Provider for the LLM HTTP API (e.g. openai, dashscope, chatanywhere, local, vllm). "
                "If omitted, DYNA_SCHEDBENCH_LLM_PROVIDER or 'openai' is used."
            ),
        ),
    ] = None,
    llm_model: Annotated[
        Optional[str],
        typer.Option(
            "--llm-model",
            help="Override LLM model name for 'llm-coder' / 'llm-scheduler' agents.",
        ),
    ] = None,
    llm_base_url: Annotated[
        Optional[str],
        typer.Option(
            "--llm-base-url",
            help="Override base URL for the LLM HTTP API (e.g. https://api.openai.com/v1).",
        ),
    ] = None,
    llm_temperature: Annotated[
        Optional[float],
        typer.Option(
            "--llm-temperature",
            help="Sampling temperature for LLM calls (where supported).",
        ),
    ] = None,
    llm_top_p: Annotated[
        Optional[float],
        typer.Option(
            "--llm-top-p",
            help="Top-p parameter for nucleus sampling (where supported).",
        ),
    ] = None,
    llm_top_k: Annotated[
        Optional[int],
        typer.Option(
            "--llm-top-k",
            help="Top-k parameter for sampling (where supported).",
        ),
    ] = None,
    llm_timeout: Annotated[
        Optional[float],
        typer.Option(
            "--llm-timeout",
            help="Timeout in seconds for LLM HTTP requests.",
        ),
    ] = None,
    llm_coder_eval_max_steps: Annotated[
        Optional[int],
        typer.Option(
            "--llm-coder-eval-max-steps",
            help="[llm-coder] Max steps per evaluation episode.",
        ),
    ] = None,
    llm_coder_eval_episodes: Annotated[
        Optional[int],
        typer.Option(
            "--llm-coder-eval-episodes",
            help="[llm-coder] Number of evaluation episodes per candidate rule.",
        ),
    ] = None,
    llm_coder_eval_min_episodes: Annotated[
        Optional[int],
        typer.Option(
            "--llm-coder-eval-min-episodes",
            help="[llm-coder] Minimum episodes before sequential test decisions (fail-fast / early accept).",
        ),
    ] = None,
    llm_coder_eval_max_episodes: Annotated[
        Optional[int],
        typer.Option(
            "--llm-coder-eval-max-episodes",
            help="[llm-coder] Maximum episodes budget for sequential test.",
        ),
    ] = None,
    llm_coder_eval_significance_level: Annotated[
        Optional[float],
        typer.Option(
            "--llm-coder-eval-significance-level",
            help="[llm-coder] Significance level alpha for sequential test (e.g., 0.2 for engineering-tolerant acceptance).",
        ),
    ] = None,
    llm_coder_eval_min_effect_size: Annotated[
        Optional[float],
        typer.Option(
            "--llm-coder-eval-min-effect-size",
            help="[llm-coder] Minimum required effect size for acceptance (engineering guardrail).",
        ),
    ] = None,
    llm_coder_eval_fail_fast: Annotated[
        bool,
        typer.Option(
            "--llm-coder-eval-fail-fast/--no-llm-coder-eval-fail-fast",
            help="[llm-coder] Enable fail-fast early reject when rel_improvement<=0 after eval_min_episodes.",
        ),
    ] = False,
    llm_coder_n_candidates: Annotated[
        Optional[int],
        typer.Option(
            "--llm-coder-n-candidates",
            help="[llm-coder] Number of candidates generated per codegen call.",
        ),
    ] = None,
    llm_coder_objective_metrics: Annotated[
        Optional[str],
        typer.Option(
            "--llm-coder-objective-metrics",
            help="[llm-coder] Comma-separated metric keys for Scheme C (randomly pick one per iteration).",
        ),
    ] = None,
    llm_coder_max_steps_between_updates: Annotated[
        Optional[int],
        typer.Option(
            "--llm-coder-max-steps-between-updates",
            help="[llm-coder] Max environment steps between rule updates.",
        ),
    ] = None,
    llm_coder_min_relative_improvement: Annotated[
        Optional[float],
        typer.Option(
            "--llm-coder-min-relative-improvement",
            help="[llm-coder] Minimum relative improvement required to accept new rule.",
        ),
    ] = None,
    llm_coder_eval_pool_size: Annotated[
        Optional[int],
        typer.Option(
            "--llm-coder-eval-pool-size",
            help="[llm-coder] Size of sandbox evaluation events pool.",
        ),
    ] = None,
    llm_coder_eval_pool_refresh_per_eval: Annotated[
        Optional[int],
        typer.Option(
            "--llm-coder-eval-pool-refresh-per-eval",
            help="[llm-coder] Number of pool entries refreshed after each sandbox evaluation.",
        ),
    ] = None,
    llm_coder_eval_max_parallel_candidates: Annotated[
        Optional[int],
        typer.Option(
            "--llm-coder-eval-max-parallel-candidates",
            help="[llm-coder] Max number of candidate rules evaluated in parallel (0/1=sequential).",
        ),
    ] = None,
    llm_coder_force_sync_interval: Annotated[
        Optional[int],
        typer.Option(
            "--llm-coder-force-sync-interval",
            help="[llm-coder] Environment steps between forced synchronous codegen calls (0=disable).",
        ),
    ] = None,
    llm_coder_force_sync_timeout: Annotated[
        Optional[float],
        typer.Option(
            "--llm-coder-force-sync-timeout",
            help="[llm-coder] Max wall-clock seconds per forced synchronous codegen call.",
        ),
    ] = None,
    llm_coder_force_sync_min_step: Annotated[
        Optional[int],
        typer.Option(
            "--llm-coder-force-sync-min-step",
            help="[llm-coder] Start forced synchronous codegen only after this env step.",
        ),
    ] = None,
    llm_coder_use_meta_advisor: Annotated[
        bool,
        typer.Option(
            "--llm-coder-use-meta-advisor/--no-llm-coder-use-meta-advisor",
            help="[llm-coder] Enable or disable MetaConfigAdvisor (disable to keep CLI eval params stable).",
        ),
    ] = True,
    llm_coder_eval_use_subprocess_sandbox: Annotated[
        bool,
        typer.Option(
            "--llm-coder-eval-use-subprocess-sandbox/--no-llm-coder-eval-use-subprocess-sandbox",
            help="[llm-coder] Evaluate candidate rules in a separate subprocess sandbox (stronger isolation).",
        ),
    ] = False,
    llm_coder_eval_subprocess_timeout: Annotated[
        Optional[float],
        typer.Option(
            "--llm-coder-eval-subprocess-timeout",
            help="[llm-coder] Timeout seconds for subprocess sandbox per episode.",
        ),
    ] = None,
    llm_coder_state_profile_window_size: Annotated[
        Optional[int],
        typer.Option(
            "--llm-coder-state-profile-window-size",
            help="[llm-coder] Window size for state_profile_window (distributional context).",
        ),
    ] = None,
    llm_coder_agentic_max_iterations: Annotated[
        Optional[int],
        typer.Option(
            "--llm-coder-agentic-max-iterations",
            help="[llm-coder] Max agentic iterations per codegen call (1 = single-pass).",
        ),
    ] = None,
    llm_coder_use_repository: Annotated[
        bool,
        typer.Option(
            "--llm-coder-use-repository/--no-llm-coder-use-repository",
            help="[llm-coder] Enable or disable the rule repository (warm-start and persistence).",
        ),
    ] = True,
    llm_coder_use_performance_trigger: Annotated[
        bool,
        typer.Option(
            "--llm-coder-use-performance-trigger/--no-llm-coder-use-performance-trigger",
            help="[llm-coder] Enable or disable performance-based trigger gating for codegen.",
        ),
    ] = True,
    llm_sched_n_samples: Annotated[
        Optional[int],
        typer.Option(
            "--llm-sched-n-samples",
            help="[llm-scheduler] Number of samples per LLM call.",
        ),
    ] = None,
    llm_sched_rollout_steps: Annotated[
        Optional[int],
        typer.Option(
            "--llm-sched-rollout-steps",
            help="[llm-scheduler] Rollout steps for env-based scoring.",
        ),
    ] = None,
    llm_sched_info_level: Annotated[
        Optional[str],
        typer.Option(
            "--llm-sched-info-level",
            help="[llm-scheduler] Info level for cognitive prompts: L1, L2, or L3.",
        ),
    ] = None,
    llm_sched_mode: Annotated[
        Optional[str],
        typer.Option(
            "--llm-sched-mode",
            help="[llm-scheduler] Interaction mode: direct, cot, or tool.",
        ),
    ] = None,
    llm_sched_use_few_shot: Annotated[
        bool,
        typer.Option(
            "--llm-sched-use-few-shot/--no-llm-sched-use-few-shot",
            help="[llm-scheduler] Enable or disable few-shot examples in prompts.",
        ),
    ] = True,
    llm_sched_max_examples: Annotated[
        Optional[int],
        typer.Option(
            "--llm-sched-max-examples",
            help="[llm-scheduler] Max number of few-shot examples to include.",
        ),
    ] = None,
    llm_sched_max_candidates: Annotated[
        Optional[int],
        typer.Option(
            "--llm-sched-max-candidates",
            help="[llm-scheduler] Max number of candidate actions shown to the LLM per decision (0 = no limit).",
        ),
    ] = None,
    llm_sched_prompt_variant: Annotated[
        Optional[str],
        typer.Option(
            "--llm-sched-prompt-variant",
            help=(
                "[llm-scheduler] Prompt ablation variant selector (V1..V6). "
                "If unset, uses the standard prompt for the selected info level."
            ),
        ),
    ] = None,
    llm_sched_select_machine: Annotated[
        bool,
        typer.Option(
            "--llm-sched-select-machine/--no-llm-sched-select-machine",
            help="[llm-scheduler] Model actions at machine granularity (job_id+group+machine).",
        ),
    ] = True,
    llm_sched_refinement: Annotated[
        Optional[str],
        typer.Option(
            "--llm-sched-refinement",
            help="[llm-scheduler] Refinement strategy: greedy, reflection, or best-of-n.",
        ),
    ] = None,
    llm_sched_reflection_rounds: Annotated[
        Optional[int],
        typer.Option(
            "--llm-sched-reflection-rounds",
            help="[llm-scheduler] Number of reflection audit rounds when refinement=reflection.",
        ),
    ] = None,
    llm_sched_voting_n: Annotated[
        Optional[int],
        typer.Option(
            "--llm-sched-voting-n",
            help="[llm-scheduler] Best-of-N voting sample count when refinement=best-of-n.",
        ),
    ] = None,
    llm_sched_reflection_temperature: Annotated[
        Optional[float],
        typer.Option(
            "--llm-sched-reflection-temperature",
            help="[llm-scheduler] Sampling temperature used during REFLECTION refinement (default: 0.3).",
        ),
    ] = None,
    llm_sched_best_of_n_temperature: Annotated[
        Optional[float],
        typer.Option(
            "--llm-sched-best-of-n-temperature",
            help="[llm-scheduler] Sampling temperature used during BEST_OF_N refinement (default: 0.7).",
        ),
    ] = None,
    ga_population_size: Annotated[
        Optional[int],
        typer.Option(
            "--ga-population-size",
            help="[ga] Population size per decision (online GA).",
        ),
    ] = None,
    ga_generations: Annotated[
        Optional[int],
        typer.Option(
            "--ga-generations",
            help="[ga] Number of GA generations per decision.",
        ),
    ] = None,
    ga_crossover_prob: Annotated[
        Optional[float],
        typer.Option(
            "--ga-crossover-prob",
            help="[ga] Crossover probability.",
        ),
    ] = None,
    ga_mutation_prob: Annotated[
        Optional[float],
        typer.Option(
            "--ga-mutation-prob",
            help="[ga] Mutation probability per gene.",
        ),
    ] = None,
    ga_mutation_sigma: Annotated[
        Optional[float],
        typer.Option(
            "--ga-mutation-sigma",
            help="[ga] Stddev of Gaussian mutation noise.",
        ),
    ] = None,
    ga_rollout_steps: Annotated[
        Optional[int],
        typer.Option(
            "--ga-rollout-steps",
            help="[ga] If >0, use quick_rollout_score(steps); else use estimate_action_score.",
        ),
    ] = None,
    ga_random_seed: Annotated[
        Optional[int],
        typer.Option(
            "--ga-random-seed",
            help="[ga] Random seed for GA sampling.",
        ),
    ] = None,
    de_population_size: Annotated[
        Optional[int],
        typer.Option(
            "--de-population-size",
            help="[de] Population size per decision.",
        ),
    ] = None,
    de_generations: Annotated[
        Optional[int],
        typer.Option(
            "--de-generations",
            help="[de] Number of DE generations per decision.",
        ),
    ] = None,
    de_mutation_scale: Annotated[
        Optional[float],
        typer.Option(
            "--de-mutation-scale",
            help="[de] Differential mutation scale factor F.",
        ),
    ] = None,
    de_crossover_prob: Annotated[
        Optional[float],
        typer.Option(
            "--de-crossover-prob",
            help="[de] Crossover probability CR.",
        ),
    ] = None,
    de_rollout_steps: Annotated[
        Optional[int],
        typer.Option(
            "--de-rollout-steps",
            help="[de] If >0, use quick_rollout_score(steps); else use estimate_action_score.",
        ),
    ] = None,
    de_random_seed: Annotated[
        Optional[int],
        typer.Option(
            "--de-random-seed",
            help="[de] Random seed for DE sampling.",
        ),
    ] = None,
    pso_swarm_size: Annotated[
        Optional[int],
        typer.Option(
            "--pso-swarm-size",
            help="[pso] Swarm size per decision.",
        ),
    ] = None,
    pso_iterations: Annotated[
        Optional[int],
        typer.Option(
            "--pso-iterations",
            help="[pso] Number of PSO iterations per decision.",
        ),
    ] = None,
    pso_inertia: Annotated[
        Optional[float],
        typer.Option(
            "--pso-inertia",
            help="[pso] Inertia weight w.",
        ),
    ] = None,
    pso_cognitive_coeff: Annotated[
        Optional[float],
        typer.Option(
            "--pso-cognitive-coeff",
            help="[pso] Cognitive coefficient c1.",
        ),
    ] = None,
    pso_social_coeff: Annotated[
        Optional[float],
        typer.Option(
            "--pso-social-coeff",
            help="[pso] Social coefficient c2.",
        ),
    ] = None,
    pso_rollout_steps: Annotated[
        Optional[int],
        typer.Option(
            "--pso-rollout-steps",
            help="[pso] If >0, use quick_rollout_score(steps); else use estimate_action_score.",
        ),
    ] = None,
    pso_random_seed: Annotated[
        Optional[int],
        typer.Option(
            "--pso-random-seed",
            help="[pso] Random seed for PSO sampling.",
        ),
    ] = None,
    cmaes_population_size: Annotated[
        Optional[int],
        typer.Option(
            "--cmaes-population-size",
            help="[cmaes] Population size per decision.",
        ),
    ] = None,
    cmaes_generations: Annotated[
        Optional[int],
        typer.Option(
            "--cmaes-generations",
            help="[cmaes] Number of CMA-ES generations per decision.",
        ),
    ] = None,
    cmaes_sigma0: Annotated[
        Optional[float],
        typer.Option(
            "--cmaes-sigma0",
            help="[cmaes] Initial global step size sigma0.",
        ),
    ] = None,
    cmaes_rollout_steps: Annotated[
        Optional[int],
        typer.Option(
            "--cmaes-rollout-steps",
            help="[cmaes] If >0, use quick_rollout_score(steps); else use estimate_action_score.",
        ),
    ] = None,
    cmaes_random_seed: Annotated[
        Optional[int],
        typer.Option(
            "--cmaes-random-seed",
            help="[cmaes] Random seed for CMA-ES sampling.",
        ),
    ] = None,
    sa_max_iterations: Annotated[
        Optional[int],
        typer.Option(
            "--sa-max-iterations",
            help="[sa] Max SA iterations per decision.",
        ),
    ] = None,
    sa_initial_temperature: Annotated[
        Optional[float],
        typer.Option(
            "--sa-initial-temperature",
            help="[sa] Initial temperature.",
        ),
    ] = None,
    sa_cooling_rate: Annotated[
        Optional[float],
        typer.Option(
            "--sa-cooling-rate",
            help="[sa] Geometric cooling rate per iteration.",
        ),
    ] = None,
    sa_rollout_steps: Annotated[
        Optional[int],
        typer.Option(
            "--sa-rollout-steps",
            help="[sa] If >0, use quick_rollout_score(steps); else use estimate_action_score.",
        ),
    ] = None,
    sa_random_seed: Annotated[
        Optional[int],
        typer.Option(
            "--sa-random-seed",
            help="[sa] Random seed for SA sampling.",
        ),
    ] = None,
    ts_max_iterations: Annotated[
        Optional[int],
        typer.Option(
            "--ts-max-iterations",
            help="[ts] Max TS iterations per decision.",
        ),
    ] = None,
    ts_tabu_tenure: Annotated[
        Optional[int],
        typer.Option(
            "--ts-tabu-tenure",
            help="[ts] Length of tabu list.",
        ),
    ] = None,
    ts_rollout_steps: Annotated[
        Optional[int],
        typer.Option(
            "--ts-rollout-steps",
            help="[ts] If >0, use quick_rollout_score(steps); else estimate_action_score.",
        ),
    ] = None,
    ts_random_seed: Annotated[
        Optional[int],
        typer.Option(
            "--ts-random-seed",
            help="[ts] Random seed for TS sampling.",
        ),
    ] = None,
    moea_population_size: Annotated[
        Optional[int],
        typer.Option(
            "--moea-population-size",
            help="[moea] Population size per decision.",
        ),
    ] = None,
    moea_generations: Annotated[
        Optional[int],
        typer.Option(
            "--moea-generations",
            help="[moea] Number of EA generations per decision.",
        ),
    ] = None,
    moea_mutation_prob: Annotated[
        Optional[float],
        typer.Option(
            "--moea-mutation-prob",
            help="[moea] Mutation probability when sampling new actions.",
        ),
    ] = None,
    moea_rollout_steps: Annotated[
        Optional[int],
        typer.Option(
            "--moea-rollout-steps",
            help="[moea] If >0, use quick_rollout_score(steps) as second objective; else only estimate_action_score.",
        ),
    ] = None,
    moea_random_seed: Annotated[
        Optional[int],
        typer.Option(
            "--moea-random-seed",
            help="[moea] Random seed for MOEA sampling.",
        ),
    ] = None,
    nsga2_population_size: Annotated[
        Optional[int],
        typer.Option(
            "--nsga2-population-size",
            help="[nsga2] Population size per decision.",
        ),
    ] = None,
    nsga2_generations: Annotated[
        Optional[int],
        typer.Option(
            "--nsga2-generations",
            help="[nsga2] Number of EA generations per decision.",
        ),
    ] = None,
    nsga2_mutation_prob: Annotated[
        Optional[float],
        typer.Option(
            "--nsga2-mutation-prob",
            help="[nsga2] Mutation probability when sampling new actions.",
        ),
    ] = None,
    nsga2_rollout_steps: Annotated[
        Optional[int],
        typer.Option(
            "--nsga2-rollout-steps",
            help="[nsga2] If >0, use quick_rollout_score(steps) as second objective; else only estimate_action_score.",
        ),
    ] = None,
    nsga2_random_seed: Annotated[
        Optional[int],
        typer.Option(
            "--nsga2-random-seed",
            help="[nsga2] Random seed for NSGA-II sampling.",
        ),
    ] = None,
    resume_from_trajectory: Annotated[
        Optional[Path],
        typer.Option(
            "--resume-from-trajectory",
            help=(
                "If set, replay a previous summary trajectory JSONL on the fresh "
                "environment before continuing the simulation. Intended for "
                "log-based resume workflows."
            ),
        ),
    ] = None,
    replay_log_timestamp: Annotated[
        Optional[str],
        typer.Option(
            "--replay-log-timestamp",
            help=(
                "If set, use this timestamp as the leading component of the A.run "
                "run_replay logging directory, keeping replay logs grouped by the "
                "original run's timestamp."
            ),
        ),
    ] = None,
    replay_log_command: Annotated[
        Optional[str],
        typer.Option(
            "--replay-log-command",
            help=(
                "Optional override for the logging command name used when replaying "
                "trajectories (e.g. 'run_replay2')."
            ),
        ),
    ] = None,
    agent_stats_offset: Annotated[
        Optional[Path],
        typer.Option(
            "--agent-stats-offset",
            help=(
                "Optional JSON file containing historical agent_stats offsets (e.g. "
                "LLM token counts) to be added to the agent before simulation."
            ),
        ),
    ] = None,
) -> None:
    """Run an agent on a pre-generated instance directory.

    The instance is expected to be produced by ``dsbx-gen gen`` and is defined by the
    files in ``instance_dir`` (typically::

        input_model.json
        events.jsonl
        static_jobs.json
        static_machines.json

    The full InputModel is loaded from ``input_model.json`` when present,
    ensuring that no configuration is simplified or inferred at evaluation
    time.
    """

    if not instance_dir.is_dir():
        msg = f"{instance_dir} is not a directory; please pass a generated instance directory (e.g. runs/.../seed_001)."
        logger.error(msg)
        print(msg)
        raise typer.Exit(code=3)

    events_file = instance_dir / "events.jsonl"
    if not events_file.exists():
        msg = f"Expected 'events.jsonl' under {instance_dir}, but it does not exist."
        logger.error(msg)
        print(msg)
        raise typer.Exit(code=3)

    if replay_log_command:
        log_command = replay_log_command
    else:
        log_command = "run_replay" if replay_log_timestamp else "run"
    init_logging(
        component="A",
        command=log_command,
        log_level="INFO",
        run_id=instance_dir.name,
        timestamp_prefix=replay_log_timestamp,
    )
    model, events = load_instance_from_events(events_file)
    traj_stream_path = (out_dir / "trajectory_light.jsonl") if save_trajectory_light else None

    env = DynaSchedEnv(
        model,
        events=events,
        auto_generate_events=False,
        traj_stream_path=traj_stream_path,
    )

    scale_cfg = getattr(model, "scale", None)
    jobs_total = getattr(scale_cfg, "jobs_total", None) if scale_cfg is not None else None
    horizon = getattr(scale_cfg, "horizon", None) if scale_cfg is not None else None
    logger.info(
        "A.run: loaded instance from {} with events={} jobs_total={} horizon={} max_steps={}",
        events_file,
        len(events),
        jobs_total,
        horizon,
        max_steps,
    )

    agent_params: Dict[str, Any] = {}
    if random_seed is not None:
        agent_params["random_seed"] = random_seed
    if llm_provider is not None:
        agent_params["llm_provider"] = llm_provider
    if llm_model is not None:
        agent_params["llm_model"] = llm_model
    if llm_base_url is not None:
        agent_params["llm_base_url"] = llm_base_url
    if llm_temperature is not None:
        agent_params["llm_temperature"] = llm_temperature
    if llm_top_p is not None:
        agent_params["llm_top_p"] = llm_top_p
    if llm_top_k is not None:
        agent_params["llm_top_k"] = llm_top_k
    if llm_timeout is not None:
        agent_params["llm_timeout"] = llm_timeout

    if llm_coder_eval_max_steps is not None:
        agent_params["llm_coder_eval_max_steps"] = llm_coder_eval_max_steps
    if llm_coder_eval_episodes is not None:
        agent_params["llm_coder_eval_episodes"] = llm_coder_eval_episodes
    if llm_coder_eval_min_episodes is not None:
        agent_params["llm_coder_eval_min_episodes"] = llm_coder_eval_min_episodes
    if llm_coder_eval_max_episodes is not None:
        agent_params["llm_coder_eval_max_episodes"] = llm_coder_eval_max_episodes
    if llm_coder_eval_significance_level is not None:
        agent_params["llm_coder_eval_significance_level"] = llm_coder_eval_significance_level
    if llm_coder_eval_min_effect_size is not None:
        agent_params["llm_coder_eval_min_effect_size"] = llm_coder_eval_min_effect_size
    agent_params["llm_coder_eval_fail_fast"] = bool(llm_coder_eval_fail_fast)
    if llm_coder_n_candidates is not None:
        agent_params["llm_coder_n_candidates"] = llm_coder_n_candidates
    if llm_coder_objective_metrics is not None:
        agent_params["llm_coder_objective_metrics"] = llm_coder_objective_metrics
    if llm_coder_max_steps_between_updates is not None:
        agent_params["llm_coder_max_steps_between_updates"] = llm_coder_max_steps_between_updates
    if llm_coder_min_relative_improvement is not None:
        agent_params["llm_coder_min_relative_improvement"] = llm_coder_min_relative_improvement
    if llm_coder_eval_pool_size is not None:
        agent_params["llm_coder_eval_pool_size"] = llm_coder_eval_pool_size
    if llm_coder_eval_pool_refresh_per_eval is not None:
        agent_params["llm_coder_eval_pool_refresh_per_eval"] = llm_coder_eval_pool_refresh_per_eval
    if llm_coder_eval_max_parallel_candidates is not None:
        agent_params["llm_coder_eval_max_parallel_candidates"] = llm_coder_eval_max_parallel_candidates
    if llm_coder_force_sync_interval is not None:
        agent_params["llm_coder_force_sync_interval"] = llm_coder_force_sync_interval
    if llm_coder_force_sync_timeout is not None:
        agent_params["llm_coder_force_sync_timeout"] = llm_coder_force_sync_timeout
    if llm_coder_force_sync_min_step is not None:
        agent_params["llm_coder_force_sync_min_step"] = llm_coder_force_sync_min_step
    agent_params["llm_coder_use_meta_advisor"] = bool(llm_coder_use_meta_advisor)
    agent_params["llm_coder_use_performance_trigger"] = bool(llm_coder_use_performance_trigger)
    agent_params["llm_coder_eval_use_subprocess_sandbox"] = bool(llm_coder_eval_use_subprocess_sandbox)
    if llm_coder_eval_subprocess_timeout is not None:
        agent_params["llm_coder_eval_subprocess_timeout"] = float(llm_coder_eval_subprocess_timeout)
    if llm_coder_state_profile_window_size is not None:
        agent_params["llm_coder_state_profile_window_size"] = int(llm_coder_state_profile_window_size)
    if llm_coder_agentic_max_iterations is not None:
        agent_params["llm_coder_agentic_max_iterations"] = llm_coder_agentic_max_iterations
    agent_params["llm_coder_use_repository"] = bool(llm_coder_use_repository)
    if llm_sched_n_samples is not None:
        agent_params["llm_sched_n_samples"] = llm_sched_n_samples
    if llm_sched_rollout_steps is not None:
        agent_params["llm_sched_rollout_steps"] = llm_sched_rollout_steps
    if llm_sched_info_level is not None:
        agent_params["llm_sched_info_level"] = llm_sched_info_level
    if llm_sched_mode is not None:
        agent_params["llm_sched_mode"] = llm_sched_mode
    if llm_sched_use_few_shot is not None:
        agent_params["llm_sched_use_few_shot"] = llm_sched_use_few_shot
    if llm_sched_max_examples is not None:
        agent_params["llm_sched_max_examples"] = llm_sched_max_examples
    if llm_sched_max_candidates is not None:
        agent_params["llm_sched_max_candidates"] = llm_sched_max_candidates
    if llm_sched_prompt_variant is not None:
        agent_params["llm_sched_prompt_variant"] = llm_sched_prompt_variant
    if llm_sched_refinement is not None:
        agent_params["llm_sched_refinement"] = llm_sched_refinement
    if llm_sched_reflection_rounds is not None:
        agent_params["llm_sched_reflection_rounds"] = llm_sched_reflection_rounds
    if llm_sched_voting_n is not None:
        agent_params["llm_sched_voting_n"] = llm_sched_voting_n
    if llm_sched_reflection_temperature is not None:
        agent_params["llm_sched_reflection_temperature"] = llm_sched_reflection_temperature
    if llm_sched_best_of_n_temperature is not None:
        agent_params["llm_sched_best_of_n_temperature"] = llm_sched_best_of_n_temperature

    if ga_population_size is not None:
        agent_params["ga_population_size"] = ga_population_size
    if ga_generations is not None:
        agent_params["ga_generations"] = ga_generations
    if ga_crossover_prob is not None:
        agent_params["ga_crossover_prob"] = ga_crossover_prob
    if ga_mutation_prob is not None:
        agent_params["ga_mutation_prob"] = ga_mutation_prob
    if ga_mutation_sigma is not None:
        agent_params["ga_mutation_sigma"] = ga_mutation_sigma
    if ga_rollout_steps is not None:
        agent_params["ga_rollout_steps"] = ga_rollout_steps
    if ga_random_seed is not None:
        agent_params["ga_random_seed"] = ga_random_seed

    if de_population_size is not None:
        agent_params["de_population_size"] = de_population_size
    if de_generations is not None:
        agent_params["de_generations"] = de_generations
    if de_mutation_scale is not None:
        agent_params["de_mutation_scale"] = de_mutation_scale
    if de_crossover_prob is not None:
        agent_params["de_crossover_prob"] = de_crossover_prob
    if de_rollout_steps is not None:
        agent_params["de_rollout_steps"] = de_rollout_steps
    if de_random_seed is not None:
        agent_params["de_random_seed"] = de_random_seed

    if pso_swarm_size is not None:
        agent_params["pso_swarm_size"] = pso_swarm_size
    if pso_iterations is not None:
        agent_params["pso_iterations"] = pso_iterations
    if pso_inertia is not None:
        agent_params["pso_inertia"] = pso_inertia
    if pso_cognitive_coeff is not None:
        agent_params["pso_cognitive_coeff"] = pso_cognitive_coeff
    if pso_social_coeff is not None:
        agent_params["pso_social_coeff"] = pso_social_coeff
    if pso_rollout_steps is not None:
        agent_params["pso_rollout_steps"] = pso_rollout_steps
    if pso_random_seed is not None:
        agent_params["pso_random_seed"] = pso_random_seed

    if cmaes_population_size is not None:
        agent_params["cmaes_population_size"] = cmaes_population_size
    if cmaes_generations is not None:
        agent_params["cmaes_generations"] = cmaes_generations
    if cmaes_sigma0 is not None:
        agent_params["cmaes_sigma0"] = cmaes_sigma0
    if cmaes_rollout_steps is not None:
        agent_params["cmaes_rollout_steps"] = cmaes_rollout_steps
    if cmaes_random_seed is not None:
        agent_params["cmaes_random_seed"] = cmaes_random_seed

    if sa_max_iterations is not None:
        agent_params["sa_max_iterations"] = sa_max_iterations
    if sa_initial_temperature is not None:
        agent_params["sa_initial_temperature"] = sa_initial_temperature
    if sa_cooling_rate is not None:
        agent_params["sa_cooling_rate"] = sa_cooling_rate
    if sa_rollout_steps is not None:
        agent_params["sa_rollout_steps"] = sa_rollout_steps
    if sa_random_seed is not None:
        agent_params["sa_random_seed"] = sa_random_seed

    if ts_max_iterations is not None:
        agent_params["ts_max_iterations"] = ts_max_iterations
    if ts_tabu_tenure is not None:
        agent_params["ts_tabu_tenure"] = ts_tabu_tenure
    if ts_rollout_steps is not None:
        agent_params["ts_rollout_steps"] = ts_rollout_steps
    if ts_random_seed is not None:
        agent_params["ts_random_seed"] = ts_random_seed

    if moea_population_size is not None:
        agent_params["moea_population_size"] = moea_population_size
    if moea_generations is not None:
        agent_params["moea_generations"] = moea_generations
    if moea_mutation_prob is not None:
        agent_params["moea_mutation_prob"] = moea_mutation_prob
    if moea_rollout_steps is not None:
        agent_params["moea_rollout_steps"] = moea_rollout_steps
    if moea_random_seed is not None:
        agent_params["moea_random_seed"] = moea_random_seed

    if nsga2_population_size is not None:
        agent_params["nsga2_population_size"] = nsga2_population_size
    if nsga2_generations is not None:
        agent_params["nsga2_generations"] = nsga2_generations
    if nsga2_mutation_prob is not None:
        agent_params["nsga2_mutation_prob"] = nsga2_mutation_prob
    if nsga2_rollout_steps is not None:
        agent_params["nsga2_rollout_steps"] = nsga2_rollout_steps
    if nsga2_random_seed is not None:
        agent_params["nsga2_random_seed"] = nsga2_random_seed

    ag = _build_agent(agent, agent_params)

    emergency_jobs = set()
    # Threshold for treating a priority change as "emergency"; lower number = higher priority.
    emergency_threshold = getattr(getattr(model, "dynamic_scenarios", None), "emergency_priority", -1)
    from_priority = set()
    for ev in events:
        if isinstance(ev, PriorityChangeEvent):
            new_p = getattr(ev, "new_priority", 0)
            if new_p <= emergency_threshold:
                jid = str(ev.job_id)
                emergency_jobs.add(jid)
                from_priority.add(jid)

    static_jobs_path = instance_dir / "static_jobs.json"
    from_static = set()
    if static_jobs_path.exists():
        try:
            raw = static_jobs_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            jobs_info = data.get("jobs", {}) or {}
            for jid, info in jobs_info.items():
                atype = info.get("arrival_type")
                if atype in ("emergency", "dynamic"):
                    jid_str = str(jid)
                    emergency_jobs.add(jid_str)
                    from_static.add(jid_str)
        except Exception as exc:
            logger.warning(f"Failed to read static_jobs.json for emergency jobs: {exc}")

    logger.info(
        "Detected emergency jobs: total={} from_priority={} from_static={} threshold={}",
        len(emergency_jobs),
        len(from_priority),
        len(from_static),
        emergency_threshold,
    )
    if emergency_jobs:
        logger.debug(
            "Emergency job ids (sorted, up to 20): {}",
            sorted(emergency_jobs)[:20],
        )

    scenario_info: Dict[str, Any] = {"events_path": str(events_file)}
    if emergency_jobs:
        scenario_info["emergency_jobs"] = sorted(emergency_jobs)
    try:
        env._static_emergency_jobs = set(emergency_jobs)
    except Exception:
        pass

    obs = env.reset()
    ag.reset(scenario_info)

    if agent_stats_offset is not None:
        try:
            offset_path = Path(agent_stats_offset)
            if offset_path.is_file():
                raw_offset = offset_path.read_text(encoding="utf-8")
                data = json.loads(raw_offset)
                offset_stats = data.get("stats") or {}
                if isinstance(offset_stats, dict) and offset_stats:
                    policy = getattr(ag, "policy", None)
                    stats_dict = getattr(policy, "stats", None)
                    if isinstance(stats_dict, dict):
                        for k, v in offset_stats.items():
                            try:
                                prev_val = float(stats_dict.get(k, 0.0))
                                inc_val = float(v)
                            except Exception:
                                continue
                            stats_dict[k] = prev_val + inc_val
        except Exception:
            logger.exception(
                "A.run: failed to apply agent_stats_offset from {}", agent_stats_offset
            )

    steps = 0
    if resume_from_trajectory is not None:
        try:
            replay_path = Path(resume_from_trajectory)
            if replay_path.is_file():
                steps_replayed, obs = _replay_trajectory_from_jsonl(env, replay_path, obs)
                steps = steps_replayed
                logger.info(
                    "A.run: resume_from_trajectory enabled; replayed {} steps from {}",
                    steps_replayed,
                    replay_path,
                )
            else:
                logger.warning(
                    "A.run: resume_from_trajectory path does not exist or is not a file: {}",
                    replay_path,
                )
        except Exception:
            logger.exception(
                "A.run: failed to replay trajectory from {}", resume_from_trajectory
            )

    done = env.done()

    log_interval = 200
    start_time_wall = time.perf_counter()
    while (not done) and steps < max_steps:
        if steps % log_interval == 0:
            try:
                t = float(obs.get("time", 0.0)) if isinstance(obs, dict) else 0.0
                dyn = obs.get("dynamic_summary", {}) if isinstance(obs, dict) else {}
                prog = dyn.get("progress", {}) if isinstance(dyn, dict) else {}
                num_arrived = prog.get("num_jobs_arrived")
                num_completed = prog.get("num_jobs_completed")
                traj_steps = getattr(env, "_traj_step_count", None)
                rss_mb = None
                try:
                    ru = resource.getrusage(resource.RUSAGE_SELF)
                    rss_mb = float(ru.ru_maxrss) / 1024.0
                except Exception:
                    rss_mb = None
                logger.info(
                    "A.run: progress steps={} traj_steps={} time={:.3f} arrived={} completed={} rss_mb={}",
                    steps,
                    traj_steps,
                    t,
                    num_arrived,
                    num_completed,
                    rss_mb,
                )
            except Exception:
                logger.exception("A.run: failed to get snapshot for progress logging")

        legal = env.legal_actions()
        if not legal:
            obs = env.advance_if_idle()
            done = env.done()
            continue

        act = ag.act(obs, legal, env)
        if act is None:
            obs = env.advance_if_idle()
            steps += 1
            done = env.done()
            continue

        obs, reward, done, info = env.step(act)
        steps += 1

    logger.info("A.run: simulation loop finished at steps={}", steps)
    end_time_wall = time.perf_counter()
    runtime_seconds = float(end_time_wall - start_time_wall)

    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        finalize_episode = getattr(ag, "finalize_episode", None)
        if callable(finalize_episode):
            finalize_episode(env, obs)
    except Exception:
        logger.exception("A.run: failed to call agent.finalize_episode")

    traj = env.get_trajectory()
    traj_path = out_dir / "trajectory.json"
    has_stream_backing = getattr(traj, "_file_path", None) is not None

    logger.info(
        "A.run: obtained trajectory (stream_backing={}, file_path={})",
        has_stream_backing,
        getattr(traj, "_file_path", None),
    )

    if save_trajectory and (not has_stream_backing):
        traj_json = traj.model_dump_json(indent=2, ensure_ascii=False)
        traj_path.write_text(traj_json, encoding="utf-8")

    logger.info("A.run: starting metrics evaluation")
    metrics = evaluate_trajectory(traj)
    logger.info("A.run: finished metrics evaluation")

    try:
        if isinstance(metrics, dict):
            metrics["runtime_seconds"] = float(runtime_seconds)
    except Exception:
        pass

    agent_stats: Dict[str, Any] = {}
    try:
        get_stats = getattr(ag, "get_stats", None)
        if callable(get_stats):
            stats_val = get_stats()
            if isinstance(stats_val, dict):
                agent_stats = stats_val
    except Exception:
        agent_stats = {}

    if agent_stats:
        try:
            if isinstance(metrics, dict):
                metrics["agent_stats"] = agent_stats
        except Exception:
            pass

    try:
        if isinstance(metrics, dict) and isinstance(agent_stats, dict):
            usage = agent_stats.get("llm_usage")
            if isinstance(usage, dict):
                ti = usage.get("total_input_tokens")
                to = usage.get("total_output_tokens")
                try:
                    if ti is not None:
                        metrics["llm_total_input_tokens"] = int(ti)
                except Exception:
                    pass
                try:
                    if to is not None:
                        metrics["llm_total_output_tokens"] = int(to)
                except Exception:
                    pass
    except Exception:
        pass

    if agent in ("llm-coder", "llm_coder", "llmcoder"):
        try:
            from dsbx.Agents.LLMScheduler.logger import TrajectoryLogger

            worker = agent_stats.get("worker") if isinstance(agent_stats, dict) else None
            traj_events = []
            if isinstance(worker, dict):
                val = worker.get("trajectory")
                if isinstance(val, list):
                    traj_events = [x for x in val if isinstance(x, dict)]

            force_sync_events = []
            if isinstance(agent_stats, dict):
                val_fs = agent_stats.get("force_sync_trajectory")
                if isinstance(val_fs, list):
                    force_sync_events = [x for x in val_fs if isinstance(x, dict)]

            all_events = []
            if traj_events:
                all_events.extend(traj_events)
            if force_sync_events:
                all_events.extend(force_sync_events)

            if all_events:
                logger_obj = TrajectoryLogger()
                for rec in all_events:
                    logger_obj.append(rec)

                llmcoder_traj_path = out_dir / "llmcoder_trajectory.jsonl"
                logger_obj.dump_jsonl(llmcoder_traj_path)
                logger.info(
                    "A.run: wrote LLMCoder internal trajectory JSONL to {} (events={})",
                    llmcoder_traj_path,
                    len(all_events),
                )
        except Exception as exc:
            logger.error("A.run: failed to dump LLMCoder trajectory JSONL: {}", exc)

    try:
        save_model = getattr(ag, "save_model", None)
        if callable(save_model):
            save_model()
    except Exception:
        logger.exception("A.run: failed to call agent.save_model")

    metrics_path = out_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("A.run: building gantt from last snapshot")
    last_snap = traj.last_snapshot
    gantt = _build_gantt_from_snapshot(last_snap)
    gantt_path = out_dir / "gantt.json"
    gantt_path.write_text(json.dumps(gantt, indent=2, ensure_ascii=False), encoding="utf-8")

    env.close()
    if save_trajectory and (not has_stream_backing):
        logger.info(f"Trajectory written to {traj_path}")
    logger.info(f"Metrics written to {metrics_path}")
    logger.info(f"Gantt written to {gantt_path}")

    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":  # pragma: no cover
    app()
