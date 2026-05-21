from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any, Iterator, List

import json

import typer
from typing_extensions import Annotated
from loguru import logger
import pandas as pd
import numpy as np

from dsbx import __version__
from dsbx.Gen import InputModel, load_input_model, run_generation_pipeline
from dsbx.Gen.pipeline import _expand_batch_parameters
from dsbx.Logging import init_logging
from dsbx.Gen.io.visualization import plot_instance_space
from dsbx.Gen.core.moo_calibrator_v3 import ExtendedCalibrationProblem
from dsbx.Gen.core.hybrid_calibrator import CoupledMetricsProblem
from dsbx.Gen.core.seed import SeedManager
from dsbx.Gen.core.constructor import FastPathConstructor
from dsbx.Gen.core.metrics_engine import MetricsEngine
from dsbx.Gen.core.feasibility import FeasibilityProjector
from dsbx.Gen.io.export import Exporter
from dsbx.Gen.models.metrics import FinalReportData


app = typer.Typer(
    name="dsbx-gen",
    help="Generate and inspect DynaSchedBench dynamic scheduling instances.",
    add_completion=False,
)


@app.command()
def gen(
    input_file: Annotated[Path, typer.Option("-i", "--input", help="Path to the input JSON file.")],
    output_dir: Annotated[Path, typer.Option("-o", "--output", help="Directory to save the generated instance.")]
    = Path("runs/tmp_cli"),
    max_calib_steps: Annotated[
        Optional[int],
        typer.Option(
            help=(
                "Maximum calibration steps (for sequential mode). "
                "If omitted, uses the default DynaSchedBench setting (25)."
            ),
        ),
    ] = None,
    tol_rho: Annotated[
        Optional[float],
        typer.Option(
            "--tol-rho",
            help=(
                "Sequential mode: per-metric tolerance for rho_global relative "
                "error. If not set, uses min(0.06, base_tol * 0.6)."
            ),
        ),
    ] = None,
    tol_scv_a: Annotated[
        Optional[float],
        typer.Option(
            "--tol-scv-a",
            help=(
                "Sequential mode: per-metric tolerance for scv_a relative "
                "error. If not set, uses min(0.12, base_tol * 1.2)."
            ),
        ),
    ] = None,
    tol_scv_p: Annotated[
        Optional[float],
        typer.Option(
            "--tol-scv-p",
            help=(
                "Sequential mode: per-metric tolerance for scv_p relative "
                "error. If not set, uses min(0.18, base_tol * 1.8) when scv_p>=1.5 "
                "else min(0.12, base_tol * 1.2)."
            ),
        ),
    ] = None,
    tol_ddt: Annotated[
        Optional[float],
        typer.Option(
            "--tol-ddt",
            help=(
                "Sequential mode: per-metric tolerance for ddt relative "
                "error. If not set, uses min(0.10, base_tol * 1.0)."
            ),
        ),
    ] = None,
    tol_disturbance: Annotated[
        Optional[float],
        typer.Option(
            "--tol-disturbance",
            help=(
                "Sequential mode: per-metric tolerance for disturbance "
                "relative error. If not set, uses min(0.10, base_tol * 1.0)."
            ),
        ),
    ] = None,
    tol_load_cv: Annotated[
        Optional[float],
        typer.Option(
            "--tol-load-cv",
            help=(
                "Sequential mode: per-metric tolerance for load_cv relative "
                "error. If not set, uses min(0.15, base_tol * 1.5)."
            ),
        ),
    ] = None,
    compare_to: Annotated[
        Optional[List[Path]],
        typer.Option(
            "--compare-to",
            help="Two final_metrics.json files to compare: BASELINE then CANDIDATE.",
            exists=True,
        ),
    ] = None,
    use_moo: Annotated[
        bool,
        typer.Option(
            "--use-moo",
            help="Use Multi-Objective Optimization (NSGA-II) v3 for calibration.",
        ),
    ] = False,
    use_hybrid: Annotated[
        bool,
        typer.Option(
            "--use-hybrid",
            help="Use Hybrid calibration (Sequential + MOO for coupled metrics).",
        ),
    ] = False,
    moo_population_size: Annotated[
        Optional[int],
        typer.Option(
            "--moo-pop-size",
            help=(
                "Population size for MOO calibrator (default: 60). "
                "Only effective when --use-moo is set."
            ),
        ),
    ] = None,
    moo_n_generations: Annotated[
        Optional[int],
        typer.Option(
            "--moo-max-gens",
            help=(
                "Maximum generations for MOO calibrator (default: 40). "
                "Only effective when --use-moo is set."
            ),
        ),
    ] = None,
    hybrid_population_size: Annotated[
        Optional[int],
        typer.Option(
            "--hybrid-pop-size",
            help=(
                "Population size for Hybrid calibrator (default: 80). "
                "Only effective when --use-hybrid is set."
            ),
        ),
    ] = None,
    hybrid_n_generations: Annotated[
        Optional[int],
        typer.Option(
            "--hybrid-max-gens",
            help=(
                "Maximum generations for Hybrid calibrator (default: 100). "
                "Only effective when --use-hybrid is set."
            ),
        ),
    ] = None,
    hybrid_convergence_window: Annotated[
        Optional[int],
        typer.Option(
            "--hybrid-conv-window",
            help=(
                "Convergence window (in generations) for Hybrid termination "
                "(default: 10). Only effective when --use-hybrid is set."
            ),
        ),
    ] = None,
    hybrid_convergence_tol: Annotated[
        Optional[float],
        typer.Option(
            "--hybrid-conv-tol",
            help=(
                "Convergence tolerance for Hybrid termination as relative "
                "improvement (default: 0.0005, i.e. 0.05%). Only effective "
                "when --use-hybrid is set."
            ),
        ),
    ] = None,
    hybrid_max_sequential_steps: Annotated[
        Optional[int],
        typer.Option(
            "--hybrid-max-seq-steps",
            help=(
                "Maximum sequential refinement steps inside Hybrid calibrator "
                "(default: 7). Only effective when --use-hybrid is set."
            ),
        ),
    ] = None,
    seq_early_stop_no_improve_steps: Annotated[
        Optional[int],
        typer.Option(
            "--seq-early-stop-no-improve",
            help=(
                "Sequential mode: number of consecutive steps with insufficient "
                "L2 improvement to trigger early stopping (default: 3)."
            ),
        ),
    ] = None,
    seq_early_stop_relax_factor: Annotated[
        Optional[float],
        typer.Option(
            "--seq-early-stop-relax-factor",
            help=(
                "Sequential mode: relaxation factor for per-metric thresholds "
                "when deciding early stop (default: 2.0, i.e. allow up to 2x "
                "the strict threshold)."
            ),
        ),
    ] = None,
    seq_min_relative_improvement: Annotated[
        Optional[float],
        typer.Option(
            "--seq-min-rel-improve",
            help=(
                "Sequential mode: minimal relative L2 improvement between "
                "steps to be considered as 'improvement' (default: 0.005, i.e. "
                "0.5%). Smaller values ​​make early stopping more difficult to trigger, while larger values ​​are more aggressive."
            ),
        ),
    ] = None,
    auto: Annotated[
        bool,
        typer.Option(
            "--auto",
            help=(
                "Auto mode: automatically select calibration mode and steps "
                "with DynaSchedBench CalibrationAdvisor."
            ),
        ),
    ] = False,
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            help="Logging level: DEBUG, INFO, WARNING, ERROR.",
        ),
    ] = "INFO",
) -> None:
    """Generate a single dynamic scheduling instance.

    Generate a DynaSchedBench instance from an input configuration.
    """

    init_logging(component="G", command="gen", log_level=log_level, run_id=input_file.stem)

    try:
        model: InputModel = load_input_model(input_file)
    except (ValueError, FileNotFoundError) as e:  # pragma: no cover - CLI error path
        msg = f"Error loading input file: {e}"
        logger.error(msg)
        print(msg)
        raise typer.Exit(code=3)

    try:
        default_out = Path("runs") / "tmp_cli"
        if output_dir == default_out:
            cfg_out = getattr(getattr(model, "outputs", None), "path", "") or ""
            cfg_out = str(cfg_out).strip()
            if cfg_out and cfg_out != "runs/default":
                output_dir = Path(cfg_out)
                logger.info(f"[Config] Using outputs.path from configuration as output directory: {output_dir}")
    except Exception:
        pass

    mode = None
    input_parts = input_file.parts
    if "warm_start" in input_parts:
        mode = "warm_start"
    elif "cold_start" in input_parts:
        mode = "cold_start"

    if mode:
        out_parts = output_dir.parts
        if len(out_parts) == 2 and out_parts[0] == "runs" and out_parts[1] == input_file.stem:
            output_dir = Path("runs") / mode / input_file.stem

    if auto:
        from dsbx.Gen.core.calibration_advisor import CalibrationAdvisor

        advisor = CalibrationAdvisor()

        if max_calib_steps is None:
            max_calib_steps = advisor.suggest_calibration_steps(model)
            logger.info(f"[AUTO] Suggested calibration steps: {max_calib_steps}")

        if not use_hybrid and not use_moo:
            mode = advisor.suggest_calibration_mode(model)
            if mode == "hybrid":
                use_hybrid = True
                logger.info("[AUTO] Selected Hybrid calibration mode")
            else:
                logger.info("[AUTO] Selected Sequential calibration mode")

    
    calib_config = model.calibration
    
    if not auto and not use_moo and not use_hybrid:
        if calib_config.mode == "moo":
            use_moo = True
            logger.info("[Config] Using MOO calibration mode from configuration")
        elif calib_config.mode == "hybrid":
            use_hybrid = True
            logger.info("[Config] Using Hybrid calibration mode from configuration")
        elif calib_config.mode == "auto":
            logger.info("[Config] Configuration requested auto mode; selecting calibration mode automatically")
            from dsbx.Gen.core.calibration_advisor import CalibrationAdvisor
            advisor = CalibrationAdvisor()
            mode = advisor.suggest_calibration_mode(model)
            if mode == "hybrid":
                use_hybrid = True
                logger.info("[AUTO] Selected Hybrid calibration mode")
            else:
                logger.info("[AUTO] Selected Sequential calibration mode")
    
    if max_calib_steps is None:
        max_calib_steps = calib_config.max_steps
        logger.debug(f"[Config] Using max_steps from configuration: {max_calib_steps}")
    
    if moo_population_size is None:
        moo_population_size = calib_config.moo_population_size
    if moo_n_generations is None:
        moo_n_generations = calib_config.moo_n_generations
    
    if hybrid_population_size is None:
        hybrid_population_size = calib_config.hybrid_population_size
    if hybrid_n_generations is None:
        hybrid_n_generations = calib_config.hybrid_n_generations
    if hybrid_convergence_window is None:
        hybrid_convergence_window = calib_config.hybrid_convergence_window
    if hybrid_convergence_tol is None:
        hybrid_convergence_tol = calib_config.hybrid_convergence_tol
    if hybrid_max_sequential_steps is None:
        hybrid_max_sequential_steps = calib_config.hybrid_max_sequential_steps
    
    if seq_early_stop_no_improve_steps is None:
        seq_early_stop_no_improve_steps = calib_config.seq_early_stop_no_improve_steps
    if seq_early_stop_relax_factor is None:
        seq_early_stop_relax_factor = calib_config.seq_early_stop_relax_factor
    if seq_min_relative_improvement is None:
        seq_min_relative_improvement = calib_config.seq_min_relative_improvement
    
    if tol_rho is None:
        tol_rho = calib_config.seq_tol_rho_global
    if tol_scv_a is None:
        tol_scv_a = calib_config.seq_tol_scv_a
    if tol_scv_p is None:
        tol_scv_p = calib_config.seq_tol_scv_p
    if tol_ddt is None:
        tol_ddt = calib_config.seq_tol_ddt
    if tol_disturbance is None:
        tol_disturbance = calib_config.seq_tol_disturbance
    if tol_load_cv is None:
        tol_load_cv = calib_config.seq_tol_load_cv
    

    if not use_moo and (moo_population_size != calib_config.moo_population_size or 
                        moo_n_generations != calib_config.moo_n_generations):
        logger.warning("MOO-related options were provided but --use-moo is not enabled; they will be ignored.")

    if not use_hybrid and any(
        opt != getattr(calib_config, attr)
        for opt, attr in [
            (hybrid_population_size, "hybrid_population_size"),
            (hybrid_n_generations, "hybrid_n_generations"),
            (hybrid_convergence_window, "hybrid_convergence_window"),
            (hybrid_convergence_tol, "hybrid_convergence_tol"),
            (hybrid_max_sequential_steps, "hybrid_max_sequential_steps"),
        ]
    ):
        logger.warning(
            "Hybrid-related options were provided but --use-hybrid is not enabled; "
            "they will be ignored."
        )

    run_generation_pipeline(
        model=model,
        output_path=output_dir,
        max_calib_steps=max_calib_steps,
        compare_metrics_paths=compare_to,
        use_moo=use_moo,
        use_hybrid=use_hybrid,
        moo_population_size=moo_population_size,
        moo_n_generations=moo_n_generations,
        hybrid_population_size=hybrid_population_size,
        hybrid_n_generations=hybrid_n_generations,
        hybrid_convergence_window=hybrid_convergence_window,
        hybrid_convergence_tol=hybrid_convergence_tol,
        hybrid_max_sequential_steps=hybrid_max_sequential_steps,
        seq_early_stop_no_improve_steps=seq_early_stop_no_improve_steps,
        seq_early_stop_relax_factor=seq_early_stop_relax_factor,
        seq_min_relative_improvement=seq_min_relative_improvement,
        seq_tol_rho_global=tol_rho,
        seq_tol_scv_a=tol_scv_a,
        seq_tol_scv_p=tol_scv_p,
        seq_tol_ddt=tol_ddt,
        seq_tol_disturbance=tol_disturbance,
        seq_tol_load_cv=tol_load_cv,
    )



