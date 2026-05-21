from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from loguru import logger
from typing_extensions import Annotated

from dsbx.Gen import load_input_model, SeedManager, FastPathConstructor
from dsbx.Logging import init_logging
from dsbx.Sim import DynaSchedSim
from dsbx.Sim.Snapshot import Snapshot


app = typer.Typer(
    name="dsbx-sim",
    help="Inspect DynaSchedBench simulator state.",
    add_completion=False,
)


@app.command(name="snapshot")
def snapshot(
    config_file: Annotated[
        Path,
        typer.Option(
            "-c",
            "--config",
            exists=True,
            readable=True,
            help="Path to InputModel JSON file.",
        ),
    ],
    out_path: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--out",
            help=(
                "Optional output path for the snapshot JSON. If omitted, the snapshot "
                "will only be printed to stdout."
            ),
        ),
    ] = None,
    time: Annotated[
        float,
        typer.Option(
            "-t",
            "--time",
            help=(
                "Decision time at which to export the snapshot. Events up to this "
                "time will be applied, but no scheduling actions are taken."
            ),
        ),
    ] = 0.0,
) -> None:
    """Export a simulator snapshot at a given decision time.

    This command is intentionally conservative: it only applies the generated
    event stream (arrivals, due dates, breakdowns, etc.) and exports the
    corresponding system state without running any scheduling algorithm.
    """

    init_logging(component="S", command="snapshot", log_level="INFO", run_id=config_file.stem)

    model = load_input_model(config_file)
    sm = SeedManager(model.meta.seed)
    constructor = FastPathConstructor(model, sm)
    events = constructor.generate_events()

    sim = DynaSchedSim(model, events)
    snap = sim.reset()

    if time > 0.0:
        # Advance the simulator to the requested time, applying all events.
        sim._process_events_until(time)  # type: ignore[attr-defined]
        snap = sim.export_snapshot()

    # Serialize snapshot as JSON
    snap_json = Snapshot.model_validate(snap).model_dump_json(indent=2, ensure_ascii=False)
    print(snap_json)

    if out_path is not None:
        out_path = Path(out_path)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(snap_json, encoding="utf-8")
            logger.info(f"Snapshot written to {out_path}")
        except OSError as e:  # pragma: no cover - filesystem error
            logger.error(f"Failed to write snapshot file: {e}")


if __name__ == "__main__":  # pragma: no cover
    app()
