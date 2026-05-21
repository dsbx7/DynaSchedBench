from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from loguru import logger
from typing_extensions import Annotated

from dsbx.Eval import Trajectory
from dsbx.Logging import init_logging
from dsbx.Eval.Metrics import evaluate_trajectory
from dsbx.Eval.Constraints import run_all_checks
from dsbx.Gen import load_input_model
from dsbx.Eval.InstanceChecks import load_events_jsonl, validate_instance
from dsbx.Eval.EpisodeDebug import build_episode_debug


app = typer.Typer(
    name="dsbx-eval",
    help="Evaluate DynaSchedBench trajectories and generated instances.",
    add_completion=False,
)


@app.command(name="from-trajectory")
def from_trajectory(
    trajectory_file: Annotated[
        Path,
        typer.Option(
            "-t",
            "--trajectory",
            exists=True,
            readable=True,
            help="Path to a JSON file containing a serialized Trajectory (Pydantic model_dump_json output).",
        ),
    ],
    out_metrics: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--out",
            help="Optional path to write the computed metrics as JSON.",
        ),
    ] = None,
    show_violations: Annotated[
        bool,
        typer.Option("--show-violations/--hide-violations", help="Whether to print detected hard-constraint violations."),
    ] = True,
    fail_on_violation: Annotated[
        bool,
        typer.Option("--fail-on-violation", help="Exit with non-zero code if any hard-constraint violations are found."),
    ] = False,
    warm: Annotated[
        bool,
        typer.Option(
            "--warm",
            help=(
                "Enable warm-start evaluation: ignore an initial warm-up period "
                "for time-series metrics (WIP, queue, stability, etc.)."
            ),
        ),
    ] = False,
    warmup_ratio: Annotated[
        float,
        typer.Option(
            "--warmup-ratio",
            help=(
                "For --warm: fraction of the trajectory time to treat as warm-up "
                "and ignore when aggregating over-time metrics (0.0-1.0)."
            ),
        ),
    ] = 0.3,
) -> None:
    """Evaluate a serialized trajectory and print metrics to stdout.

    The input JSON is expected to be created via ``Trajectory.model_dump_json``
    (or an equivalent serialization). The command will:
    1. Load the trajectory
    2. Compute static+dynamic metrics
    3. Optionally run hard-constraint checks
    4. Print metrics as JSON and optionally write them to disk
    """

    init_logging(component="E", command="from-trajectory", log_level="INFO", run_id=trajectory_file.stem)

    if trajectory_file.suffix.lower() == ".jsonl":
        try:
            traj = Trajectory.load_from_disk(trajectory_file)
        except Exception as e:  # pragma: no cover - filesystem error path
            logger.error(f"Failed to load trajectory JSONL file: {e}")
            raise typer.Exit(code=3)
    else:
        try:
            raw = trajectory_file.read_text(encoding="utf-8")
        except OSError as e:  # pragma: no cover - filesystem error path
            logger.error(f"Failed to read trajectory file: {e}")
            raise typer.Exit(code=3)

        traj = Trajectory.model_validate_json(raw)

    # Determine the evaluation window start time for optional warm-start behavior.
    start_time = 0.0
    try:
        last_time = float(traj.last_snapshot.time)
    except Exception:  # pragma: no cover - defensive fallback
        last_time = 0.0

    if warm and last_time > 0.0:
        ratio = float(warmup_ratio)
        if ratio < 0.0:
            ratio = 0.0
        if ratio >= 1.0:
            ratio = 0.99
        start_time = ratio * last_time

    metrics = evaluate_trajectory(traj, start_time=start_time)
    violations = run_all_checks(traj)

    # Print metrics to stdout
    print(json.dumps(metrics, indent=2, ensure_ascii=False))

    if out_metrics is not None:
        try:
            out_metrics.parent.mkdir(parents=True, exist_ok=True)
            out_metrics.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"Metrics written to {out_metrics}")
        except OSError as e:  # pragma: no cover - filesystem error path
            logger.error(f"Failed to write metrics file: {e}")

    if show_violations and violations:
        print("\nViolations:")
        for v in violations:
            print(json.dumps(v.model_dump(), indent=2, ensure_ascii=False))

    if fail_on_violation and violations:
        logger.error(f"Found {len(violations)} hard-constraint violations; exiting with code 2.")
        raise typer.Exit(code=2)