@app.command(name="gen-batch")
def gen_batch(
    input_file: Annotated[
        Path,
        typer.Option("-i", "--input", help="Path to the batch input JSON file.", exists=True),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("-o", "--output", help="Base directory for all generated instances."),
    ],
    max_calib_steps: Annotated[
        int,
        typer.Option(help="Maximum calibration steps per instance (for sequential mode)."),
    ] = 25,
    use_moo: Annotated[
        bool,
        typer.Option("--use-moo", help="Use Multi-Objective Optimization (NSGA-II) v3 for calibration."),
    ] = False,
    use_hybrid: Annotated[
        bool,
        typer.Option("--use-hybrid", help="Use Hybrid calibration (Sequential + MOO for coupled metrics)."),
    ] = False,
) -> None:
    """Generate a batch of instances from an input file with parameter ranges.

    Generate multiple DynaSchedBench instances from batchable targets.
    """

    log_file = init_logging(component="G", command="gen-batch", log_level="INFO", run_id=input_file.stem)
    run_log_dir = log_file.parent

    try:
        batch_model: InputModel = load_input_model(input_file)
    except (ValueError, FileNotFoundError) as e:  # pragma: no cover - CLI error path
        logger.error(f"Error loading batch input file: {e}")
        raise typer.Exit(code=3)

    output_dir.mkdir(parents=True, exist_ok=True)
    all_metrics: List[Dict[str, Any]] = []

    for i, instance_model in enumerate(_expand_batch_parameters(batch_model)):
        instance_name = f"instance_{i:03d}"
        instance_path = output_dir / instance_name

        instance_log_path = run_log_dir / f"{instance_name}.log"
        instance_handler_id = logger.add(instance_log_path, level="INFO", encoding="utf-8")
        try:
            logger.info(f"--- Generating Batch Instance {i+1}: {instance_name} ---")

            param_str = ", ".join(
                f"{k}={v}" for k, v in instance_model.targets.model_dump().items() if isinstance(v, (int, float))
            )
            logger.info(f"Parameters: {param_str}, Seed: {instance_model.meta.seed}")

            final_metrics = run_generation_pipeline(
                model=instance_model,
                output_path=instance_path,
                max_calib_steps=max_calib_steps,
                compare_metrics_paths=None,
                use_moo=use_moo,
                use_hybrid=use_hybrid,
            )
        finally:
            logger.remove(instance_handler_id)

        if final_metrics:
            flat_metrics: Dict[str, Any] = {k: v for k, v in final_metrics.items() if k != "SSI"}
            flat_metrics.update({f"SSI_{k}": v for k, v in final_metrics.get("SSI", {}).items()})
            flat_metrics["instance_name"] = instance_name

            target_metrics_dict = {
                "rho_global": instance_model.targets.rho_global,
                "ddt": instance_model.targets.ddt,
                "scv_a": instance_model.targets.scv_a,
                "scv_p": instance_model.targets.scv_p,
            }
            flat_metrics.update({f"target_{k}": v for k, v in target_metrics_dict.items()})
            all_metrics.append(flat_metrics)

    if not all_metrics:
        logger.warning("No instances were successfully generated in the batch.")
        return

    summary_df = pd.DataFrame(all_metrics).round(4)
    summary_csv_path = output_dir / "summary.csv"
    summary_df.to_csv(summary_csv_path, index=False)
    logger.info(f"✅ Batch summary saved to {summary_csv_path}")

    isa_plot_path = output_dir / "instance_space.png"
    plot_instance_space(summary_df, isa_plot_path)
    logger.info(f"✅ Instance Space plot saved to {isa_plot_path}")


