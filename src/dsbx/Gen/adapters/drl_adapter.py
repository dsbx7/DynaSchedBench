"""Deep-RL adapter for converting events.jsonl into common training inputs.

The adapter targets DQN-style, PPO-style, and multi-agent DRL schedulers by
producing shared state, action-space, reward, and dynamic-event structures."""

from typing import Dict, List, Any, Optional, Tuple
import numpy as np
from pathlib import Path
import json

from .base_adapter import BaseAdapter, AdapterConfig
from .events_parser import EventsParser


class DRLAdapter(BaseAdapter):
    """Generic adapter for deep reinforcement learning schedulers.

    The output contains state tensors, action-space metadata, reward parameters,
    and a dynamic-event queue in a format commonly used by DRL algorithms.
    """
    
    def __init__(self, config: AdapterConfig):
        super().__init__(config)
        self.parser = EventsParser()
        self.num_machines: int = 0
        self.num_jobs: int = 0
        self.max_operations: int = 0
        
    def load_events(self, events_path: Path) -> None:
        """Load and parse an events.jsonl file."""
        super().load_events(events_path)
        self.parser.load(events_path)
        
        jobs_info = self.parser.get_jobs_info()
        self.num_jobs = len(jobs_info)
        self.max_operations = max(len(info['routing']) for info in jobs_info.values()) if jobs_info else 0
        
    def to_algorithm_format(self) -> Dict[str, Any]:
        """Convert events to the generic DRL input format.

        Returns:
            Dictionary with static information, initial state, dynamic-event
            queue, and configuration parameters.
        """
        jobs_info = self.parser.get_jobs_info()
        
        static_info = self._build_static_info(jobs_info)
        
        initial_state = self._build_initial_state(jobs_info)
        
        dynamic_events = self._build_dynamic_events()
        
        config = {
            'num_jobs': self.num_jobs,
            'num_machines': self.num_machines,
            'max_operations': self.max_operations,
            'horizon': max(e['time'] for e in self.events) if self.events else 1000,
        }
        
        return {
            'static_info': static_info,
            'initial_state': initial_state,
            'dynamic_events': dynamic_events,
            'config': config
        }
    
    def _build_static_info(self, jobs_info: Dict[str, Dict]) -> Dict[str, Any]:
        """Build static job, route, and processing-time information.

        The returned structure is intentionally generic so multiple DRL
        algorithms can consume it.
        """
        all_groups = set()
        for info in jobs_info.values():
            all_groups.update(info['routing'])
        
        group_to_machine_ids = {}
        machine_id = 0
        for group in sorted(all_groups):
            group_to_machine_ids[group] = [machine_id]
            machine_id += 1
        
        self.num_machines = machine_id
        
        job_ids = sorted(jobs_info.keys())
        process_time_matrix = np.full(
            (self.num_jobs, self.max_operations, self.num_machines),
            fill_value=self.config.default_unavailable_time,
            dtype=np.float32
        )
        
        candidates = {}  # (job, op) -> [machine_ids]
        
        for job_idx, job_id in enumerate(job_ids):
            info = jobs_info[job_id]
            for op_idx, (group, ptime) in enumerate(zip(info['routing'], info['process_times'])):
                machine_ids = group_to_machine_ids.get(group, [])
                candidates[(job_idx, op_idx)] = machine_ids
                
                for machine_id in machine_ids:
                    process_time_matrix[job_idx, op_idx, machine_id] = ptime
        
        routing_matrix = np.full(
            (self.num_jobs, self.max_operations),
            fill_value=-1,
            dtype=np.int32
        )
        
        for job_idx, job_id in enumerate(job_ids):
            info = jobs_info[job_id]
            for op_idx, group in enumerate(info['routing']):
                machine_ids = group_to_machine_ids.get(group, [])
                if machine_ids:
                    routing_matrix[job_idx, op_idx] = machine_ids[0]
        
        return {
            'num_jobs': self.num_jobs,
            'num_machines': self.num_machines,
            'num_operations': [len(jobs_info[jid]['routing']) for jid in job_ids],
            'process_time_matrix': process_time_matrix.tolist(),
            'routing_matrix': routing_matrix.tolist(),
            'candidates': {f"({j},{o})": machines for (j, o), machines in candidates.items()},
            'job_ids': job_ids,
            'group_to_machines': group_to_machine_ids,
        }
    
    def _build_initial_state(self, jobs_info: Dict[str, Dict]) -> Dict[str, Any]:
        """Build the initial environment state."""
        job_ids = sorted(jobs_info.keys())
        
        arrival_times = np.array([
            jobs_info[jid]['arrival_time'] for jid in job_ids
        ], dtype=np.float32)
        
        due_dates = np.array([
            jobs_info[jid].get('due_date', 1e6) for jid in job_ids
        ], dtype=np.float32)
        
        job_progress = np.zeros(self.num_jobs, dtype=np.int32)
        
        machine_available_time = np.zeros(self.num_machines, dtype=np.float32)
        
        return {
            'arrival_times': arrival_times.tolist(),
            'due_dates': due_dates.tolist(),
            'job_progress': job_progress.tolist(),
            'machine_available_time': machine_available_time.tolist(),
            'current_time': 0.0,
        }
    
    def _build_dynamic_events(self) -> List[Dict[str, Any]]:
        """Extract and format dynamic events."""
        dynamic_events = []
        
        for event in self.parser.get_dynamic_events():
            event_type = event['event_type']
            
            formatted_event = {
                'time': event['time'],
                'type': event_type,
            }
            
            if event_type == 'BREAKDOWN':
                formatted_event.update({
                    'machine_id': event['machine_id'],
                    'duration': event['duration']
                })
            elif event_type == 'PTIME_CHANGE':
                formatted_event.update({
                    'job_id': event['job_id'],
                    'step_index': event['step_index'],
                    'new_process_time': event['new_process_time']
                })
            elif event_type == 'PRIORITY_CHANGE':
                formatted_event.update({
                    'job_id': event['job_id'],
                    'new_priority': event['new_priority']
                })
            elif event_type == 'ORDER_CANCELLATION':
                formatted_event.update({
                    'job_id': event['job_id']
                })
            elif event_type == 'ROUTE_CHANGE':
                formatted_event.update({
                    'job_id': event['job_id'],
                    'new_routing': event['new_routing'],
                    'new_process_times': event['new_process_times'],
                    'from_step': event.get('from_step', 0)
                })
            
            dynamic_events.append(formatted_event)
        
        dynamic_events.sort(key=lambda x: x['time'])
        
        return dynamic_events
    
    def from_algorithm_output(self, output: Any) -> Dict[str, Any]:
        """Convert DRL algorithm output to the standard result format.

        Args:
            output: Raw DRL output, such as Gantt dictionaries, a dictionary
                containing schedule and metrics, or a scheduling matrix.
        """
        if isinstance(output, dict):
            if 'gantt' in output:
                gantt_data = output['gantt']
            elif 'schedule' in output:
                gantt_data = output['schedule']
            else:
                gantt_data = []
        elif isinstance(output, list):
            gantt_data = output
        else:
            gantt_data = self._parse_schedule_matrix(output)
        
        from .output_formatter import OutputFormatter
        formatter = OutputFormatter(self.config.algorithm_name)
        
        formatted_gantt = formatter.format_gantt(gantt_data)
        jobs_info = self.parser.get_jobs_info()
        metrics = formatter.format_metrics(formatted_gantt, jobs_info)
        
        return {
            'gantt': formatted_gantt,
            'metrics': metrics,
            'algorithm': self.config.algorithm_name
        }
    
    def _parse_schedule_matrix(self, matrix: np.ndarray) -> List[Dict[str, Any]]:
        """Parse Gantt data from a scheduling matrix used by some DRL algorithms."""
        gantt_data = []
        
        if len(matrix.shape) == 3 and matrix.shape[2] >= 3:
            for job_idx in range(matrix.shape[0]):
                for op_idx in range(matrix.shape[1]):
                    machine_id = int(matrix[job_idx, op_idx, 0])
                    start_time = float(matrix[job_idx, op_idx, 1])
                    end_time = float(matrix[job_idx, op_idx, 2])
                    
                    if machine_id >= 0 and start_time >= 0:
                        gantt_data.append({
                            'job_id': f"Job-{job_idx}",
                            'operation': op_idx,
                            'machine_id': f"M{machine_id}",
                            'start_time': start_time,
                            'end_time': end_time,
                            'status': 'completed'
                        })
        
        return gantt_data
    
    def save_for_training(self, output_path: Path, format: str = 'jsonl') -> None:
        """Save converted data in a training-data format for DRL algorithms.

        Args:
            output_path: Output path.
            format: Either 'jsonl' or 'numpy'.
        """
        data = self.to_algorithm_format()
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if format == 'jsonl':
            with open(output_path, 'w') as f:
                f.write(json.dumps({
                    'type': 'static_info',
                    'data': data['static_info']
                }) + '\n')
                
                for event in data['dynamic_events']:
                    f.write(json.dumps({
                        'type': 'event',
                        'data': event
                    }) + '\n')
        
        elif format == 'numpy':
            np.savez_compressed(
                output_path,
                process_times=np.array(data['static_info']['process_time_matrix']),
                routing=np.array(data['static_info']['routing_matrix']),
                arrivals=np.array(data['initial_state']['arrival_times']),
                due_dates=np.array(data['initial_state']['due_dates']),
            )
        
        else:
            with open(output_path, 'w') as f:
                json.dump(data, f, indent=2)


def create_drl_adapter(algorithm_name: str, 
                      support_dynamic: bool = True,
                      max_jobs: Optional[int] = None) -> DRLAdapter:
    """Create a DRL adapter with a compact convenience API.

    Args:
        algorithm_name: Algorithm name.
        support_dynamic: Whether dynamic events are supported.
        max_jobs: Optional maximum number of jobs.

    Returns:
        Configured ``DRLAdapter`` instance.
    """
    config = AdapterConfig(
        algorithm_name=algorithm_name,
        support_dynamic_events=support_dynamic,
        support_flexible_routing=True,
        support_machine_breakdown=support_dynamic,
        max_jobs=max_jobs
    )
    
    return DRLAdapter(config)