@app.command(name="debug-llmscheduler")
def debug_llmscheduler(
    trajectory_file: Annotated[
        Path,
        typer.Option(
            "-t",
            "--trajectory",
            exists=True,
            readable=True,
            help="Path to a trajectory JSONL file (streaming Trajectory).",
        ),
    ],
    events_file: Annotated[
        Path,
        typer.Option(
            "-e",
            "--events",
            exists=True,
            readable=True,
            help="Path to the events.jsonl file used for this episode.",
        ),
    ],
    log_file: Annotated[
        Path,
        typer.Option(
            "-l",
            "--log",
            exists=True,
            readable=True,
            help="Path to the run log file (e.g. main.log) containing LLM debug output.",
        ),
    ],
    static_jobs: Annotated[
        Optional[Path],
        typer.Option(
            "--static-jobs",
            help="Optional path to static_jobs.json (defaults to events directory / static_jobs.json).",
        ),
    ] = None,
    static_machines: Annotated[
        Optional[Path],
        typer.Option(
            "--static-machines",
            help="Optional path to static_machines.json (defaults to events directory / static_machines.json).",
        ),
    ] = None,
    out_file: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--out",
            help=(
                "Optional path to write the consolidated debug JSONL. "
                "Defaults to <trajectory_basename>.edebug.jsonl in the trajectory directory."
            ),
        ),
    ] = None,
) -> None:
    """Build a compact per-step debug JSONL view for an episode.

    This command consolidates information from a trajectory JSONL, events.jsonl,
    and a run log (containing LLMPolicy debug messages) into a single
    <*.edebug.jsonl> file. Static jobs/machines JSON files are recorded in the
    meta header for completeness.
    """

    init_logging(component="E", command="debug-llmscheduler", log_level="INFO", run_id=trajectory_file.stem)

    # Resolve defaults for optional static paths and output path.
    events_dir = events_file.parent
    if static_jobs is None:
        sj = events_dir / "static_jobs.json"
        static_jobs = sj if sj.exists() else None
    if static_machines is None:
        sm = events_dir / "static_machines.json"
        static_machines = sm if sm.exists() else None

    if out_file is None:
        # Default: same directory as trajectory, same stem, .edebug.jsonl suffix
        out_file = trajectory_file.with_suffix("")
        out_file = out_file.with_name(out_file.name + ".edebug.jsonl")

    try:
        build_episode_debug(
            trajectory_path=trajectory_file,
            events_path=events_file,
            static_jobs_path=static_jobs,
            static_machines_path=static_machines,
            log_path=log_file,
            output_path=out_file,
        )
    except Exception as e:
        logger.error("Failed to build episode debug file: {}", e)
        raise typer.Exit(code=3)

    logger.info("Episode debug file written to {}", out_file)


@app.command(name="debug-llmcoder")
def debug_llmcoder(
    trajectory_file: Annotated[
        Path,
        typer.Option(
            "-t",
            "--trajectory",
            exists=True,
            readable=True,
            help="Path to the environment trajectory JSON/JSONL file.",
        ),
    ],
    events_file: Annotated[
        Path,
        typer.Option(
            "-e",
            "--events",
            exists=True,
            readable=True,
            help="Path to the events.jsonl file used for this episode.",
        ),
    ],
    coder_trajectory_file: Annotated[
        Path,
        typer.Option(
            "--coder-trajectory",
            exists=True,
            readable=True,
            help="Path to the LLMCoder internal trajectory JSONL file.",
        ),
    ],
    log_file: Annotated[
        Path,
        typer.Option(
            "-l",
            "--log",
            exists=True,
            readable=True,
            help="Path to the run log file (e.g. main.log) containing LLMCoder debug output.",
        ),
    ],
    static_jobs: Annotated[
        Optional[Path],
        typer.Option(
            "--static-jobs",
            help="Optional path to static_jobs.json (defaults to events directory / static_jobs.json).",
        ),
    ] = None,
    static_machines: Annotated[
        Optional[Path],
        typer.Option(
            "--static-machines",
            help="Optional path to static_machines.json (defaults to events directory / static_machines.json).",
        ),
    ] = None,
    out_file: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--out",
            help=(
                "Optional path to write the consolidated LLMCoder debug JSON. "
                "Defaults to <trajectory_basename>.llmcoder.edebug.json in the trajectory directory."
            ),
        ),
    ] = None,
) -> None:
    """Build a consolidated debug JSON file for an LLMCoder episode.

    This command is analogous to debug-llmscheduler but tailored to LLMCoder.
    It consolidates information from:

    - the environment trajectory (JSON/JSONL);
    - the input events.jsonl;
    - LLMCoder's own internal trajectory JSONL;
    - the main log file with LLMCoder-specific debug messages.
    """

    from dsbx.Eval.LLMCoderDebug import build_llmcoder_debug

    init_logging(component="E", command="debug-llmcoder", log_level="INFO", run_id=trajectory_file.stem)

    events_dir = events_file.parent
    if static_jobs is None:
        sj = events_dir / "static_jobs.json"
        static_jobs = sj if sj.exists() else None
    if static_machines is None:
        sm = events_dir / "static_machines.json"
        static_machines = sm if sm.exists() else None

    if out_file is None:
        out_file = trajectory_file.with_suffix("")
        out_file = out_file.with_name(out_file.name + ".llmcoder.edebug.json")

    try:
        build_llmcoder_debug(
            trajectory_path=trajectory_file,
            events_path=events_file,
            static_jobs_path=static_jobs,
            static_machines_path=static_machines,
            coder_trajectory_path=coder_trajectory_file,
            log_path=log_file,
            output_path=out_file,
        )
    except Exception as e:
        logger.error("Failed to build LLMCoder debug file: {}", e)
        raise typer.Exit(code=3)

    logger.info("LLMCoder debug file written to {}", out_file)


