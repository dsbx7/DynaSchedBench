import json
import os
import sys
from dataclasses import replace
from typing import List, Dict, Any

from .config import CognitiveConfig, InfoLevel, InteractionMode
from .feature_extractor import ObservationEncoder


SYSTEM_PROMPT_PREFIX = (
    "You are an expert production scheduler for dynamic job shops.\n"
    "You receive a compact table of candidate actions and must choose actions "
    "that balance short-term efficiency, long-term stability, and emergency responsiveness.\n"
    "Your high-level scheduling objectives are:\n"
    "- Keep overall completion time (makespan) and total/average flow time small.\n"
    "- Minimize tardy jobs and their total/weighted tardiness, and avoid unnecessary job cancellations.\n"
    "- Maintain high but well-balanced machine utilization, avoiding extreme queues or severely overloaded bottlenecks.\n"
    "- Avoid excessive rescheduling and large, unnecessary shifts of planned start times unless reacting to important disturbances.\n\n"
)

SYSTEM_PROMPT_TEMPLATE = (
    SYSTEM_PROMPT_PREFIX
    + "\n\nShop Profile:\n"
    + "{shop_profile}\n"
)

USER_PROMPT_TEMPLATE = (
    "Current State (Level {info_level}):\n"
    "{markdown_table}\n\n"
    "Instructions:\n"
    "{instructions}\n\n"
    "Output Format (JSON only):\n"
    "{output_format}\n"
)


def _render_markdown_table(headers: List[str], rows: List[List[str]]) -> str:
    if not headers:
        return ""
    n = len(headers)
    norm_rows: List[List[str]] = []
    for r in rows:
        cells = [str(c) for c in r]
        if len(cells) < n:
            cells = cells + [""] * (n - len(cells))
        elif len(cells) > n:
            cells = cells[:n]
        norm_rows.append(cells)
    widths: List[int] = []
    for j in range(n):
        col_values = [headers[j]] + [row[j] for row in norm_rows]
        widths.append(max(len(str(v)) for v in col_values))

    def _fmt_row(cells: List[str]) -> str:
        return "| " + " | ".join(str(cells[j]).ljust(widths[j]) for j in range(n)) + " |"

    header_line = _fmt_row([str(h) for h in headers])
    sep_line = "| " + " | ".join("-" * widths[j] for j in range(n)) + " |"
    data_lines = [_fmt_row(row) for row in norm_rows]
    return "\n".join([header_line, sep_line] + data_lines)


class FewShotBank:
    """Provide high-quality few-shot examples for each information level.

    The current implementation uses hard-coded examples for three information
    levels: basic operation data for SPT-style decisions, statistical queue and
    priority context, and structural bottleneck information with downstream
    machine availability.
    """

    def get_examples(self, info_level: InfoLevel, max_examples=None) -> str:
        k = max(0, int(max_examples)) if max_examples is not None else 1
        if k <= 0:
            return ""

        blocks: List[str] = []

        if info_level is InfoLevel.LEVEL_1_MYOPIC:
            headers = [
                "ActionID",
                "Job",
                "OpIdx",
                "Group",
                "Machine",
                "ProcTime",
                "MachineStatus",
                "AvailableFrom",
            ]
            rows = [
                ["1", "Job-1", "1", "G2", "G2-M1", "3.200", "BUSY", "8.000"],
                ["2", "Job-2", "0", "G1", "G1-M1", "1.500", "IDLE", "5.000"],
                ["3", "Job-3", "0", "G1", "G1-M2", "4.000", "IDLE", "5.000"],
            ]
            table = _render_markdown_table(headers, rows)
            text = (
                "### Example 1 (Myopic Scheduling)\n"
                f"{table}\n\n"
                "Reasoning: Focus only on the current machine status and processing time. "
                "Action 2 and 3 are both on idle machines from time 5.000, but Action 2 has much shorter ProcTime. "
                "Ignore long-term congestion or due dates.\n"
                "Chosen Action: ID=2 (shortest processing time on an immediately idle machine).\n"
            )
            blocks.append(text)

        elif info_level is InfoLevel.LEVEL_2_STATISTICAL:
            headers = [
                "ActionID",
                "Job",
                "OpIdx",
                "Group",
                "Machine",
                "ProcTime",
                "MachineStatus",
                "AvailableFrom",
                "QueueLen",
                "Priority",
                "Slack",
                "Progress",
            ]
            rows = [
                ["1", "Job-1", "1", "G2", "G2-M1", "3.000", "IDLE", "6.000", "6", "-1", "-1.0", "0.50"],
                ["2", "Job-2", "0", "G1", "G1-M1", "2.000", "IDLE", "6.000", "1", "0", "5.0", "0.20"],
                ["3", "Job-3", "0", "G1", "G1-M2", "1.500", "BUSY", "7.500", "4", "0", "2.0", "0.10"],
            ]
            table = _render_markdown_table(headers, rows)
            text = (
                "### Example 1 (Statistical Trade-offs)\n"
                f"{table}\n\n"
                "Reasoning: Use both local efficiency and statistics. Action 1 has negative slack and higher priority "
                "but sits behind a long queue (QueueLen=6). Action 2 has a much shorter queue and reasonable slack, "
                "and can also start at time 6.000.\n"
                "Chosen Action: ID=2 (balance urgency with shorter queue and stable slack).\n"
            )
            blocks.append(text)

        else:
            headers = [
                "ActionID",
                "Job",
                "OpIdx",
                "Group",
                "Machine",
                "ProcTime",
                "MachineStatus",
                "AvailableFrom",
                "QueueLen",
                "Priority",
                "Slack",
                "Progress",
                "BottleneckScore",
                "SystemUtilization",
                "NextGroupLoad",
            ]
            rows = [
                [
                    "1",
                    "Job-1",
                    "1",
                    "G2",
                    "G2-M1",
                    "4.000",
                    "IDLE",
                    "5.000",
                    "3",
                    "-1",
                    "-0.5",
                    "0.60",
                    "1.000",
                    "0.90",
                    "5",
                ],
                [
                    "2",
                    "Job-2",
                    "0",
                    "G1",
                    "G1-M1",
                    "2.500",
                    "IDLE",
                    "5.000",
                    "1",
                    "0",
                    "3.0",
                    "0.10",
                    "0.200",
                    "0.90",
                    "1",
                ],
                [
                    "3",
                    "Job-3",
                    "0",
                    "G3",
                    "G3-M1",
                    "3.000",
                    "BUSY",
                    "8.000",
                    "4",
                    "0",
                    "1.0",
                    "0.20",
                    "0.800",
                    "0.90",
                    "7",
                ],
            ]
            table = _render_markdown_table(headers, rows)
            text = (
                "### Example 1 (Structural Bottleneck Feeding)\n"
                f"{table}\n\n"
                "Reasoning: Although Action 1 has a longer processing time than Action 2, it feeds a structural "
                "bottleneck (BottleneckScore=1.000) under high system utilization (0.90) and moderate next-group load. "
                "Keeping the bottleneck busy is more important than greedily picking the shortest job.\n"
                "Chosen Action: ID=1 (feed the highly utilized bottleneck machine).\n"
            )
            blocks.append(text)

        if not blocks:
            return ""
        return "\n\n".join(blocks[:k])


