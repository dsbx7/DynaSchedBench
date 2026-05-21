import json
from pathlib import Path
import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError
from loguru import logger
import numpy as np
import random as _py_random
from ..models.inputs import InputModel
from .config_migrator import ConfigMigrator

def load_input_model(path) -> InputModel:
    """Load and validate an input file in JSON or YAML format.

    If required fields are missing, sensible defaults are filled and the model is
    validated again. The loader also migrates v1.0 configuration files to the
    v2.0 schema automatically.
    """
    try:
        if isinstance(path, str):
            path = Path(path)
        
        if path.suffix in [".yaml", ".yml"]:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
        else:
            with open(path, "r") as f:
                data = json.load(f)
        
        data = ConfigMigrator.migrate_if_needed(data)

        def _autofill_missing(d: dict) -> dict:
            d = dict(d or {})
            meta = d.get("meta") or {}
            # Seed: if not provided, randomize once and store for reproducibility
            if "seed" not in meta:
                sysrand = _py_random.SystemRandom()
                meta["seed"] = int(sysrand.randrange(1, 2**31 - 1))
                logger.warning(f"Input missing meta.seed. Auto-generated random seed={meta['seed']} for reproducibility.")
            seed = int(meta.get("seed"))
            rng = np.random.default_rng(seed)

            # Optionally randomize horizon if not provided (v2.0: horizon in scale)
            scale = d.get("scale") or {}
            if "horizon" not in scale:
                # Choose a moderate horizon to keep sizes reasonable
                scale["horizon"] = float(rng.uniform(200.0, 2000.0))
                logger.warning(f"Input missing scale.horizon. Auto-generated random horizon≈{scale['horizon']:.1f}.")
            d["scale"] = scale

            # Ensure a plant exists; randomize if missing
            plant = d.get("plant") or {}
            machines = plant.get("machines") or []
            templates = plant.get("process_templates") or []

            # If machines missing, create random groups and machines per group
            if not machines:
                n_groups = int(rng.integers(1, 4))  # 1 to 3 groups
                group_names = [f"G{i+1}" for i in range(n_groups)]
                machines = []
                mid = 1
                for g in group_names:
                    n_m = int(rng.integers(1, 4))  # 1 to 3 machines per group
                    for _ in range(n_m):
                        machines.append({"id": f"M{mid}", "group": g})
                        mid += 1
                logger.warning(f"Input missing plant.machines. Auto-generated random machines across groups {group_names}.")

            # If templates missing, synthesize random routes based on available groups
            if not templates:
                groups = sorted({m.get("group", "G1") for m in machines})
                if not groups:
                    groups = ["G1"]
                n_tpl = int(rng.integers(1, 4))  # 1 to 3 templates
                templates = []
                for t_idx in range(n_tpl):
                    family = f"F{t_idx+1}"
                    steps = int(rng.integers(1, 6))  # 1 to 5 steps
                    route = []
                    for _ in range(steps):
                        g = rng.choice(np.array(groups))
                        mean = float(rng.uniform(3.0, 20.0))
                        # Small chance of variability at template level, but ProcessTime.scv isn’t used in constructor
                        route.append({
                            "machine_group": str(g),
                            "process_time": {"mean": round(mean, 3)}
                        })
                    templates.append({"family": family, "route": route})
                logger.warning("Input missing plant.process_templates. Auto-generated random templates and routes.")

            d["plant"] = {"machines": machines, "process_templates": templates}
            d.setdefault("scale", {})
            d.setdefault("dynamics", {})
            d.setdefault("targets", {})
            d.setdefault("dynamic_scenarios", {})
            d.setdefault("evaluation", {})
            d.setdefault("tolerance", {})
            d.setdefault("outputs", {})
            d["meta"] = meta

            # Randomize missing target fields
            tgt = d["targets"]
            if "rho_global" not in tgt:
                tgt["rho_global"] = float(rng.uniform(0.5, 0.95))
                logger.warning(f"Input missing targets.rho_global. Auto-generated random value≈{tgt['rho_global']:.3f}.")
            if "ddt" not in tgt:
                tgt["ddt"] = float(rng.uniform(0.8, 1.6))
                logger.warning(f"Input missing targets.ddt. Auto-generated random value≈{tgt['ddt']:.3f}.")
            if "scv_a" not in tgt:
                tgt["scv_a"] = float(rng.uniform(0.0, 1.0))
                logger.warning(f"Input missing targets.scv_a. Auto-generated random value≈{tgt['scv_a']:.3f}.")
            if "scv_p" not in tgt:
                tgt["scv_p"] = float(rng.uniform(0.0, 1.0))
                logger.warning(f"Input missing targets.scv_p. Auto-generated random value≈{tgt['scv_p']:.3f}.")
            if "disturbance" not in tgt:
                tgt["disturbance"] = float(rng.uniform(0.0, 0.25))
                logger.warning(f"Input missing targets.disturbance. Auto-generated random value≈{tgt['disturbance']:.3f}.")

            # Randomize scale.jobs_total if missing
            sc = d["scale"]
            if "jobs_total" not in sc or sc.get("jobs_total") is None:
                sc["jobs_total"] = int(rng.integers(50, 300))
                logger.warning(f"Input missing scale.jobs_total. Auto-generated random value={sc['jobs_total']}.")

            # Randomize dynamic_scenarios missing fields
            dyn = d["dynamic_scenarios"]
            if "cancellation_rate" not in dyn:
                dyn["cancellation_rate"] = float(rng.uniform(0.0, 0.1))
            if "priority_change_rate" not in dyn:
                dyn["priority_change_rate"] = float(rng.uniform(0.0, 0.15))
            if "rework_probability" not in dyn:
                dyn["rework_probability"] = float(rng.uniform(0.0, 0.05))
            if "ptime_change_rate" not in dyn:
                dyn["ptime_change_rate"] = float(rng.uniform(0.0, 0.2))
            if "ptime_change_multiplier" not in dyn:
                # mix of <1 and >1 multipliers
                k = int(rng.integers(2, 6))  # 2..5 multipliers
                lows = list(rng.uniform(0.7, 1.0, size=max(1, k//2)))
                highs = list(rng.uniform(1.0, 1.5, size=k - len(lows)))
                dyn["ptime_change_multiplier"] = [round(float(x), 2) for x in lows + highs]

            return d

        try:
            return InputModel.model_validate(data)
        except ValidationError:
            # Attempt to auto-fill and validate again
            data2 = _autofill_missing(data)
            return InputModel.model_validate(data2)
    except ValidationError as e:
        raise ValueError(f"Input validation failed:\n{e}") from e
    except FileNotFoundError:
        raise FileNotFoundError(f"Input file not found at: {path}") from None