@app.command(name="check-events")
def check_events(
    config_file: Annotated[
        Path,
        typer.Option(
            "-c",
            "--config",
            exists=True,
            readable=True,
            help="Path to the input model JSON config used to generate the instance.",
        ),
    ],
    events_file: Annotated[
        Path,
        typer.Option(
            "-e",
            "--events",
            exists=True,
            readable=True,
            help="Path to the events.jsonl file to validate.",
        ),
    ],
    run_feasibility: Annotated[
        bool,
        typer.Option(
            "--feas/--no-feas",
            help="Whether to run target feasibility checks via FeasibilityProjector.",
        ),
    ] = True,
    strict_events: Annotated[
        bool,
        typer.Option(
            "--strict-events/--no-strict-events",
            help=(
                "Whether to run strict event-consistency checks (job references, cancellation ordering, "
                "ptime step bounds, etc.)."
            ),
        ),
    ] = False,
    strict_max_messages: Annotated[
        int,
        typer.Option(
            "--strict-max-messages",
            help="Max number of strict-check messages to include per severity (errors/warnings).",
        ),
    ] = 50,
    strict_allow_unknown_jobs: Annotated[
        bool,
        typer.Option(
            "--strict-allow-unknown-jobs/--strict-disallow-unknown-jobs",
            help=(
                "If enabled, strict event checks downgrade unknown-job references (e.g., PRIORITY_CHANGE for a job_id "
                "with no ARRIVAL in the file) from errors to warnings."
            ),
        ),
    ] = False,
    fail_on_error: Annotated[
        bool,
        typer.Option(
            "--fail-on-error",
            help="Exit with non-zero code if any instance validation error is found.",
        ),
    ] = False,
) -> None:
    init_logging(component="E", command="check-events", log_level="INFO", run_id=config_file.stem)

    try:
        model = load_input_model(config_file)
    except Exception as e:
        logger.error(f"Failed to load input model: {e}")
        raise typer.Exit(code=3)

    try:
        events = load_events_jsonl(events_file, sort_events=False)
    except Exception as e:
        logger.error(f"Failed to read events file: {e}")
        raise typer.Exit(code=3)

    summary = validate_instance(
        model,
        events,
        run_feasibility_projector=run_feasibility,
        run_strict_event_checks=strict_events,
        strict_max_messages=strict_max_messages,
        strict_allow_unknown_jobs=strict_allow_unknown_jobs,
    )

    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if fail_on_error and not summary.get("is_valid", False):
        logger.error("Instance validation reported errors; exiting with code 2.")
        raise typer.Exit(code=2)


@app.command(name="check-schedule")
def check_schedule(
    trajectory_file: Annotated[
        Path,
        typer.Option(
            "-t",
            "--trajectory",
            exists=True,
            readable=True,
            help="Path to a JSON file containing a serialized Trajectory (Pydantic model_dump_json output).",
        ),
    ],
    show_violations: Annotated[
        bool,
        typer.Option(
            "--show-violations/--hide-violations",
            help="Whether to print detected hard-constraint violations.",
        ),
    ] = True,
    fail_on_violation: Annotated[
        bool,
        typer.Option(
            "--fail-on-violation",
            help="Exit with non-zero code if any hard-constraint violations are found.",
        ),
    ] = False,
) -> None:
    init_logging(component="E", command="check-schedule", log_level="INFO", run_id=trajectory_file.stem)

    if trajectory_file.suffix.lower() == ".jsonl":
        try:
            traj = Trajectory.load_from_disk(trajectory_file)
        except Exception as e:
            logger.error(f"Failed to load trajectory JSONL file: {e}")
            raise typer.Exit(code=3)
    else:
        try:
            raw = trajectory_file.read_text(encoding="utf-8")
        except OSError as e:
            logger.error(f"Failed to read trajectory file: {e}")
            raise typer.Exit(code=3)

        traj = Trajectory.model_validate_json(raw)
    violations = run_all_checks(traj)

    summary = {
        "is_feasible": len(violations) == 0,
        "num_violations": len(violations),
        "violations": [v.model_dump() for v in violations],
    }

    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if show_violations and violations:
        print("\nHard-constraint violations:")
        for v in violations:
            print(json.dumps(v.model_dump(), indent=2, ensure_ascii=False))

    if fail_on_violation and violations:
        logger.error(f"Found {len(violations)} hard-constraint violations; exiting with code 2.")
        raise typer.Exit(code=2)


if __name__ == "__main__":  # pragma: no cover
    app()