def _get_few_shot_examples(info_level: InfoLevel, max_examples: int) -> str:
    k = max(0, int(max_examples))
    if k <= 0:
        return ""

    bank = FewShotBank()
    return bank.get_examples(info_level, k)


def _build_l3_table_column_guidance() -> str:
    """Return a textual description of each column in the LEVEL_3_STRUCTURAL table.

    The description is used in L3 mode so the LLM can interpret each column
    consistently.
    """

    return (
        "Column meanings for the LEVEL_3_STRUCTURAL table:\n"
        "- ActionID: the row index of a candidate action; you must always choose actions by this ID.\n"
        "- Job: the job identifier for the operation.\n"
        "- OpIdx: index of the operation within the job (0 = first operation).\n"
        "- Group: the machine group required by the current operation.\n"
        "- Machine: the specific machine candidate within that group.\n"
        "- ProcTime: processing time of this operation on the chosen machine.\n"
        "- MachineStatus: IDLE / BUSY / DOWN status of the target machine or all candidates in the group.\n"
        "- AvailableFrom: earliest time this machine or group can start a new operation (not earlier than the current time).\n"
        "- QueueLen: current queue length on the target machine or machine group.\n"
        "- Priority: -1 for emergency jobs and 0 for normal jobs (emergency jobs should not be starved).\n"
        "- Slack: due_date − current_time − remaining_work; negative slack means the job is already projected to be late. "
        "If a job has no due date, its Slack cell is left empty and you should ignore it when reasoning about tardiness.\n"
        "- Progress: fraction of operations that will have been completed for this job after finishing this operation "
        "(0–1, larger = closer to completion).\n"
        "- BottleneckScore: long-run utilization of this machine group, computed as total busy time of all machines in "
        "the group divided by the elapsed simulation time (higher values indicate a stronger structural bottleneck).\n"
        "- SystemUtilization: average utilization across all machines, i.e., the mean of each machine's busy_time "
        "divided by the elapsed simulation time (higher values mean the whole system is more heavily loaded).\n"
        "- NextGroupLoad: queue length on the job's next machine group, indicating future congestion after this operation.\n"
    )


def _build_o1_instructions(level: InfoLevel) -> str:
    if level is InfoLevel.LEVEL_1_MYOPIC:
        return (
            "Choose the single best operation–machine-group pair to schedule now. "
            "Focus on processing time and basic identifiers in the table. Use the 'Priority' column, "
            "where -1 indicates an emergency job and 0 indicates a normal job, and give emergency jobs "
            "higher priority unless this would cause severe starvation elsewhere. "
            "Whenever possible, prefer choices that help keep makespan and flow time small and "
            "avoid clearly unnecessary job cancellations or chaotic rescheduling."
        )
    if level is InfoLevel.LEVEL_2_STATISTICAL:
        return (
            "Choose the single best action, using processing time, remaining work, remaining operations, "
            "flexibility, priority, and group queue length in the table. "
            "Explicitly trade off these features to reduce expected makespan and tardiness, keep queues "
            "under control, and avoid unnecessary cancellations. Treat Priority=-1 as an emergency job "
            "and Priority=0 as a normal job when resolving ties."
        )
    return (
        "Choose the single best action, combining local efficiency (processing time, remaining work) with "
        "structural signals (queue lengths, next machine availability, bottleneck score) and emergency priority "
        "encoded as Priority=-1 for emergency jobs and 0 for normal jobs, so that makespan and tardiness remain low, "
        "machines stay well utilized but not overloaded, and unnecessary rescheduling or cancellations are avoided.\n\n"
        + _build_l3_table_column_guidance()
    )


