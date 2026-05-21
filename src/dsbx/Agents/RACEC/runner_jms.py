from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from loguru import logger

from dsbx.Agents.LLMScheduler.config import ModelConfig
from dsbx.Logging import init_logging

from .config import LLMCoderConfig
from .runner import solve_jms_instance


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run LLMCoder on a JMS/GEN-Bench JSONL instance using JMSSim backend. "
            "This is a thin CLI wrapper around solve_jms_instance, intended "
            "for batch scripts over data/jmsbench and data/genbench."
        )
    )

    parser.add_argument(
        "--instance-file",
        type=str,
        required=True,
        help="Path to a JMSBench/GEN-Bench style JSONL instance (static_info + dynamic_events).",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output directory; metrics.json, gantt.json, and llmcoder_trajectory.jsonl will be written here.",
    )
    parser.add_argument(
        "--agent",
        type=str,
        default="llm-coder",
        help="Agent name (currently only 'llm-coder' is supported).",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=0,
        help=(
            "Optional safety bound on decision steps (currently ignored; "
            "DynaSchedEnv.total_operations is used to derive a bound)."
        ),
    )

    # LLM connection parameters (mirrors A.run subset).
    parser.add_argument("--llm-provider", type=str, default=None, help="LLM HTTP provider (e.g. chatanywhere, openai).")
    parser.add_argument("--llm-model", type=str, default=None, help="Override LLM model name.")
    parser.add_argument("--llm-base-url", type=str, default=None, help="Override LLM HTTP base URL.")
    parser.add_argument("--llm-temperature", type=float, default=None, help="Sampling temperature for LLM calls.")
    parser.add_argument("--llm-timeout", type=float, default=None, help="Timeout seconds for LLM HTTP requests.")

    # LLMCoder-specific options (subset used by the bash scripts).
    parser.add_argument("--llm-coder-eval-max-steps", type=int, default=None)
    parser.add_argument("--llm-coder-max-steps-between-updates", type=int, default=None)
    parser.add_argument("--llm-coder-min-relative-improvement", type=float, default=None)

    parser.add_argument("--llm-coder-force-sync-interval", type=int, default=0)
    parser.add_argument("--llm-coder-force-sync-timeout", type=float, default=600.0)
    parser.add_argument("--llm-coder-force-sync-min-step", type=int, default=0)

    parser.add_argument("--llm-coder-eval-pool-size", type=int, default=None)
    parser.add_argument("--llm-coder-eval-pool-refresh-per-eval", type=int, default=None)

    parser.add_argument("--llm-coder-eval-min-episodes", type=int, default=None)
    parser.add_argument("--llm-coder-eval-max-episodes", type=int, default=None)
    parser.add_argument("--llm-coder-eval-significance-level", type=float, default=None)

    parser.add_argument(
        "--llm-coder-eval-fail-fast",
        dest="llm_coder_eval_fail_fast",
        action="store_true",
        default=False,
        help="Enable fail-fast early reject when rel_improvement<=0 after eval_min_episodes.",
    )

    parser.add_argument("--llm-coder-agentic-max-iterations", type=int, default=None)

    parser.add_argument(
        "--llm-coder-use-repository",
        dest="llm_coder_use_repository",
        action="store_true",
        default=True,
        help="Enable the rule repository (warm-start and persistence).",
    )
    parser.add_argument(
        "--no-llm-coder-use-repository",
        dest="llm_coder_use_repository",
        action="store_false",
        help="Disable the rule repository (cold start, no persistence).",
    )
    parser.add_argument(
        "--llm-coder-use-meta-advisor",
        dest="llm_coder_use_meta_advisor",
        action="store_true",
        default=True,
        help="Enable MetaConfigAdvisor for automatic eval parameter tuning.",
    )
    parser.add_argument(
        "--no-llm-coder-use-meta-advisor",
        dest="llm_coder_use_meta_advisor",
        action="store_false",
        help="Disable MetaConfigAdvisor and use raw LLMCoderConfig settings.",
    )
    parser.add_argument(
        "--no-llm-coder-use-performance-trigger",
        dest="llm_coder_use_performance_trigger",
        action="store_false",
        default=True,
        help="Disable performance-based trigger gating for codegen.",
    )

    return parser.parse_args()


