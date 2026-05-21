from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from pydantic import BaseModel, Field, PrivateAttr

from dsbx.Sim.Snapshot import Snapshot


class StepRecord(BaseModel):
    """A single step in a scheduling trajectory.

    Each step records the decision point time, the full snapshot and the
    action that led to it. The `info` field can hold arbitrary metadata
    (e.g. rewards, solver stats).
    """

    time: float
    snapshot: Snapshot
    action: Optional[Dict[str, Any]] = None
    info: Dict[str, Any] = {}


class StaticContext(BaseModel):
    """Static, per-trajectory configuration shared by all snapshots.

    This mirrors the static fields embedded in :class:`Snapshot` and allows
    disk-backed trajectories to store them once in a header while rehydrating
    full snapshots on read.
    """

    scenario_id: Optional[str] = None
    seed: Optional[int] = None
    config_hash: Optional[str] = None

    plant: Optional[Dict[str, Any]] = None
    scale: Optional[Dict[str, Any]] = None
    targets: Optional[Dict[str, Any]] = None
    dynamics: Optional[Dict[str, Any]] = None
    dynamic_scenarios: Optional[Dict[str, Any]] = None


def _inject_static(snapshot: Snapshot, static: Optional[StaticContext]) -> Snapshot:
    """Return a copy of ``snapshot`` with missing static fields filled.

    The original ``snapshot`` is left untouched; if no updates are required,
    it is returned as-is.
    """

    if static is None:
        return snapshot

    update: Dict[str, Any] = {}

    if snapshot.scenario_id is None and static.scenario_id is not None:
        update["scenario_id"] = static.scenario_id
    if snapshot.seed is None and static.seed is not None:
        update["seed"] = static.seed
    if snapshot.config_hash is None and static.config_hash is not None:
        update["config_hash"] = static.config_hash

    if snapshot.plant is None and static.plant is not None:
        update["plant"] = static.plant
    if snapshot.scale is None and static.scale is not None:
        update["scale"] = static.scale
    if snapshot.targets is None and static.targets is not None:
        update["targets"] = static.targets
    if snapshot.dynamics is None and static.dynamics is not None:
        update["dynamics"] = static.dynamics
    if snapshot.dynamic_scenarios is None and static.dynamic_scenarios is not None:
        update["dynamic_scenarios"] = static.dynamic_scenarios

    if not update:
        return snapshot

    return snapshot.model_copy(update=update)


