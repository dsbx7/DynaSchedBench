"""Base classes for converting DynaSchedBench events into algorithm inputs."""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from pathlib import Path
from dataclasses import dataclass
import json


@dataclass
class AdapterConfig:
    """Configuration for a scheduler adapter."""
    algorithm_name: str
    support_dynamic_events: bool = True
    support_flexible_routing: bool = True
    support_machine_breakdown: bool = True
    support_priority_change: bool = False
    support_route_change: bool = False
    max_jobs: Optional[int] = None
    max_machines: Optional[int] = None
    default_unavailable_time: float = 1e6  # Default marker for unavailable machines.


class BaseAdapter(ABC):
    """Base class for algorithm-specific event adapters."""
    
    def __init__(self, config: AdapterConfig):
        self.config = config
        self.events: List[Dict[str, Any]] = []
        self.machines: Dict[str, Dict[str, Any]] = {}
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.machine_groups: Dict[str, List[str]] = {}
        
    def load_events(self, events_path: Path) -> None:
        """Load an events.jsonl file into memory."""
        self.events = []
        with open(events_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    event = json.loads(line)
                    self.events.append(event)
        
        # Extract machine and job metadata from the event stream.
        self._extract_metadata()
    
    def _extract_metadata(self) -> None:
        """Extract machine groups and job metadata from loaded events."""
        for event in self.events:
            if event['event_type'] == 'ARRIVAL':
                job_id = event['job_id']
                self.jobs[job_id] = {
                    'job_id': job_id,
                    'family': event['job_family'],
                    'routing': event['routing'],
                    'process_times': event['process_times'],
                    'arrival_time': event['time']
                }
                
                for group in event['routing']:
                    if group not in self.machine_groups:
                        self.machine_groups[group] = []
    
    @abstractmethod
    def to_algorithm_format(self) -> Any:
        """Convert loaded events to an algorithm-specific input format.
        
        Returns:
            Data structure required by the target algorithm, such as a dict,
            NumPy array, or custom object.
        """
        pass
    
    @abstractmethod
    def from_algorithm_output(self, output: Any) -> Dict[str, Any]:
        """Convert algorithm output to the standard DynaSchedBench format.
        
        Args:
            output: Raw algorithm output.
            
        Returns:
            Standardized scheduling result with ``gantt`` data, ``makespan``,
            and additional ``metrics``.
        """
        pass
    
    def validate_events(self) -> List[str]:
        """Validate loaded event data for completeness and compatibility.
        
        Returns:
            List of error and warning messages.
        """
        issues = []
        
        arrival_events = [e for e in self.events if e['event_type'] == 'ARRIVAL']
        if not arrival_events:
            issues.append("ERROR: No ARRIVAL events found")
        
        if self.config.max_jobs and len(self.jobs) > self.config.max_jobs:
            issues.append(f"WARNING: Number of jobs ({len(self.jobs)}) exceeds max_jobs ({self.config.max_jobs})")
        
        if not self.config.support_dynamic_events:
            dynamic_event_types = {'BREAKDOWN', 'PTIME_CHANGE', 'PRIORITY_CHANGE', 
                                   'ORDER_CANCELLATION', 'ROUTE_CHANGE'}
            found_dynamic = set(e['event_type'] for e in self.events) & dynamic_event_types
            if found_dynamic:
                issues.append(f"WARNING: Algorithm does not support dynamic events: {found_dynamic}")
        
        return issues
    
    def get_event_summary(self) -> Dict[str, Any]:
        """Return summary statistics for the loaded event stream."""
        event_counts = {}
        for event in self.events:
            event_type = event['event_type']
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
        
        return {
            'total_events': len(self.events),
            'event_counts': event_counts,
            'num_jobs': len(self.jobs),
            'num_machine_groups': len(self.machine_groups),
            'time_range': (
                min(e['time'] for e in self.events) if self.events else 0,
                max(e['time'] for e in self.events) if self.events else 0
            )
        }