_DEFAULT_COGNITIVE_CONFIG = CognitiveConfig()


def _build_system_block(shop_profile: str, info_level: InfoLevel) -> str:
    """Construct the system prompt, optionally omitting an empty Shop Profile for L1.

    When the agent is LEVEL_1_MYOPIC and there is no shop_profile content
    (empty or whitespace), we drop the "Shop Profile" section entirely so that
    the system prompt only contains the high-level role description. This keeps
    L1 agents myopic and avoids confusing empty headers in the logs.
    """

    sp = (shop_profile or "").strip()
    if info_level is InfoLevel.LEVEL_1_MYOPIC and not sp:
        return SYSTEM_PROMPT_PREFIX
    if not sp:
        return SYSTEM_PROMPT_PREFIX
    return SYSTEM_PROMPT_TEMPLATE.format(shop_profile=sp)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            body = parts[1].strip()
            return body or parts[2]
    return text


def _extract_json_payload(text: str) -> str:
    s1, e1 = text.find("{"), text.rfind("}")
    s2, e2 = text.find("["), text.rfind("]")
    if s1 != -1 and e1 != -1 and e1 > s1:
        return text[s1:e1 + 1]
    if s2 != -1 and e2 != -1 and e2 > s2:
        return text[s2:e2 + 1]
    return text


def _safe_json_loads(text: str):
    try:
        return json.loads(text)
    except Exception:
        try:
            t = _strip_code_fences(text)
            return json.loads(_extract_json_payload(t))
        except Exception:
            return None


def _is_non_empty(value: Any) -> bool:
    """Simple helper to filter out None/empty values when rendering metrics."""
    if value is None:
        return False
    if value == "":
        return False
    if value == []:
        return False
    return True


