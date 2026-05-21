"""Parse and index DynaSchedBench events.jsonl files."""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
import numpy as np


class EventsParser:
    """Parse an events.jsonl file and provide query and conversion helpers."""
    
    def __init__(self, events_path: Optional[Path] = None):
        self.events: List[Dict[str, Any]] = []
        self.events_by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.events_by_job: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.timeline: List[Tuple[float, Dict[str, Any]]] = []
        
        if events_path:
            self.load(events_path)
    
    def load(self, events_path: Path) -> None:
        """Load and index an events.jsonl file."""
        self.events = []
        self.events_by_type = defaultdict(list)
        self.events_by_job = defaultdict(list)
        
        with open(events_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    event = json.loads(line)
                    self.events.append(event)
                    
                    self.events_by_type[event['event_type']].append(event)
                    
                    if 'job_id' in event:
                        self.events_by_job[event['job_id']].append(event)
        
        self.timeline = sorted(
            [(e['time'], e) for e in self.events],
            key=lambda x: x[0]
        )
    
    def get_jobs_info(self) -> Dict[str, Dict[str, Any]]:
        """Extract information for all jobs.

        Returns:
            Mapping from job ID to family, routing, processing times, arrival
            time, and due date.
        """
        jobs_info = {}
        
        for event in self.events_by_type['ARRIVAL']:
            job_id = event['job_id']
            jobs_info[job_id] = {
                'job_id': job_id,
                'family': event['job_family'],
                'routing': event['routing'],
                'process_times': event['process_times'],
                'arrival_time': event['time'],
                'due_date': None
            }
        
        for event in self.events_by_type.get('DUE_DATE_SET', []):
            job_id = event['job_id']
            if job_id in jobs_info:
                jobs_info[job_id]['due_date'] = event['due_date']
        
        return jobs_info
    
    def get_machine_groups(self) -> Dict[str, List[str]]:
        """Infer machine-group information from routing data.

        Returns:
            Mapping from group name to machine IDs when available. Concrete
            machine IDs may need to come from another source.
        """
        groups = defaultdict(set)
        
        for event in self.events_by_type['ARRIVAL']:
            for group in event['routing']:
                groups[group].add(group)
        
        return {k: list(v) for k, v in groups.items()}
    
    def get_dynamic_events(self) -> List[Dict[str, Any]]:
        """Return all dynamic events, excluding ARRIVAL and DUE_DATE_SET."""
        static_types = {'ARRIVAL', 'DUE_DATE_SET'}
        return [e for e in self.events if e['event_type'] not in static_types]
    
    def get_events_in_window(self, start_time: float, end_time: float) -> List[Dict[str, Any]]:
        """Return events inside a specific time window."""
        return [e for e in self.events if start_time <= e['time'] <= end_time]
    
    def build_operation_matrix(self, jobs_info: Optional[Dict[str, Dict]] = None) -> Tuple[np.ndarray, List[str]]:
        """Build an operation matrix for algorithms that require tensor inputs.

        Returns:
            ``(process_time_matrix, job_ids)`` where the matrix shape is
            ``(num_jobs, max_ops, num_machine_groups)``.
        """
        if jobs_info is None:
            jobs_info = self.get_jobs_info()
        
        if not jobs_info:
            return np.array([]), []
        
        job_ids = sorted(jobs_info.keys())
        max_ops = max(len(info['routing']) for info in jobs_info.values())
        
        all_groups = set()
        for info in jobs_info.values():
            all_groups.update(info['routing'])
        group_to_idx = {g: i for i, g in enumerate(sorted(all_groups))}
        num_groups = len(all_groups)
        
        matrix = np.full((len(job_ids), max_ops, num_groups), fill_value=1e6, dtype=np.float32)
        
        for job_idx, job_id in enumerate(job_ids):
            info = jobs_info[job_id]
            for op_idx, (group, ptime) in enumerate(zip(info['routing'], info['process_times'])):
                group_idx = group_to_idx[group]
                matrix[job_idx, op_idx, group_idx] = ptime
        
        return matrix, job_ids
    
    def to_jsonl_events_format(self, output_path: Path) -> None:
        """Write parsed events back to JSONL for debugging."""
        with open(output_path, 'w') as f:
            for event in self.events:
                f.write(json.dumps(event) + '\n')
    
    def get_statistics(self) -> Dict[str, Any]:
        """Return event statistics."""
        jobs_info = self.get_jobs_info()
        
        ops_counts = [len(info['routing']) for info in jobs_info.values()]
        
        all_ptimes = []
        for info in jobs_info.values():
            all_ptimes.extend(info['process_times'])
        
        event_counts = {
            event_type: len(events) 
            for event_type, events in self.events_by_type.items()
        }
        
        return {
            'total_events': len(self.events),
            'event_counts': event_counts,
            'num_jobs': len(jobs_info),
            'operations': {
                'total': sum(ops_counts),
                'mean': np.mean(ops_counts) if ops_counts else 0,
                'min': min(ops_counts) if ops_counts else 0,
                'max': max(ops_counts) if ops_counts else 0,
            },
            'process_times': {
                'mean': np.mean(all_ptimes) if all_ptimes else 0,
                'std': np.std(all_ptimes) if all_ptimes else 0,
                'min': min(all_ptimes) if all_ptimes else 0,
                'max': max(all_ptimes) if all_ptimes else 0,
            },
            'time_span': (
                min(e['time'] for e in self.events) if self.events else 0,
                max(e['time'] for e in self.events) if self.events else 0
            )
        }


def parse_events_jsonl(events_path: Path) -> EventsParser:
    """Parse an events.jsonl file.

    Args:
        events_path: Path to an events.jsonl file.

    Returns:
        ``EventsParser`` instance.
    """
    parser = EventsParser(events_path)
    return parser