class Trajectory(BaseModel):
    """A sequence of decision points for a single scenario/run.

    In the disk-backed setting, this model acts primarily as a lightweight
    handle around a JSONL file that stores one header line with static
    context followed by per-step dynamic records. The legacy ``steps`` list
    is preserved for compatibility but is no longer required to hold the
    entire trajectory in memory.
    """

    # Legacy in-memory storage for compatibility. New code should prefer
    # streaming via :meth:`iter_steps` and disk-backed JSONL files.
    steps: List[StepRecord] = Field(default_factory=list)
    scenario_id: Optional[str] = None
    seed: Optional[int] = None
    config: Dict[str, Any] = {}

    # Static context shared by all snapshots in this trajectory.
    static_context: Optional[StaticContext] = None

    # Optional backing JSONL file; when set, the trajectory is streamed from
    # disk instead of relying on the in-memory ``steps`` list.
    _file_path: Optional[Path] = PrivateAttr(default=None)
    _mode: str = PrivateAttr(default="full")

    def append_step(self, step: StepRecord) -> None:
        """Append an in-memory step (legacy behaviour)."""

        self.steps.append(step)

    @property
    def last_snapshot(self) -> Snapshot:
        """Return the last snapshot, streaming from disk if necessary."""

        if self.steps:
            return self.steps[-1].snapshot

        if self._file_path is not None and self._mode == "summary":
            path = self._file_path
            last: Optional[Snapshot] = None
            try:
                with path.open("r", encoding="utf-8") as f:
                    first = f.readline()
                    if not first:
                        raise ValueError("Trajectory JSONL is empty, no header present")
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        obj = json.loads(line)
                        if obj.get("type") != "final_snapshot":
                            continue
                        snap_data = obj.get("snapshot") or {}
                        snap = Snapshot(**snap_data)
                        snap = _inject_static(snap, self.static_context)
                        last = snap
                if last is None:
                    raise ValueError("Trajectory JSONL (summary mode) has no final_snapshot record")
                return last
            except FileNotFoundError:
                # Fall back to in-memory handling below if the file vanished.
                pass

        last: Optional[Snapshot] = None
        for step in self.iter_steps():
            last = step.snapshot
        if last is None:
            raise ValueError("Trajectory is empty, no last_snapshot available")
        return last

    def iter_steps(self) -> Iterator[StepRecord]:
        """Iterate over all steps in the trajectory.

        If a backing JSONL file is configured, steps are streamed from disk and
        static context is injected on the fly. Otherwise, this falls back to
        iterating over the in-memory ``steps`` list.
        """

        if self._file_path is None:
            for step in self.steps:
                if self.static_context is not None:
                    snap = _inject_static(step.snapshot, self.static_context)
                    if snap is not step.snapshot:
                        step = StepRecord(
                            time=step.time,
                            snapshot=snap,
                            action=step.action,
                            info=step.info,
                        )
                yield step
            return

        path = self._file_path
        try:
            with path.open("r", encoding="utf-8") as f:
                # First line is expected to be a header; we rely on
                # ``load_from_disk`` to have already parsed and stored the
                # static context, so we can safely skip it here.
                first = f.readline()
                if not first:
                    return

                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    # Allow for explicit type tagging; ignore non-step records.
                    if obj.get("type") and obj.get("type") != "step":
                        continue

                    snap_data = obj.get("snapshot") or {}
                    snap = Snapshot(**snap_data)
                    snap = _inject_static(snap, self.static_context)

                    time_val = obj.get("time", getattr(snap, "time", 0.0))
                    action = obj.get("action")
                    info = obj.get("info") or {}

                    yield StepRecord(
                        time=float(time_val),
                        snapshot=snap,
                        action=action,
                        info=info,
                    )
        except FileNotFoundError:
            # Fallback: if the file is missing, behave as an in-memory
            # trajectory to avoid surprising callers.
            for step in self.steps:
                yield step

    def iter_summaries(self) -> Iterator[Dict[str, Any]]:
        if self._file_path is None or self._mode != "summary":
            return

        path = self._file_path
        try:
            with path.open("r", encoding="utf-8") as f:
                first = f.readline()
                if not first:
                    return

                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    if obj.get("type") != "summary":
                        continue
                    yield obj
        except FileNotFoundError:
            return

    @classmethod
    def load_from_disk(cls, path: Path) -> "Trajectory":
        """Create a disk-backed :class:`Trajectory` from a JSONL file.

        The file is expected to contain:

        * a first header line with a ``static_context`` object; and
        * subsequent lines describing individual steps with at least
          ``time`` and ``snapshot`` fields.
        """

        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Trajectory file does not exist: {p}")

        try:
            with p.open("r", encoding="utf-8") as f:
                first = f.readline()
        except OSError as exc:  # pragma: no cover - filesystem error path
            raise RuntimeError(f"Failed to open trajectory file: {p}") from exc

        if not first:
            raise ValueError(f"Trajectory JSONL file is empty: {p}")

        header_obj = json.loads(first)
        static_data = (
            header_obj.get("static_context")
            or header_obj.get("context")
            or {}
        )
        static_ctx = StaticContext(**static_data) if static_data else None

        mode = "full"
        try:
            with p.open("r", encoding="utf-8") as f2:
                _ = f2.readline()
                for line in f2:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    rec_type = obj.get("type")
                    if rec_type in {"summary", "final_snapshot"}:
                        mode = "summary"
                        break
                    snap_data = obj.get("snapshot")
                    if snap_data is not None:
                        mode = "full"
                        break
        except Exception:
            mode = "full"

        traj = cls(
            steps=[],
            scenario_id=getattr(static_ctx, "scenario_id", None) if static_ctx else None,
            seed=getattr(static_ctx, "seed", None) if static_ctx else None,
            config={},
            static_context=static_ctx,
        )
        traj._file_path = p
        traj._mode = mode
        return traj
