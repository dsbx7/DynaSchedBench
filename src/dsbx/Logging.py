from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import os
import sys
from loguru import logger


def init_logging(
    component: str,
    command: str,
    *,
    log_level: str = "INFO",
    run_id: Optional[str] = None,
    timestamp_prefix: Optional[str] = None,
) -> Path:
    """Initialize loguru logging for a DynaSchedBench CLI entry.

    Logs are written to a per-command run directory:
        <repo_root>/logs/<component>/<command>/<timestamp>_<component>_<command>[_runid]/main.log

    where:
      - ``component`` is a short tag like "G", "E", "V", "A", "S";
      - ``command`` is the subcommand name, e.g. "gen", "from-trajectory";
      - ``run_id`` is an optional extra identifier such as the config or trajectory stem.
    """

    # Resolve the repository root from this module's location: dsbx/Logging.py -> repo root
    repo_root = Path(__file__).resolve().parent.parent
    logs_root = repo_root / "logs"

    # Per-command directory: logs/<component>/<command>/
    command_dir = logs_root / component.lower() / command.replace(" ", "_")

    if timestamp_prefix:
        ts = str(timestamp_prefix)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    parts = [component, command]
    if run_id:
        parts.append(run_id)
    safe_suffix = "_".join(parts)

    run_dir = command_dir / f"{ts}_{safe_suffix}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "main.log"
    sandbox_log_file = run_dir / "sandbox_eval.log"

    try:
        os.environ["DYNA_SCHEDBENCH_RUN_LOG_DIR"] = str(run_dir)
    except Exception:
        pass

    logger.remove()

    logger.add(sys.stderr, level=log_level.upper())

    logger.add(
        log_file,
        level="DEBUG",
        encoding="utf-8",
        filter=lambda record: not bool(record["extra"].get("sandbox_eval", False)),
    )

    logger.add(
        sandbox_log_file,
        level="DEBUG",
        encoding="utf-8",
        filter=lambda record: bool(record["extra"].get("sandbox_eval", False)),
    )

    return log_file