@app.command(name="replay")
def replay(
    input_file: Annotated[
        Path,
        typer.Option("-i", "--input", help="Path to the input JSON file.", exists=True),
    ],
    pareto_file: Annotated[
        Path,
        typer.Option("-p", "--pareto", help="Path to pareto_info.json.", exists=True),
    ],
    solution_id: Annotated[
        int,
        typer.Option("--solution-id", help="Index of the solution in Pareto front (0-based)."),
    ] = 0,
    output_dir: Annotated[
        Path,
        typer.Option("-o", "--output", help="Directory to save the replayed instance."),
    ] = Path("runs/replay"),
    log_level: Annotated[
        str,
        typer.Option("--log-level", help="Logging level: DEBUG, INFO, WARNING, ERROR."),
    ] = "INFO",
    list_only: Annotated[
        bool,
        typer.Option("--list", help="List all Pareto solutions with indices and exit."),
    ] = False,
) -> None:
    """Replay a specific Pareto solution and regenerate events.

    This command does **not** rerun the full MOO/Hybrid search. Instead, it:

    1. Loads the original input model.
    2. Reads the saved pareto_info.json.
    3. Selects a decision vector by ``solution_id``.
    4. Applies it to the base model using the same transformation logic
       as the original calibrator (MOO v3 or Hybrid 5D MOO).
    5. Regenerates events and writes ``events.jsonl`` and ``final_metrics.json``
       to the specified output directory.
    """

    run_id = f"{input_file.stem}_replay_{solution_id}"
    init_logging(component="G", command="replay", log_level=log_level, run_id=run_id)

    try:
        model: InputModel = load_input_model(input_file)
    except (ValueError, FileNotFoundError) as e:
        msg = f"Error loading input file: {e}"
        logger.error(msg)
        print(msg)
        raise typer.Exit(code=3)

    try:
        projector = FeasibilityProjector(model)
        model, _ = projector.check_and_project()
    except Exception as proj_exc:
        logger.warning(f"Feasibility projection failed in replay; proceeding with original model: {proj_exc}")

    try:
        with open(pareto_file, "r", encoding="utf-8") as f:
            pareto_info = json.load(f)
    except Exception as e:
        msg = f"Error loading pareto file: {e}"
        logger.error(msg)
        print(msg)
        raise typer.Exit(code=3)

    pareto_points = pareto_info.get("pareto_points") or []
    legacy_solutions = pareto_info.get("pareto_solutions") or []
    legacy_front = pareto_info.get("pareto_front") or []

    chosen_point: Optional[Dict[str, Any]] = None

    if pareto_points:
        n_solutions = len(pareto_points)
    else:
        n_solutions = len(legacy_solutions)

    if n_solutions == 0:
        msg = "pareto_info.json does not contain any Pareto solutions; cannot replay."
        logger.error(msg)
        print(msg)
        raise typer.Exit(code=3)

    if list_only:
        best_idx = pareto_info.get("best_index")
        objective_labels = pareto_info.get("objective_labels")

        if pareto_points:
            first_obj = pareto_points[0].get("objectives", [])
            n_obj = len(first_obj) if isinstance(first_obj, list) else 0
            header = ["solution_id"]
            if isinstance(objective_labels, list) and len(objective_labels) == n_obj:
                header.extend(str(lbl) for lbl in objective_labels)
            else:
                header.extend(f"f{i}" for i in range(n_obj))
            print("\t".join(header))

            for idx, pt in enumerate(pareto_points):
                sid = pt.get("id", idx)
                obj_vals = pt.get("objectives", [])
                row = [str(sid)]
                if isinstance(obj_vals, list):
                    row.extend(f"{float(v):.6f}" for v in obj_vals)
                mark = " *" if best_idx is not None and sid == int(best_idx) else ""
                print("\t".join(row) + mark)
        else:
            if not legacy_front:
                logger.info("Pareto front is empty; nothing to list.")
                print("Pareto front is empty; nothing to list.")
                return

            first = legacy_front[0]
            n_obj = len(first) if isinstance(first, list) else 0
            header = ["solution_id"]
            if isinstance(objective_labels, list) and len(objective_labels) == n_obj:
                header.extend(str(lbl) for lbl in objective_labels)
            else:
                header.extend(f"f{i}" for i in range(n_obj))
            print("\t".join(header))

            for idx, obj_vals in enumerate(legacy_front):
                row = [str(idx)]
                if isinstance(obj_vals, list):
                    row.extend(f"{float(v):.6f}" for v in obj_vals)
                mark = " *" if best_idx is not None and idx == int(best_idx) else ""
                print("\t".join(row) + mark)

        return

    if solution_id < 0:
        msg = f"Invalid solution_id={solution_id}. Must be non-negative."
        logger.error(msg)
        print(msg)
        raise typer.Exit(code=3)

    x: np.ndarray
    if pareto_points:
        chosen = None
        for idx, pt in enumerate(pareto_points):
            sid = int(pt.get("id", idx))
            if sid == solution_id:
                chosen = pt
                break
        if chosen is None:
            if solution_id >= len(pareto_points):
                msg = (
                    f"Invalid solution_id={solution_id}. "
                    f"Valid range: [0, {len(pareto_points) - 1}]."
                )
                logger.error(msg)
                print(msg)
                raise typer.Exit(code=3)
            chosen = pareto_points[solution_id]
        decision_vars = chosen.get("decision_vars")
        chosen_point = chosen
        if not isinstance(decision_vars, list):
            msg = "pareto_points entry is missing 'decision_vars'; cannot replay."
            logger.error(msg)
            print(msg)
            raise typer.Exit(code=3)
        x = np.asarray(decision_vars, dtype=float)
    else:
        if solution_id >= len(legacy_solutions):
            msg = (
                f"Invalid solution_id={solution_id}. "
                f"Valid range: [0, {len(legacy_solutions) - 1}]."
            )
            logger.error(msg)
            print(msg)
            raise typer.Exit(code=3)
        x = np.asarray(legacy_solutions[solution_id], dtype=float)
    calibration_mode = str(pareto_info.get("calibration_mode", "")).lower()

    logger.info(f"Replaying solution #{solution_id} using calibration_mode='{calibration_mode}'")

    if "hybrid" in calibration_mode:
        problem = CoupledMetricsProblem(base_model=model, target_metrics={})
        modified_model = problem._create_modified_model(x)
    elif "moo" in calibration_mode:
        problem = ExtendedCalibrationProblem(base_model=model, target_metrics={})
        modified_model = problem._create_extended_model(x)
    else:
        msg = (
            "Unknown or missing calibration_mode in pareto_info.json; "
            "expected something like 'hybrid_5d_moo' or 'moo_v3_extended'."
        )
        logger.error(msg)
        print(msg)
        raise typer.Exit(code=3)

    det_seed: Optional[int] = None
    if chosen_point is not None:
        try:
            raw_seed = chosen_point.get("deterministic_seed")
            if raw_seed is not None:
                det_seed = int(raw_seed)
        except Exception:
            det_seed = None

    seed_manager = SeedManager(det_seed if det_seed is not None else modified_model.meta.seed)
    constructor = FastPathConstructor(modified_model, seed_manager)
    events = constructor.generate_events()

    metrics_engine = MetricsEngine(modified_model, events)
    final_metrics: Dict[str, Any] = metrics_engine.estimate()

    exporter = Exporter(output_dir)

    input_str = modified_model.model_dump_json()
    input_hash = exporter.write_meta(input_str, __version__, seed_manager.get_seed_map())

    # 2) Build target metrics with the same semantics as the generation pipeline.
    def _as_float(v: Any) -> float:
        return float(v[0]) if isinstance(v, list) and v else float(v)

    target_metrics_dict: Dict[str, float] = {
        "rho_global": _as_float(modified_model.targets.rho_global),
        "rho_bottleneck": 0.0,
        "ddt": _as_float(modified_model.targets.ddt),
        "scv_a": _as_float(modified_model.targets.scv_a),
        "scv_p": _as_float(modified_model.targets.scv_p),
        "disturbance": _as_float(modified_model.targets.disturbance),
    }
    if getattr(modified_model.targets, "load_cv", None) is not None:
        target_metrics_dict["load_cv"] = float(modified_model.targets.load_cv)

    errors: Dict[str, float] = {
        k: (abs(final_metrics.get(k, 0) - v) / v if v != 0 else 0.0)
        for k, v in target_metrics_dict.items()
    }

    replay_objective_labels: List[str] = []
    replay_objectives: List[float] = []

    base_targets = model.targets

    if "hybrid" in calibration_mode:
        scv_a_target = float(getattr(base_targets, "scv_a", 1.0))
        scv_p_target = float(getattr(base_targets, "scv_p", 1.0))
        ddt_target = float(getattr(base_targets, "ddt", 2.0))
        load_cv_target = float(getattr(base_targets, "load_cv", 0.2))

        scv_a_obs = float(final_metrics.get("scv_a", 0.0))
        scv_p_obs = float(final_metrics.get("scv_p", 0.0))
        ddt_obs = float(final_metrics.get("ddt", 0.0))
        rho_bn_obs = float(final_metrics.get("rho_bottleneck", 0.0))
        load_cv_obs = float(final_metrics.get("load_cv", 0.0))

        has_bottleneck = bool(getattr(base_targets, "rho_bottleneck", None))
        has_load_cv = getattr(base_targets, "load_cv", None) is not None

        # scv_a
        replay_objective_labels.append("scv_a")
        if scv_a_target < 0.01:
            replay_objectives.append(abs(scv_a_obs))
        else:
            replay_objectives.append(abs(scv_a_obs - scv_a_target) / (scv_a_target + 0.1))

        # scv_p
        replay_objective_labels.append("scv_p")
        if scv_p_target < 0.01:
            replay_objectives.append(abs(scv_p_obs))
        else:
            replay_objectives.append(abs(scv_p_obs - scv_p_target) / (scv_p_target + 0.1))

        # ddt
        replay_objective_labels.append("ddt")
        replay_objectives.append(abs(ddt_obs - ddt_target) / (ddt_target + 1e-6))

        # rho_bottleneck
        if has_bottleneck:
            replay_objective_labels.append("rho_bottleneck")
            replay_objectives.append(abs(rho_bn_obs) / 0.8)

        # load_cv
        if has_load_cv:
            replay_objective_labels.append("load_cv")
            if load_cv_target < 1e-6:
                replay_objectives.append(abs(load_cv_obs))
            else:
                replay_objectives.append(abs(load_cv_obs - load_cv_target) / (load_cv_target + 0.01))

    elif "moo" in calibration_mode:
        if getattr(base_targets, "rho_global", None) is not None:
            rho_target = float(getattr(base_targets, "rho_global", 0.0))
            scv_a_target = float(getattr(base_targets, "scv_a", 0.0))
            scv_p_target = float(getattr(base_targets, "scv_p", 0.0))
            ddt_target = float(getattr(base_targets, "ddt", 0.0))
            dist_target = float(getattr(base_targets, "disturbance", 0.0))

            rho_obs = float(final_metrics.get("rho_global", rho_target))
            scv_a_obs = float(final_metrics.get("scv_a", scv_a_target))
            scv_p_obs = float(final_metrics.get("scv_p", scv_p_target))
            ddt_obs = float(final_metrics.get("ddt", ddt_target))
            dist_obs = float(final_metrics.get("disturbance", dist_target))

            replay_objective_labels.append("rho")
            if rho_target > 0:
                replay_objectives.append(abs(rho_obs - rho_target) / (rho_target + 1e-6))
            else:
                replay_objectives.append(abs(rho_obs))

            replay_objective_labels.append("scv_a")
            replay_objectives.append(abs(scv_a_obs - scv_a_target) / max(abs(scv_a_target), 0.01))

            replay_objective_labels.append("scv_p")
            replay_objectives.append(abs(scv_p_obs - scv_p_target) / max(abs(scv_p_target), 0.01))

            replay_objective_labels.append("ddt")
            if ddt_target > 0:
                replay_objectives.append(abs(ddt_obs - ddt_target) / (ddt_target + 1e-6))
            else:
                replay_objectives.append(abs(ddt_obs))

            replay_objective_labels.append("disturbance")
            if dist_target > 0:
                replay_objectives.append(abs(dist_obs - dist_target) / max(abs(dist_target), 0.01))
            else:
                replay_objectives.append(abs(dist_obs))

            has_load_cv = getattr(base_targets, "load_cv", None) is not None
            if has_load_cv:
                load_target = float(getattr(base_targets, "load_cv", 0.0))
                load_obs = float(final_metrics.get("load_cv", load_target))
                replay_objective_labels.append("load_cv")
                if load_target < 1e-6:
                    replay_objectives.append(abs(load_obs))
                else:
                    replay_objectives.append(abs(load_obs - load_target) / max(abs(load_target), 0.01))

            has_bottleneck = bool(getattr(base_targets, "rho_bottleneck", None))
            if has_bottleneck:
                rho_bn_obs = float(final_metrics.get("rho_bottleneck", 0.0))
                replay_objective_labels.append("rho_bottleneck")
                replay_objectives.append(abs(rho_bn_obs))

    else:
        logger.warning(
            "Unknown or missing calibration_mode when computing replay_objectives; "
            "replay_objectives.json will not be written."
        )

    if replay_objective_labels:
        try:
            original_objectives = None
            original_labels = pareto_info.get("objective_labels") if isinstance(pareto_info, dict) else None

            pareto_points = pareto_info.get("pareto_points") if isinstance(pareto_info, dict) else None
            if isinstance(pareto_points, list):
                for pt in pareto_points:
                    sid = int(pt.get("id", -1))
                    if sid == solution_id:
                        original_objectives = pt.get("objectives")
                        break

            replay_diag = {
                "solution_id": solution_id,
                "objective_labels_replay": replay_objective_labels,
                "objectives_replay": replay_objectives,
                "objective_labels_original": original_labels,
                "objectives_original": original_objectives,
            }

            (output_dir / "replay_objectives.json").write_text(
                json.dumps(replay_diag, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            logger.info("Replay objectives (MOO/Hybrid objective space):")
            for lbl, val in zip(replay_objective_labels, replay_objectives):
                logger.info(f"  {lbl}: {val:.6f}")
        except Exception as diag_exc:
            logger.warning(f"Failed to write replay_objectives.json: {diag_exc}")

    exporter.write_events(events)
    exporter.write_final_metrics(final_metrics)

    exporter.write_trace(pd.DataFrame({"time": [0.0]}))

    projections: List[str] = []
    report_data = FinalReportData(  # type: ignore[call-arg]
        input_hash=input_hash,
        version=__version__,
        seed_map=seed_manager.get_seed_map(),
        target_metrics=target_metrics_dict,
        observed_metrics={k: float(final_metrics.get(k, 0.0)) for k in target_metrics_dict},
        errors=errors,
        projections=projections,
        ssi=final_metrics.get("SSI", {}),
        comparison_report=None,
    )
    exporter.write_report(report_data)

    logger.info(f"Replay completed. All artifacts saved to: {output_dir}")
