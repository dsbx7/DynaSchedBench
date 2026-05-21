"""Output formatter for normalizing scheduler outputs."""

from typing import Dict, List, Any, Optional
import json
from pathlib import Path
import numpy as np


class OutputFormatter:
    """Convert outputs from different algorithms into a common structure.

    The standard result contains normalized Gantt records, a metrics dictionary,
    and a compact summary with completion counts and algorithm metadata.
    """
    
    def __init__(self, algorithm_name: str):
        self.algorithm_name = algorithm_name
    
    def format_gantt(self, 
                     gantt_data: List[Dict[str, Any]],
                     machine_id_mapping: Optional[Dict[int, str]] = None) -> List[Dict[str, Any]]:
        """Normalize Gantt-chart records.

        Args:
            gantt_data: Raw Gantt data.
            machine_id_mapping: Optional mapping from machine index to machine ID.

        Returns:
            Normalized Gantt data.
        """
        formatted = []
        
        for entry in gantt_data:
            formatted_entry = {
                'job_id': self._normalize_job_id(entry.get('job_id', entry.get('job'))),
                'operation': int(entry.get('operation', entry.get('op', 0))),
                'machine_id': self._normalize_machine_id(
                    entry.get('machine_id', entry.get('machine')),
                    machine_id_mapping
                ),
                'start_time': float(entry.get('start_time', entry.get('start', 0))),
                'end_time': float(entry.get('end_time', entry.get('end', 0))),
                'status': entry.get('status', 'completed')
            }
            formatted.append(formatted_entry)
        
        formatted.sort(key=lambda x: x['start_time'])
        
        return formatted
    
    def format_metrics(self,
                      gantt_data: List[Dict[str, Any]],
                      jobs_info: Optional[Dict[str, Dict]] = None,
                      all_events: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Compute performance metrics from normalized Gantt data.

        Args:
            gantt_data: Normalized Gantt records.
            jobs_info: Job metadata including arrival times and due dates.

        Returns:
            Performance-metric dictionary.
        """
        if not gantt_data:
            return self._empty_metrics()
        
        completed_ops = [op for op in gantt_data if op['status'] == 'completed']
        makespan = max(op['end_time'] for op in completed_ops) if completed_ops else 0.0
        
        job_completion_times = {}
        for op in completed_ops:
            job_id = op['job_id']
            if job_id not in job_completion_times:
                job_completion_times[job_id] = op['end_time']
            else:
                job_completion_times[job_id] = max(job_completion_times[job_id], op['end_time'])
        
        total_tardiness = 0.0
        max_tardiness = 0.0
        num_tardy_jobs = 0
        flowtimes = []
        
        if jobs_info:
            for job_id, completion_time in job_completion_times.items():
                if job_id in jobs_info:
                    arrival_time = jobs_info[job_id].get('arrival_time', 0)
                    due_date = jobs_info[job_id].get('due_date')
                    
                    # Flowtime
                    flowtime = completion_time - arrival_time
                    flowtimes.append(flowtime)
                    
                    # Tardiness
                    if due_date is not None:
                        tardiness = max(0, completion_time - due_date)
                        total_tardiness += tardiness
                        max_tardiness = max(max_tardiness, tardiness)
                        if tardiness > 0:
                            num_tardy_jobs += 1
        
        machine_utilization = self._calculate_utilization(gantt_data, makespan)
        
        all_jobs = set(op['job_id'] for op in gantt_data)
        completed_jobs = set(job_completion_times.keys())
        cancelled_ops = [op for op in gantt_data if op['status'] == 'cancelled']
        cancelled_jobs = set(op['job_id'] for op in cancelled_ops)
        
        metrics = {
            'makespan': round(makespan, 4),
            'total_tardiness': round(total_tardiness, 4),
            'mean_tardiness': round(total_tardiness / len(completed_jobs), 4) if completed_jobs else 0.0,
            'max_tardiness': round(max_tardiness, 4),
            'num_tardy_jobs': num_tardy_jobs,
            'mean_flowtime': round(np.mean(flowtimes), 4) if flowtimes else 0.0,
            'max_flowtime': round(max(flowtimes), 4) if flowtimes else 0.0,
            'machine_utilization': machine_utilization,
            'mean_utilization': round(np.mean(list(machine_utilization.values())), 4) if machine_utilization else 0.0,
            'jobs_completed': len(completed_jobs),
            'jobs_cancelled': len(cancelled_jobs),
            'jobs_total': len(all_jobs),
        }

        if jobs_info:
            earliness = []
            lateness = []  # signed lateness = completion - due_date
            tardiness_list = []  # non-negative
            flow_pcts = []
            tardy_flags = []
            job_proc_sum: Dict[str, float] = {}
            for op in completed_ops:
                job_proc_sum[op['job_id']] = job_proc_sum.get(op['job_id'], 0.0) + (op['end_time'] - op['start_time'])
            for job_id, completion_time in job_completion_times.items():
                if job_id in jobs_info:
                    arr = jobs_info[job_id].get('arrival_time', 0.0)
                    due = jobs_info[job_id].get('due_date', None)
                    ft = completion_time - arr
                    flow_pcts.append(ft)
                    if due is not None:
                        lt = completion_time - float(due)
                        lateness.append(lt)
                        td = max(0.0, lt)
                        tardiness_list.append(td)
                        e = max(0.0, float(due) - completion_time)
                        earliness.append(e)
                        tardy_flags.append(1 if td > 0 else 0)
            if tardiness_list:
                metrics['tardiness_p50'] = float(np.percentile(np.array(tardiness_list), 50))
                metrics['tardiness_p95'] = float(np.percentile(np.array(tardiness_list), 95))
                metrics['on_time_rate'] = 1.0 - (sum(tardy_flags) / len(tardy_flags)) if tardy_flags else 0.0
                metrics['mean_earliness'] = float(np.mean(earliness)) if earliness else 0.0
                metrics['mean_lateness'] = float(np.mean(lateness)) if lateness else 0.0
            if flow_pcts:
                metrics['flowtime_p50'] = float(np.percentile(np.array(flow_pcts), 50))
                metrics['flowtime_p95'] = float(np.percentile(np.array(flow_pcts), 95))
            waits = []
            for job_id, completion_time in job_completion_times.items():
                if job_id in jobs_info and job_id in job_proc_sum:
                    arr = jobs_info[job_id].get('arrival_time', 0.0)
                    waits.append(max(0.0, (completion_time - arr) - job_proc_sum[job_id]))
            metrics['mean_wait_time'] = float(np.mean(waits)) if waits else 0.0

        metrics['throughput_rate'] = float(metrics['jobs_completed'] / makespan) if makespan > 0 else 0.0

        metrics['rho_global_realized'] = metrics.get('mean_utilization', 0.0)
        metrics['rho_bottleneck_realized'] = float(max(machine_utilization.values())) if machine_utilization else 0.0

        if jobs_info:
            arrivals = sorted([float(info.get('arrival_time', 0.0)) for info in jobs_info.values()])
            if len(arrivals) >= 2:
                inter = np.diff(np.array(arrivals, dtype=np.float64))
                mu = float(np.mean(inter)) if inter.size > 0 else 0.0
                var = float(np.var(inter)) if inter.size > 0 else 0.0
                metrics['scv_a_realized'] = (var / (mu * mu)) if mu > 0 else 0.0
            else:
                metrics['scv_a_realized'] = 0.0
            ptimes = []
            for info in jobs_info.values():
                ptimes.extend([float(x) for x in info.get('process_times', [])])
            if ptimes:
                arr_pt = np.array(ptimes, dtype=np.float64)
                mu = float(np.mean(arr_pt))
                var = float(np.var(arr_pt))
                metrics['scv_p_realized'] = (var / (mu * mu)) if mu > 0 else 0.0
            else:
                metrics['scv_p_realized'] = 0.0
            # ddt_realized
            ddt_vals = []
            for job_id, info in jobs_info.items():
                due = info.get('due_date', None)
                if due is not None and job_id in job_completion_times:
                    arr = float(info.get('arrival_time', 0.0))
                    denom = float(sum(info.get('process_times', []) )) or 1.0
                    ddt_vals.append( (float(due) - arr) / denom )
            metrics['ddt_realized'] = float(np.mean(ddt_vals)) if ddt_vals else 0.0

        horizon_est = makespan
        if all_events:
            try:
                last_ev_t = max(float(e.get('time', 0.0)) for e in all_events)
                horizon_est = max(horizon_est, last_ev_t)
            except Exception:
                pass
            bd = [float(e.get('duration', 0.0)) for e in all_events if e.get('event_type') == 'BREAKDOWN']
            total_bd = float(sum(bd)) if bd else 0.0
            metrics['disturbance_realized'] = float(total_bd / horizon_est) if horizon_est > 0 else 0.0
        else:
            metrics['disturbance_realized'] = 0.0
        if machine_utilization:
            util_arr = np.array(list(machine_utilization.values()), dtype=np.float64)
            mu = float(np.mean(util_arr))
            sd = float(np.std(util_arr))
            metrics['load_cv_realized'] = (sd / mu) if mu > 0 else 0.0
        else:
            metrics['load_cv_realized'] = 0.0

        return metrics
    
    def _calculate_utilization(self, gantt_data: List[Dict], makespan: float) -> Dict[str, float]:
        """Compute utilization for each machine."""
        machine_busy_time = {}
        
        for op in gantt_data:
            if op['status'] == 'completed':
                machine_id = op['machine_id']
                duration = op['end_time'] - op['start_time']
                machine_busy_time[machine_id] = machine_busy_time.get(machine_id, 0) + duration
        
        if makespan == 0:
            return {m: 0.0 for m in machine_busy_time.keys()}
        
        return {
            machine_id: round(busy_time / makespan, 4)
            for machine_id, busy_time in machine_busy_time.items()
        }
    
    def _normalize_job_id(self, job_id: Any) -> str:
        """Normalize a job ID to string format."""
        if isinstance(job_id, str):
            return job_id
        elif isinstance(job_id, (int, float)):
            return f"Job-{int(job_id)}"
        else:
            return str(job_id)
    
    def _normalize_machine_id(self, machine_id: Any, mapping: Optional[Dict] = None) -> str:
        """Normalize a machine ID."""
        if mapping and isinstance(machine_id, int):
            return mapping.get(machine_id, f"M{machine_id}")
        elif isinstance(machine_id, str):
            return machine_id
        elif isinstance(machine_id, (int, float)):
            return f"M{int(machine_id)}"
        else:
            return str(machine_id)
    
    def _empty_metrics(self) -> Dict[str, Any]:
        """Return empty metrics for cases with no valid data."""
        return {
            'makespan': 0.0,
            'total_tardiness': 0.0,
            'mean_tardiness': 0.0,
            'max_tardiness': 0.0,
            'num_tardy_jobs': 0,
            'mean_flowtime': 0.0,
            'max_flowtime': 0.0,
            'machine_utilization': {},
            'mean_utilization': 0.0,
            'jobs_completed': 0,
            'jobs_cancelled': 0,
            'jobs_total': 0,
        }
    
    def save_output(self, 
                   gantt_data: List[Dict],
                   metrics: Dict[str, Any],
                   output_path: Path,
                   format: str = 'json') -> None:
        """Save formatted output to disk.

        Args:
            gantt_data: Gantt records.
            metrics: Performance metrics.
            output_path: Output file path.
            format: Output format, either 'json' or 'jsonl'.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        output = {
            'algorithm': self.algorithm_name,
            'gantt': gantt_data,
            'metrics': metrics,
            'summary': {
                'jobs_completed': metrics.get('jobs_completed', 0),
                'jobs_cancelled': metrics.get('jobs_cancelled', 0),
                'total_operations': len(gantt_data),
                'makespan': metrics.get('makespan', 0),
            }
        }
        
        if format == 'jsonl':
            with open(output_path, 'w') as f:
                for op in gantt_data:
                    f.write(json.dumps(op) + '\n')
                f.write(json.dumps({'metrics': metrics}) + '\n')
        else:
            with open(output_path, 'w') as f:
                json.dump(output, f, indent=2)


def format_gantt(gantt_data: List[Dict], 
                 algorithm_name: str = "unknown",
                 machine_id_mapping: Optional[Dict] = None) -> List[Dict]:
    """Convenience wrapper for formatting Gantt data."""
    formatter = OutputFormatter(algorithm_name)
    return formatter.format_gantt(gantt_data, machine_id_mapping)


def format_metrics(gantt_data: List[Dict],
                  jobs_info: Optional[Dict] = None,
                  algorithm_name: str = "unknown",
                  all_events: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Convenience wrapper for computing performance metrics."""
    formatter = OutputFormatter(algorithm_name)
    return formatter.format_metrics(gantt_data, jobs_info, all_events=all_events)