def _build_llmcoder_config(args: argparse.Namespace) -> LLMCoderConfig:
    cfg = LLMCoderConfig()

    # LLM sampling params.
    if args.llm_temperature is not None:
        try:
            cfg.llm_temperature = float(args.llm_temperature)
        except Exception:
            logger.warning("Invalid llm_temperature override: {}", args.llm_temperature)

    # Evaluation & update schedule.
    if args.llm_coder_eval_max_steps is not None:
        try:
            cfg.eval_max_steps = int(args.llm_coder_eval_max_steps)
        except Exception:
            logger.warning("Invalid eval_max_steps override: {}", args.llm_coder_eval_max_steps)
    if args.llm_coder_max_steps_between_updates is not None:
        try:
            cfg.max_steps_between_updates = int(args.llm_coder_max_steps_between_updates)
        except Exception:
            logger.warning("Invalid max_steps_between_updates override: {}", args.llm_coder_max_steps_between_updates)
    if args.llm_coder_min_relative_improvement is not None:
        try:
            cfg.min_relative_improvement = float(args.llm_coder_min_relative_improvement)
        except Exception:
            logger.warning("Invalid min_relative_improvement override: {}", args.llm_coder_min_relative_improvement)

    if args.llm_coder_eval_pool_size is not None:
        try:
            cfg.eval_pool_size = int(args.llm_coder_eval_pool_size)
        except Exception:
            logger.warning("Invalid eval_pool_size override: {}", args.llm_coder_eval_pool_size)
    if args.llm_coder_eval_pool_refresh_per_eval is not None:
        try:
            cfg.eval_pool_refresh_per_eval = int(args.llm_coder_eval_pool_refresh_per_eval)
        except Exception:
            logger.warning("Invalid eval_pool_refresh_per_eval override: {}", args.llm_coder_eval_pool_refresh_per_eval)

    if args.llm_coder_eval_min_episodes is not None:
        try:
            cfg.eval_min_episodes = int(args.llm_coder_eval_min_episodes)
        except Exception:
            logger.warning("Invalid eval_min_episodes override: {}", args.llm_coder_eval_min_episodes)
    if args.llm_coder_eval_max_episodes is not None:
        try:
            cfg.eval_max_episodes = int(args.llm_coder_eval_max_episodes)
        except Exception:
            logger.warning("Invalid eval_max_episodes override: {}", args.llm_coder_eval_max_episodes)
    if args.llm_coder_eval_significance_level is not None:
        try:
            cfg.eval_significance_level = float(args.llm_coder_eval_significance_level)
        except Exception:
            logger.warning("Invalid eval_significance_level override: {}", args.llm_coder_eval_significance_level)

    if args.llm_coder_agentic_max_iterations is not None:
        try:
            cfg.agentic_max_iterations = int(args.llm_coder_agentic_max_iterations)
        except Exception:
            logger.warning("Invalid agentic_max_iterations override: {}", args.llm_coder_agentic_max_iterations)

    # Boolean switches.
    cfg.eval_fail_fast = bool(args.llm_coder_eval_fail_fast)
    cfg.use_repository = bool(args.llm_coder_use_repository)
    cfg.use_meta_advisor = bool(args.llm_coder_use_meta_advisor)
    cfg.use_performance_trigger = bool(args.llm_coder_use_performance_trigger)

    # Force-sync parameters.
    try:
        cfg.force_sync_codegen_interval = int(args.llm_coder_force_sync_interval)
    except Exception:
        logger.warning("Invalid force_sync_codegen_interval override: {}", args.llm_coder_force_sync_interval)
    try:
        cfg.force_sync_codegen_timeout = float(args.llm_coder_force_sync_timeout)
    except Exception:
        logger.warning("Invalid force_sync_codegen_timeout override: {}", args.llm_coder_force_sync_timeout)
    try:
        cfg.force_sync_codegen_min_step = int(args.llm_coder_force_sync_min_step)
    except Exception:
        logger.warning("Invalid force_sync_codegen_min_step override: {}", args.llm_coder_force_sync_min_step)

    return cfg


def _build_model_config(args: argparse.Namespace) -> ModelConfig:
    provider = args.llm_provider or "none"
    model_name = args.llm_model
    base_url = args.llm_base_url
    timeout = float(args.llm_timeout) if args.llm_timeout is not None else 30.0
    return ModelConfig(provider=provider, model_name=model_name, base_url=base_url, request_timeout=timeout)


def main() -> None:
    args = _parse_args()

    agent_key = str(args.agent).lower().replace("_", "-")
    if agent_key not in {"llm-coder", "llmcoder"}:
        logger.warning(
            "runner_jms: only 'llm-coder' is supported for now; got agent='{}' (proceeding anyway)",
            args.agent,
        )

    instance_path = Path(args.instance_file)
    if not instance_path.is_file():
        raise SystemExit(f"JMS/GEN-Bench JSONL instance not found: {instance_path}")

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Initialize logging so that this script behaves like the Agents CLI:
    # logs/A/run_jms/<timestamp>_A_run_jms[_runid]/{main.log,sandbox_eval.log}
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

    cfg = _build_llmcoder_config(args)
    model_cfg = _build_model_config(args)

    metrics_path = out_dir / "metrics.json"
    traj_log_path = out_dir / "llmcoder_trajectory.jsonl"

    result = solve_jms_instance(
        instance_path=instance_path,
        cfg=cfg,
        output_path=metrics_path,
        trajectory_path=traj_log_path,
        model_cfg=model_cfg,
    )

    # Also write gantt.json alongside metrics.json for convenience.
    try:
        gantt = result.get("gantt", []) if isinstance(result, dict) else []
        gantt_path = out_dir / "gantt.json"
        gantt_path.write_text(json.dumps(gantt, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.exception("runner_jms: failed to write gantt.json")

    # Print metrics to stdout for quick inspection / logging pipelines.
    try:
        metrics: Any = result.get("metrics", result)
        print(json.dumps(metrics, indent=2, ensure_ascii=False))
    except Exception:
        try:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except Exception:
            logger.exception("runner_jms: failed to print result as JSON")


if __name__ == "__main__":  # pragma: no cover
    main()
