import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any
import pandas as pd
import numpy as np
from jinja2 import Environment

from ..models.events import Event
from ..models.metrics import FinalReportData
from .report_templates import REPORT_MD_TEMPLATE

def _round_floats_in_dict(d: Any, precision: int = 4) -> Any:
    """Recursively rounds float values in a dictionary or list."""
    if isinstance(d, dict):
        return {k: _round_floats_in_dict(v, precision) for k, v in d.items()}
    if isinstance(d, list):
        return [_round_floats_in_dict(i, precision) for i in d]
    if isinstance(d, (float, np.floating)):
        return round(d, precision)
    return d

class Exporter:
    """Handles writing all output artifacts to disk."""

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.output_path.mkdir(parents=True, exist_ok=True)

    def write_events(self, events: List[Event]) -> None:
        path = self.output_path / "events.jsonl"
        with open(path, "w") as f:
            for event in events:
                f.write(event.model_dump_json() + "\n")

    def write_static_jobs(self, static_jobs: Dict[str, Any]) -> None:
        path = self.output_path / "static_jobs.json"
        with open(path, "w") as f:
            json.dump(static_jobs, f, indent=2)

    def write_static_machines(self, machines: List[Any]) -> None:
        """Write a snapshot of the machine list to static_machines.json.

        The input can be either a list of Pydantic models (with ``model_dump``)
        or a list of plain dictionaries. This keeps the exporter decoupled from
        the concrete InputModel types while still emitting a stable JSON
        structure that other components (e.g. simulators) can consume.
        """

        path = self.output_path / "static_machines.json"
        payload_machines: List[Dict[str, Any]] = []
        for m in machines:
            if hasattr(m, "model_dump"):
                payload_machines.append(m.model_dump())  # type: ignore[call-arg]
            else:
                # Fallback: assume it is already a mapping-like object
                payload_machines.append(dict(m))

        with open(path, "w") as f:
            json.dump({"machines": payload_machines}, f, indent=2)

    def write_trace(self, trace_df: pd.DataFrame) -> None:
        _ = trace_df
        return

    def write_meta(self, input_model_str: str, version: str, seed_map: Dict[str, int]) -> str:
        path = self.output_path / "meta.json"
        input_hash = hashlib.sha256(input_model_str.encode()).hexdigest()
        meta = { "input_hash": input_hash, "dynaschedbench_version": version, "seed_map": seed_map }
        with open(path, "w") as f:
            json.dump(meta, f, indent=2)
        return input_hash

    def write_final_metrics(self, final_metrics: Dict[str, Any]) -> None:
        """Writes the final computed metrics, with rounded floats, to a JSON file."""
        path = self.output_path / "final_metrics.json"
        
        # Convert numpy types to native Python types first
        metrics_native = {k: v.item() if hasattr(v, 'item') else v for k, v in final_metrics.items()}
        
        # --- 👇 Apply recursive rounding ---
        metrics_rounded = _round_floats_in_dict(metrics_native)
        
        with open(path, "w") as f:
            json.dump(metrics_rounded, f, indent=2)

    def write_report(self, report_data: FinalReportData) -> None:
        path = self.output_path / "report.md"
        env = Environment()
        template = env.from_string(REPORT_MD_TEMPLATE)
        rendered_report = template.render(report_data.model_dump())
        with open(path, "w") as f:
            f.write(rendered_report)
