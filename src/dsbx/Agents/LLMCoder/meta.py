from __future__ import annotations

from typing import Any, Dict

from loguru import logger

from .config import LLMCoderConfig


class MetaConfigAdvisor:
    def __init__(self) -> None:
        pass

    def tune_inplace(self, model_summary: Dict[str, Any], cfg: LLMCoderConfig) -> None:
        try:
            if getattr(cfg, "debug_always_accept", False):
                return
        except Exception:
            pass
        try:
            summary = dict(model_summary) if isinstance(model_summary, dict) else {}
        except Exception:
            summary = {}
        num_jobs = int(float(summary.get("num_jobs", 0.0) or 0.0))
        num_machines = int(float(summary.get("num_machines", 0.0) or 0.0))
        horizon = float(summary.get("horizon", 0.0) or 0.0)
        scale = max(num_jobs * max(num_machines, 1), 1)
        cfg_changed: Dict[str, Any] = {}
        if scale <= 100:
            target_min_ep = 3
            target_max_ep = 8
            target_n = 4
        elif scale <= 400:
            target_min_ep = 5
            target_max_ep = 12
            target_n = 6
        else:
            target_min_ep = 8
            target_max_ep = 20
            target_n = 8
        if cfg.eval_min_episodes != target_min_ep:
            cfg.eval_min_episodes = target_min_ep
            cfg_changed["eval_min_episodes"] = target_min_ep
        if cfg.eval_max_episodes != target_max_ep:
            cfg.eval_max_episodes = target_max_ep
            cfg_changed["eval_max_episodes"] = target_max_ep
        if cfg.n_candidates != target_n:
            cfg.n_candidates = target_n
            cfg_changed["n_candidates"] = target_n
        if horizon > 0.0:
            target_steps = int(max(cfg.eval_max_steps, min(horizon, horizon * 1.5)))
            if cfg.eval_max_steps != target_steps:
                cfg.eval_max_steps = target_steps
                cfg_changed["eval_max_steps"] = target_steps
        if scale >= 400:
            target_cw = max(cfg.complexity_weight, 0.2)
            if cfg.complexity_weight != target_cw:
                cfg.complexity_weight = target_cw
                cfg_changed["complexity_weight"] = target_cw
            target_effect = max(cfg.eval_min_effect_size, 0.2)
            if cfg.eval_min_effect_size != target_effect:
                cfg.eval_min_effect_size = target_effect
                cfg_changed["eval_min_effect_size"] = target_effect
        config_path = summary.get("config_path")
        if isinstance(config_path, str):
            lower = config_path.lower()
            if "cold_start" in lower and "warm" not in lower:
                if cfg.llm_temperature != 0.2:
                    cfg.llm_temperature = 0.2
                    cfg_changed["llm_temperature"] = 0.2
            if "warm_start" in lower:
                if cfg.llm_temperature != 0.0:
                    cfg.llm_temperature = 0.0
                    cfg_changed["llm_temperature"] = 0.0
            if "preventive_maintenance" in lower or "pm_" in lower:
                target_alpha = min(cfg.eval_significance_level, 0.05)
                if cfg.eval_significance_level != target_alpha:
                    cfg.eval_significance_level = target_alpha
                    cfg_changed["eval_significance_level"] = target_alpha
        if cfg_changed:
            try:
                run_name = summary.get("run_name")
            except Exception:
                run_name = None
            logger.info(
                "MetaConfigAdvisor: tuned LLMCoderConfig for scenario run_name={} with changes={}",
                run_name,
                cfg_changed,
            )