def _format_dynamic_summary(obs: Dict[str, Any], info_level: InfoLevel) -> str:
    summary = obs.get("dynamic_summary")
    if not isinstance(summary, dict) or not summary:
        return ""
    scenario = summary.get("scenario") or {}
    progress = summary.get("progress") or {}
    events = summary.get("events") or {}
    emergency_jobs = summary.get("emergency_jobs") or []
    down_machines = summary.get("down_machines") or []

    scenario_lines: List[str] = []
    progress_lines: List[str] = []
    critical_lines: List[str] = []

    # Level 3 (STRUCTURAL): full Bayesian view, including scenario priors
    scale_cfg = scenario.get("scale") or {}
    targets_cfg = scenario.get("targets") or {}
    dynamics_cfg = scenario.get("dynamics") or {}
    dyn_cfg = scenario.get("dynamic_scenarios") or {}

    # L3: curated Instance Metrics (priors and goals). L1/L2 do not see this block.
    if scenario and info_level is InfoLevel.LEVEL_3_STRUCTURAL:
        scenario_lines.append("# Instance Metrics")
        scenario_lines.append(
            "- Guidance: These parameters describe configured goals and event probabilities. "
            "Compare them with the Realized Statistics section to judge how mild or severe "
            "the dynamics have been so far."
        )

        # DynamicScenarios grouped by event family
        if isinstance(dyn_cfg, dict) and dyn_cfg:
            # Process-time changes
            ptime_keys = ["ptime_change_rate", "ptime_change_multiplier"]
            ptime_view = {k: v for k, v in dyn_cfg.items() if k in ptime_keys and _is_non_empty(v)}
            if ptime_view:
                scenario_lines.append("- Process-time change parameters:")
                for k in ptime_keys:
                    if k in ptime_view:
                        scenario_lines.append(f"  - {k}: {ptime_view[k]}")

            # Preventive maintenance
            pm_keys = ["pm_interval", "pm_duration_mean", "pm_duration_std"]
            pm_view = {k: v for k, v in dyn_cfg.items() if k in pm_keys and _is_non_empty(v)}
            if pm_view:
                scenario_lines.append("- Preventive maintenance parameters:")
                for k in pm_keys:
                    if k in pm_view:
                        scenario_lines.append(f"  - {k}: {pm_view[k]}")

            # Batch arrivals
            batch_keys = ["batch_arrival_probability", "batch_size_mean", "batch_size_std"]
            batch_view = {k: v for k, v in dyn_cfg.items() if k in batch_keys and _is_non_empty(v)}
            if batch_view:
                scenario_lines.append("- Batch arrival parameters:")
                for k in batch_keys:
                    if k in batch_view:
                        scenario_lines.append(f"  - {k}: {batch_view[k]}")

            # Route changes
            route_keys = ["route_change_probability"]
            route_view = {k: v for k, v in dyn_cfg.items() if k in route_keys and _is_non_empty(v)}
            if route_view:
                scenario_lines.append("- Route-change parameters:")
                for k in route_keys:
                    if k in route_view:
                        scenario_lines.append(f"  - {k}: {route_view[k]}")

            # Due-date changes
            dd_keys = [
                "due_date_change_probability",
                "due_date_tightening_ratio",
                "due_date_change_factor",
            ]
            dd_view = {k: v for k, v in dyn_cfg.items() if k in dd_keys and _is_non_empty(v)}
            if dd_view:
                scenario_lines.append("- Due-date change parameters:")
                for k in dd_keys:
                    if k in dd_view:
                        scenario_lines.append(f"  - {k}: {dd_view[k]}")

            # Other dynamic event probabilities (not tied to a single family above)
            other_dyn_keys = ["cancellation_rate", "priority_change_rate", "rework_probability"]
            other_view = {
                k: v
                for k, v in dyn_cfg.items()
                if k in other_dyn_keys and _is_non_empty(v)
            }
            if other_view:
                scenario_lines.append("- Other event probabilities:")
                for k in other_dyn_keys:
                    if k in other_view:
                        scenario_lines.append(f"  - {k}: {other_view[k]}")

        # Target priors and goals
        if isinstance(targets_cfg, dict) and targets_cfg:
            target_keys = [
                "rho_global",
                "rho_bottleneck",
                "disturbance",
                "ddt",
                "scv_a",
                "scv_p",
                "load_cv",
            ]
            targets_view = {
                k: v
                for k, v in targets_cfg.items()
                if k in target_keys and _is_non_empty(v)
            }
            if targets_view:
                scenario_lines.append("- Target parameters (objectives & priors):")
                for k in target_keys:
                    if k in targets_view:
                        scenario_lines.append(f"  - {k}: {targets_view[k]}")

        # Flow dynamics (arrival patterns)
        if isinstance(dynamics_cfg, dict) and dynamics_cfg:
            dyn_flow_keys = [
                "arrival_pattern",
                "arrival_amplitude",
                "arrival_period",
            ]
            dynamics_view = {
                k: v
                for k, v in dynamics_cfg.items()
                if k in dyn_flow_keys and _is_non_empty(v)
            }
            if dynamics_view:
                scenario_lines.append("- Flow dynamics:")
                for k in dyn_flow_keys:
                    if k in dynamics_view:
                        scenario_lines.append(f"  - {k}: {dynamics_view[k]}")

    # Level 2 (STATISTICAL) and Level 3 (STRUCTURAL): runtime stats and realized events
    if progress and info_level in (InfoLevel.LEVEL_2_STATISTICAL, InfoLevel.LEVEL_3_STRUCTURAL):
        progress_lines.append("# Realized Statistics")
        if info_level is InfoLevel.LEVEL_2_STATISTICAL:
            progress_lines.append(
                "- Guidance: This section shows ONLY realized statistics from the current run "
                "(time, jobs arrived/completed/cancelled, and counts of each dynamic event type "
                "such as cancellations, priority changes, process-time changes, breakdowns, "
                "preventive maintenance, route changes, and due-date changes). Treat these numbers "
                "purely as evidence about how volatile and disturbed the system has actually been so far.\n"
                "  * If cancellations or due-date changes are frequent, avoid fragile schedules that "
                "require long uninterrupted chains and leave some slack for re-planning.\n"
                "  * If breakdowns or PM events are frequent, avoid overloading any single machine and "
                "prefer shorter operations or more flexible jobs on risky resources.\n"
                "  * If almost no disruptive events have occurred, you may schedule more aggressively, "
                "but still base decisions only on what has been observed, not on any hidden priors."
            )
        elif info_level is InfoLevel.LEVEL_3_STRUCTURAL:
            progress_lines.append(
                "- Guidance: These statistics show what has actually happened so far "
                "(arrivals, completed/cancelled jobs, and realized counts of each dynamic event type: "
                "cancellations, priority changes, process-time changes, breakdowns, preventive "
                "maintenance, route changes, due-date changes, etc.). Compare these realized "
                "frequencies and downtimes with the priors in Instance Metrics to adjust your "
                "scheduling style.\n"
                "  * If cancellations per arrived job are higher than the configured cancellation_rate, "
                "treat long, fragile job chains as risky and prefer decisions that keep alternative jobs "
                "available.\n"
                "  * If breakdown and PM downtime is high relative to the disturbance target, avoid "
                "pushing the system to extreme utilization and spread load across machines.\n"
                "  * If due-date changes are frequent relative to due_date_change_probability, be cautious "
                "about relying on current due dates and leave slack for future tightening or changes.\n"
                "Use this Bayesian view (priors vs realized data) to decide when to be more conservative "
                "versus more aggressive in your scheduling choices."
            )
        t = progress.get("time")
        if t is not None:
            progress_lines.append(f"- Current time: {t}")
        nj_arr = progress.get("num_jobs_arrived")
        nj_cmp = progress.get("num_jobs_completed")
        nj_ccl = progress.get("num_jobs_cancelled")
        if nj_arr is not None:
            progress_lines.append(f"- Jobs arrived: {nj_arr}")
        if nj_cmp is not None:
            progress_lines.append(f"- Jobs completed: {nj_cmp}")
        if nj_ccl is not None:
            progress_lines.append(f"- Jobs cancelled: {nj_ccl}")
        total_ops = progress.get("total_ops")
        completed_ops = progress.get("completed_ops")
        if total_ops is not None and completed_ops is not None:
            progress_lines.append(f"- Scheduled operations: {completed_ops} / {total_ops}")

        # Realized dynamic events so far (best-effort mapping from
        # simulator counters). This gives the LLM a sense of how many
        # cancellations / breakdowns / PMs etc. have already occurred.
        if isinstance(events, dict) and events:
            label_map = {
                "arrival": "arrivals",
                "cancellation": "cancellations",
                "breakdown": "breakdowns",
                "pm": "pm_events",
                "priority_change": "priority_changes",
                "ptime_change": "ptime_changes",
                "route_change": "route_changes",
                "due_date_change": "due_date_changes",
                "repair": "repairs",
                "due_date": "due_date_initializations",
            }
            pretty: List[str] = []
            for k, v in events.items():
                if not isinstance(v, (int, float)):
                    continue
                name = label_map.get(k, k)
                pretty.append(f"  - {name}: {int(v)}")
            if pretty:
                progress_lines.append("- Realized events so far:")
                progress_lines.extend(pretty)

    # Critical status (current emergencies / down machines) is visible at all levels
    if emergency_jobs or down_machines:
        critical_lines.append("# Critical Status")
        if emergency_jobs:
            critical_lines.append(f"- Active emergency jobs: {sorted(set(emergency_jobs))}")
        if down_machines:
            critical_lines.append(f"- Machines currently down: {sorted(set(down_machines))}")

    lines: List[str] = []
    if scenario_lines:
        lines.extend(scenario_lines)
    if progress_lines:
        if lines:
            lines.append("")
        lines.extend(progress_lines)
    if critical_lines:
        if lines:
            lines.append("")
        lines.extend(critical_lines)
    return "\n".join(lines)


