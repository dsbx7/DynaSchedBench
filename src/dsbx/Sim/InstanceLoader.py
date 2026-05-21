"""Simplified loader that finds and loads input.json alongside events.jsonl.

For PDR and other algorithms, we need both events and the InputModel.
This module provides a simple way to load them together.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

from loguru import logger

from dsbx.Gen import InputModel, load_input_model
from dsbx.Sim.Events import (
    Event, ArrivalEvent, DueDateEvent, BreakdownEvent, PriorityChangeEvent,
    OrderCancellationEvent, MachineRepairCompletionEvent, ProcessTimeChangeEvent,
    PreventiveMaintenanceEvent, RouteChangeEvent, DueDateChangeEvent,
)


EVENT_TYPE_MAP = {
    "ARRIVAL": ArrivalEvent,
    "DUE_DATE_SET": DueDateEvent,
    "BREAKDOWN": BreakdownEvent,
    "PRIORITY_CHANGE": PriorityChangeEvent,
    "ORDER_CANCELLATION": OrderCancellationEvent,
    "REPAIR_COMPLETION": MachineRepairCompletionEvent,
    "PTIME_CHANGE": ProcessTimeChangeEvent,
    "PREVENTIVE_MAINTENANCE": PreventiveMaintenanceEvent,
    "ROUTE_CHANGE": RouteChangeEvent,
    "DUE_DATE_CHANGE": DueDateChangeEvent,
}


def load_events_from_jsonl(events_file: Path) -> List[Event]:
    """Load all events from an events.jsonl file.
    
    Args:
        events_file: Path to events.jsonl file
        
    Returns:
        List of Event objects, sorted by time
    """
    events: List[Event] = []
    
    with open(events_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            
            try:
                event_dict = json.loads(line)
                event_type = event_dict.get("event_type")
                model_cls = EVENT_TYPE_MAP.get(event_type)
                
                if model_cls is None:
                    logger.warning(f"Unknown event type '{event_type}' at line {line_num}")
                    continue
                
                # Use Pydantic to parse and validate
                event = model_cls(**event_dict)
                events.append(event)
            except Exception as e:
                logger.warning(f"Failed to parse event at line {line_num}: {e}")
                continue
    
    # Sort by time
    events.sort(key=lambda e: e.time)
    
    logger.info(f"Loaded {len(events)} events from {events_file}")
    return events


def load_instance_from_directory(run_dir: Path) -> Tuple[InputModel, List[Event]]:
    """Load InputModel and events from a run directory.
    
    Looks for input.json and events.jsonl in the given directory.
    
    Args:
        run_dir: Path to the run directory (e.g., runs/cold_start/my_instance)
        
    Returns:
        Tuple of (InputModel, events list)
        
    Example:
        >>> model, events = load_instance_from_directory(Path("runs/cold_start/my_instance"))
        >>> from dsbx.Sim import DynaSchedSim
        >>> sim = DynaSchedSim(model, events)
        >>> snapshot = sim.reset()
    """
    run_dir = Path(run_dir).resolve()
    
    # Look for input.json
    input_file = run_dir / "input.json"
    if not input_file.exists():
        raise FileNotFoundError(f"input.json not found in {run_dir}")
    
    # Look for events.jsonl
    events_file = run_dir / "events.jsonl"
    if not events_file.exists():
        raise FileNotFoundError(f"events.jsonl not found in {run_dir}")
    
    # Load both
    model = load_input_model(input_file)
    events = load_events_from_jsonl(events_file)
    
    logger.info(f"Loaded instance from {run_dir}: {model.scale.n_jobs} jobs, {len(events)} events")
    
    return model, events


def find_instance_directory(events_file: Path) -> Path:
    """Find the run directory containing an events.jsonl file.
    
    Args:
        events_file: Path to events.jsonl (can be absolute or relative)
        
    Returns:
        Path to the directory containing events.jsonl
    """
    events_file = Path(events_file).resolve()
    if not events_file.exists():
        raise FileNotFoundError(f"events.jsonl not found: {events_file}")
    
    return events_file.parent