def _extract_section(text: str, header: str) -> str:
    if not text:
        return ""
    lines = str(text).splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == header:
            start = i
            break
    if start is None:
        return ""
    out: List[str] = []
    for j in range(start, len(lines)):
        ln = lines[j]
        if j > start and ln.strip().startswith("# "):
            break
        out.append(ln)
    return "\n".join(out).strip()


def _extract_instance_metric_kv_lines(instance_metrics_block: str) -> List[str]:
    if not instance_metrics_block:
        return []
    out: List[str] = []
    for ln in instance_metrics_block.splitlines():
        raw = str(ln)
        s = raw.strip()
        if not s:
            continue
        if s.startswith("# "):
            continue
        if s.startswith("- Guidance"):
            continue
        if s.startswith("- Guidance:"):
            continue
        if s.startswith("- Target") or s.startswith("- Flow") or s.startswith("- Process") or s.startswith("- Preventive") or s.startswith("- Batch") or s.startswith("- Route") or s.startswith("- Due") or s.startswith("- Other"):
            continue
        # Keep only key-value leaf lines which are typically formatted as indented bullets.
        if raw.lstrip().startswith("- ") and raw.startswith("  "):
            out.append(raw.lstrip())
    return out


def _filter_instance_metrics(instance_metrics_block: str, allowed_keys: set[str]) -> str:
    kv_lines = _extract_instance_metric_kv_lines(instance_metrics_block)
    kept: List[str] = []
    for ln in kv_lines:
        # ln like "- rho_global: 0.8" or "- rho_bottleneck: 0.9" but already stripped to "- ..."
        s = ln.strip()
        if s.startswith("- "):
            s2 = s[2:]
        else:
            s2 = s
        key = s2.split(":", 1)[0].strip()
        if key in allowed_keys:
            kept.append(f"  - {s2}")
    if not kept:
        return ""
    return "\n".join(["# Instance Metrics", "- Target parameters (objectives & priors):"] + kept)


_DUMMY_PADDING_TEXT = (
    "Factory scheduling note (padding): Dynamic job shop scheduling has been studied for decades, "
    "covering dispatching rules, bottleneck analysis, and stability under disturbances. "
    "Always ensure safety compliance, keep walkways clear, and follow lockout-tagout procedures. "
    "This paragraph is not part of the current decision and may be ignored."
)


_TOKENIZER_CACHE: Dict[str, Any] = {}


def _count_tokens_best_effort(text: str) -> int:
    if not text:
        return 0
    tok_dir = os.getenv("LLMSCHED_TOKENIZER_DIR") or os.getenv("DYNA_SCHEDBENCH_TOKENIZER_DIR")
    if not tok_dir:
        return len(text)
    try:
        key = str(tok_dir)
        tok = _TOKENIZER_CACHE.get(key)
        if tok is None:
            from transformers import AutoTokenizer  # type: ignore

            tok = AutoTokenizer.from_pretrained(tok_dir, use_fast=True)
            _TOKENIZER_CACHE[key] = tok
        ids = tok.encode(text)
        return int(len(ids))
    except Exception:
        return len(text)


def _pad_to_match_length(base_prompt: str, target_prompt: str) -> str:
    base_n = _count_tokens_best_effort(base_prompt)
    tgt_n = _count_tokens_best_effort(target_prompt)
    try:
        tok_dir = os.getenv("LLMSCHED_TOKENIZER_DIR") or os.getenv("DYNA_SCHEDBENCH_TOKENIZER_DIR")
        delta = int(tgt_n) - int(base_n)
        msg = f"[LLMScheduler][V3] prompt_len_gap: L2={base_n} L3={tgt_n} delta={delta} tokenizer_dir={tok_dir}"
        print(msg, file=sys.stderr, flush=True)
        run_log_dir = os.getenv("DYNA_SCHEDBENCH_RUN_LOG_DIR")
        if run_log_dir:
            try:
                p = os.path.join(run_log_dir, "prompt_len_gap.log")
                with open(p, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass
    except Exception:
        pass
    if base_n >= tgt_n:
        return base_prompt
    missing = max(0, tgt_n - base_n)
    # Grow padding gradually; token estimation may be rough without tokenizer.
    chunk = "\n\n" + _DUMMY_PADDING_TEXT
    out = base_prompt
    for _ in range(2000):
        if missing <= 0:
            break
        out = out + chunk
        new_n = _count_tokens_best_effort(out)
        missing = tgt_n - new_n
        if new_n >= tgt_n:
            break
    return out


def build_cognitive_prompt_o1(
    obs: Dict[str, Any],
    legal_actions: List[Dict[str, Any]],
    env: Any,
    cog_cfg: CognitiveConfig = _DEFAULT_COGNITIVE_CONFIG,
    shop_profile: str = "",
):
    cfg = cog_cfg or _DEFAULT_COGNITIVE_CONFIG

    raw_variant = str(getattr(cfg, "prompt_variant", "") or "").strip()
    variant = raw_variant.upper()
    if variant in {"V1", "V3", "V4", "V5"}:
        effective_level = InfoLevel.LEVEL_2_STATISTICAL
    elif variant in {"V2", "V6"}:
        effective_level = InfoLevel.LEVEL_3_STRUCTURAL
    else:
        effective_level = cfg.info_level

    cfg_effective = cfg
    if effective_level is not cfg.info_level:
        try:
            cfg_effective = replace(cfg, info_level=effective_level)
        except Exception:
            cfg_effective = cfg

    encoder = ObservationEncoder(cfg_effective)
    encoded = encoder.encode(obs, legal_actions, env)
    table = _render_markdown_table(encoded.headers, encoded.rows)
    info_level = encoded.info_level

    if not shop_profile:
        # Default profile depends on effective info level.
        shop_profile = _format_dynamic_summary(obs, info_level)

        # Variant-specific surgery: selectively inject/transform only the L3 priors.
        if variant in {"V4", "V5", "V6", "V3"}:
            l3_profile = _format_dynamic_summary(obs, InfoLevel.LEVEL_3_STRUCTURAL)
            inst_block = _extract_section(l3_profile, "# Instance Metrics")

            if variant == "V4":
                # Only add global targets
                allowed = {"rho_global", "ddt", "scv_a", "scv_p", "disturbance", "load_cv"}
                filtered = _filter_instance_metrics(inst_block, allowed)
                if filtered:
                    shop_profile = (shop_profile + "\n\n" + filtered).strip()
            elif variant == "V5":
                # Only add bottleneck-related priors
                allowed = {"rho_bottleneck"}
                filtered = _filter_instance_metrics(inst_block, allowed)
                if filtered:
                    shop_profile = (shop_profile + "\n\n" + filtered).strip()
            elif variant == "V6":
                # Reformat L3 priors as XML and add an explicit ignore instruction.
                if inst_block:
                    xml_lines: List[str] = []
                    xml_lines.append("<Global_Priors>")
                    for ln in inst_block.splitlines():
                        if ln.strip().startswith("# "):
                            continue
                        xml_lines.append(ln)
                    xml_lines.append("</Global_Priors>")
                    xml_block = "\n".join(xml_lines)
                    # Replace the instance metrics section in the original L3 profile
                    before = l3_profile
                    try:
                        parts = l3_profile.split(inst_block)
                        if len(parts) >= 2:
                            before = parts[0].rstrip() + "\n" + xml_block + "\n" + "".join(parts[1:]).lstrip()
                    except Exception:
                        before = l3_profile + "\n\n" + xml_block
                    shop_profile = before

    system_block = _build_system_block(shop_profile, info_level)
    mode = cfg_effective.mode
    base_instructions = _build_o1_instructions(info_level)
    sampling_summary = getattr(encoded, "sampling_summary", "")
    if sampling_summary:
        try:
            sampling_text = str(sampling_summary)
        except Exception:
            sampling_text = ""
        if sampling_text:
            base_instructions = sampling_text + "\n\n" + base_instructions
    output_format = (
        '{"action_id": <int>, "job_id": <int or string>, '
        '"machine_group": <string>, "machine_id": <string or null>}'
    )
    if mode is InteractionMode.COT:
        prefix = (
            "Think step-by-step about machine queues, bottlenecks, and emergency jobs "
            "before choosing a single ActionID from the table.\n"
        )
        base_instructions = prefix + base_instructions
        if variant == "V6":
            base_instructions = (
                base_instructions
                + "\n\n"
                + "If the prompt contains a <Global_Priors> block, you may ignore it unless you believe it is necessary for making a better decision."
            )
        output_format = (
            '{"reasoning": "...", "action_id": <int>, "job_id": <int or string>, '
            '"machine_group": <string>, "machine_id": <string or null>}'
        )
    elif mode is InteractionMode.TOOL_USE:
        if info_level is InfoLevel.LEVEL_1_MYOPIC:
            tool_prefix = (
                "You will iteratively reason about the candidate actions and may call tools before making "
                "a final decision.\n"
                "Tools (Level 1):\n"
                "  - inspect_action_details(action_id): reveals detailed local information (job, op index, queue "
                "length, slack, progress) plus structural signals (bottleneck score of the group, overall system "
                "utilization, next-group load) and realized global statistics (arrivals, completions, cancellations, "
                "and event counters). It does NOT expose any design priors.\n"
                "  - simulate_action(action_id, steps?): runs a short rollout for the given ActionID (default steps=1) "
                "and returns an estimated completion time T; smaller T is better.\n"
                "Field semantics for inspect_action_details outputs:\n"
                "  - NA: unavailable/unreliable at this step; do not assume a value.\n"
                "  - Priority: -1 means an emergency job, 0 means a normal job (emergencies must not be starved).\n"
                "  - Slack: due_date − current_time − remaining_work. Negative slack means the job is projected to be late. "
                "Slack=NA usually means the job has no valid due date (e.g., due date is a horizon sentinel).\n"
                "  - Progress: (current_op_index + 1) / total_ops, in [0, 1]; larger means closer to completion.\n"
                "  - QueueLen: current queue length on the target machine (or machine group); larger means more congestion.\n"
                "  - BottleneckScore(Group=G): long-run utilization / bottleneck strength signal of group G; higher means a stronger bottleneck.\n"
                "  - SystemUtilization: average utilization across all machines; higher means the system is more heavily loaded.\n"
                "  - NextGroupLoad(Group=G): queue length on the job's next machine group; higher means more downstream congestion risk.\n"
                "  - EventCounts: realized event counters so far (evidence only; do not treat as priors).\n"
                "To call a tool, use either of the following formats:\n"
                "  - Plain text: 'Tool: inspect_action_details(<int>)' or 'Tool: simulate_action(<int>, steps=<int?>)'.\n"
                "  - JSON: {\"tool\": \"inspect_action_details\", \"action_id\": <int>} or "
                "{\"tool\": \"simulate_action\", \"action_id\": <int>, \"steps\": <int?>}.\n"
                "A recommended workflow at this level is: first inspect 1–2 promising Action IDs to understand their "
                "slack, queues, and bottleneck status; then, if needed, simulate the top candidates; finally, respond "
                "with a single JSON object choosing exactly one ActionID from the table.\n"
                "Do not assume any tool results that have not been explicitly provided to you.\n"
            )
        else:
            tool_prefix = (
                "You will iteratively reason about the candidate actions and may call a simulation tool "
                "before making a final decision.\n"
                "Tool: simulate_action(action_id).\n"
                "To call the tool, use either of the following formats:\n"
                "  - Plain text: 'Tool: simulate_action(<int>)'.\n"
                "  - JSON: {\"tool\": \"simulate_action\", \"action_id\": <int>}.\n"
                "The system will execute a short rollout for the referenced ActionID and return an observation "
                "describing the estimated completion time (smaller is better).\n"
                "Do not assume any simulation results that have not been explicitly provided to you.\n"
                "After you have gathered enough observations, return a final JSON object choosing exactly one ActionID "
                "from the table.\n"
            )
        base_instructions = tool_prefix + base_instructions
        output_format = (
            "Tool calls (during reasoning): either plain text 'Tool: inspect_action_details(<int>)' or 'Tool: "
            "simulate_action(<int>, steps=<int?>)', or JSON objects such as {\"tool\": \"inspect_action_details\", "
            "\"action_id\": <int>} or {\"tool\": \"simulate_action\", \"action_id\": <int>, \"steps\": <int?>}.\n"
            "Final answer (after using tools): a single JSON object {\"action_id\": <int>, \"job_id\": <int or string>, "
            "\"machine_group\": <string>, \"machine_id\": <string or null>} with no extra text."
        )
    user_block = USER_PROMPT_TEMPLATE.format(
        info_level=info_level.value,
        markdown_table=table,
        instructions=base_instructions,
        output_format=output_format,
    )
    few_shot = ""
    if cfg_effective.use_few_shot:
        bank = FewShotBank()
        few_shot = bank.get_examples(info_level, cfg_effective.max_examples)
        if not few_shot:
            few_shot = _get_few_shot_examples(info_level, cfg_effective.max_examples)
        if mode is InteractionMode.TOOL_USE and info_level is InfoLevel.LEVEL_1_MYOPIC:
            tool_example_lines: List[str] = []
            tool_example_lines.append("### Tool-use Example (Level 1 with tools)")
            tool_example_lines.append("Below is a sketch of a good multi-turn pattern:\n")
            tool_example_lines.append("Tool: inspect_action_details(2)")
            tool_example_lines.append("Observation: inspect_action_details(2) =>")
            tool_example_lines.append("- Local:")
            tool_example_lines.append("  Job = Job-2")
            tool_example_lines.append("  OpIdx = 1/3")
            tool_example_lines.append("  Group = G1")
            tool_example_lines.append("  QueueLen = 4")
            tool_example_lines.append("  Priority = -1.000")
            tool_example_lines.append("  Slack = -1.500")
            tool_example_lines.append("  Progress = 0.333")
            tool_example_lines.append("- Structural:")
            tool_example_lines.append("  BottleneckScore(Group=G1) = 0.900")
            tool_example_lines.append("  SystemUtilization = 0.850")
            tool_example_lines.append("  NextGroupLoad(Group=G1) = 5")
            tool_example_lines.append("- GlobalEvidence:")
            tool_example_lines.append("  JobsArrived = 20")
            tool_example_lines.append("  JobsCompleted = 15")
            tool_example_lines.append("  JobsCancelled = 1")
            tool_example_lines.append("  WIP = 8")
            tool_example_lines.append("  EventCounts = {arrival=20, cancellation=1, breakdown=0, pm=1, priority_change=0, ptime_change=0, route_change=0, due_date_change=0}")
            tool_example_lines.append("Tool: inspect_action_details(3)")
            tool_example_lines.append("Observation: inspect_action_details(3) =>")
            tool_example_lines.append("- Local:")
            tool_example_lines.append("  Job = Job-3")
            tool_example_lines.append("  OpIdx = 0/2")
            tool_example_lines.append("  Group = G1")
            tool_example_lines.append("  QueueLen = 3")
            tool_example_lines.append("  Priority = 0.000")
            tool_example_lines.append("  Slack = 2.000")
            tool_example_lines.append("  Progress = 0.250")
            tool_example_lines.append("- Structural:")
            tool_example_lines.append("  BottleneckScore(Group=G1) = 0.900")
            tool_example_lines.append("  SystemUtilization = 0.850")
            tool_example_lines.append("  NextGroupLoad(Group=G1) = 2")
            tool_example_lines.append("- GlobalEvidence:")
            tool_example_lines.append("  JobsArrived = 20")
            tool_example_lines.append("  JobsCompleted = 15")
            tool_example_lines.append("  JobsCancelled = 1")
            tool_example_lines.append("  WIP = 8")
            tool_example_lines.append("  EventCounts = {arrival=20, cancellation=1, breakdown=0, pm=1, priority_change=0, ptime_change=0, route_change=0, due_date_change=0}")
            tool_example_lines.append("Tool: simulate_action(2)")
            tool_example_lines.append("Observation: simulate_action(2) => estimated finish time T=105.500. (Smaller T is better.)")
            tool_example_lines.append("Tool: simulate_action(3)")
            tool_example_lines.append("Observation: simulate_action(3) => estimated finish time T=112.750. (Smaller T is better.)")
            tool_example_lines.append("# After comparing all observations, respond with a single final JSON object only:")
            tool_example_lines.append("{\"action_id\": 2, \"job_id\": \"Job-2\", \"machine_group\": \"G1\", \"machine_id\": \"G1-M1\"}")
            tool_example_lines.append("Do not include any natural language outside the final JSON object.")
            tool_example = "\n".join(tool_example_lines)
            few_shot = (few_shot + "\n\n" + tool_example) if few_shot else tool_example
    parts: List[str] = [system_block]
    if few_shot:
        parts.append(few_shot)
    parts.append(user_block)
    prompt = "\n\n".join(p for p in parts if p)

    # V3: L2 prompt + domain-related dummy padding to match the token length of standard L3.
    if variant == "V3":
        try:
            # Build a reference V2 prompt (standard L3) for length matching.
            ref_cfg = cfg_effective
            try:
                ref_cfg = replace(cfg_effective, info_level=InfoLevel.LEVEL_3_STRUCTURAL)
            except Exception:
                ref_cfg = cfg_effective
            ref_cfg = replace(ref_cfg, prompt_variant="") if hasattr(ref_cfg, "prompt_variant") else ref_cfg
            ref_prompt, _ = build_cognitive_prompt_o1(
                obs,
                legal_actions,
                env,
                ref_cfg,
                shop_profile="",
            )
            prompt = _pad_to_match_length(prompt, ref_prompt)
        except Exception:
            # best-effort: do not fail the run if reference prompt construction fails.
            prompt = prompt + "\n\n" + _DUMMY_PADDING_TEXT
    return prompt, encoded.pruned_actions


def build_reflection_prompt(
    state_table: str,
    previous_response: str,
    chosen_action_id: int,
) -> str:
    try:
        aid_str = str(int(chosen_action_id))
    except Exception:
        aid_str = str(chosen_action_id)

    instructions = (
        "You act as a Quality Assurance Auditor. Review the decision (Action "
        f"{aid_str}) against the provided Current State Table. Verify two aspects:\n"
        "1. Feasibility: Does the chosen machine have a valid status and start time?\n"
        "2. Optimality: Is there an obviously better alternative based on the visible columns "
        "(e.g., much shorter queue or higher urgency)?\n"
        "If you find a critical violation (e.g., selecting a DOWN machine) or a significant missed opportunity, "
        "output the corrected Action ID. If the decision is sound, output the original ID.\n"
    )

    parts: List[str] = []
    parts.append("You are an auditing expert checking the quality of a scheduling decision.")
    parts.append("## Current State Table")
    parts.append(state_table)
    if previous_response:
        parts.append("## Previous Decision")
        parts.append(str(previous_response))
    parts.append("## Audit Task")
    parts.append(instructions)
    parts.append("## Output Format (JSON only)")
    parts.append('Return exactly one JSON object: {"action_id": <int>} with no extra text.')
    return "\n\n".join(parts)


def parse_o1(text: str) -> Dict[str, Any]:
    def _from_obj(obj: Any) -> Dict[str, Any]:
        if not isinstance(obj, dict):
            return {}
        out: Dict[str, Any] = {}
        if "job_id" in obj and "machine_group" in obj:
            out["job_id"] = obj["job_id"]
            out["machine_group"] = obj["machine_group"]
            if "machine_id" in obj:
                out["machine_id"] = obj["machine_id"]
        if "action_id" in obj:
            out["action_id"] = obj["action_id"]
        return out

    candidate: Dict[str, Any] = {}
    try:
        obj = _safe_json_loads(text)
        candidate = _from_obj(obj)
        if candidate:
            return candidate
    except Exception:
        candidate = {}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "{" not in line or "}" not in line:
            continue
        try:
            obj = _safe_json_loads(line)
        except Exception:
            continue
        out = _from_obj(obj)
        if out:
            candidate = out

    if candidate:
        return candidate
    return {}
