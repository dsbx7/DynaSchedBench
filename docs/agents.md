# Agents

DynaSchedBench agents implement a small interface: reset for a new episode,
read the current observation and legal actions, then return one legal action.
Agents can be used from Python or through `dsbx-agent run`.

## Discover Available Agents

```bash
dsbx-agent list-agents
```

Built-in names include:

| Agent | Description |
| --- | --- |
| `spt` | Shortest Processing Time baseline. |
| `random` | Uniform random legal-action baseline. |
| `pdr:<OP_RULE>:<MACHINE_RULE>` | Priority dispatching rule with explicit operation and machine rules. |
| `gp-simplegp-best` | GP-based dispatching rule extracted from a fixed best-of-run expression. |
| `ga` | Genetic Algorithm online rescheduling agent. |
| `de` | Differential Evolution online rescheduling agent. |
| `pso` | Particle Swarm Optimization online rescheduling agent. |
| `cmaes` | CMA-ES action scoring agent. |
| `sa` | Simulated Annealing online rescheduling agent. |
| `ts` | Tabu Search online rescheduling agent. |
| `moea` | MOEA/D-style multi-objective online agent. |
| `nsga2` | NSGA-II multi-objective online agent. |
| `llm-coder` | LLM-assisted heuristic code generation agent. |
| `llm-scheduler` | LLM scheduling policy with cognitive prompts. |

## PDR Agents

PDR agents encode their behavior in the agent name:

```bash
dsbx-agent run -d runs/minimal -o runs/minimal/pdr_spt_lit -a pdr:SPT:LIT
```

Operation rules:

| Rule | Meaning |
| --- | --- |
| `SPT` | Shortest Processing Time. |
| `LPT` | Longest Processing Time. |
| `MWKR` | Most Work Remaining. |
| `LWKR` | Least Work Remaining. |
| `MOPNR` | Most Operations Remaining. |
| `LOPNR` | Least Operations Remaining. |
| `FIFO` | First In First Out. |
| `LIFO` | Last In First Out. |

Machine rules:

| Rule | Meaning |
| --- | --- |
| `LIT` | Least Idle Time, usually earliest available. |
| `LWL` | Least Workload. |
| `SPT` | Shortest Processing Time on the machine. |

## Evolutionary And Local Search Agents

Use `agent-help` to show relevant options:

```bash
dsbx-agent agent-help ga
dsbx-agent agent-help de
dsbx-agent agent-help pso
dsbx-agent agent-help cmaes
dsbx-agent agent-help sa
dsbx-agent agent-help ts
dsbx-agent agent-help moea
dsbx-agent agent-help nsga2
```

Example:

```bash
dsbx-agent run \
  -d runs/minimal \
  -o runs/minimal/ga \
  -a ga \
  --ga-population-size 16 \
  --ga-generations 8 \
  --ga-rollout-steps 3 \
  --ga-random-seed 42
```

The rollout-step options control whether the agent evaluates candidate actions
with a short environment rollout or with the faster one-step score estimate.
Use small budgets for smoke tests and larger budgets for final experiments.

## LLM Agents

LLM agents can be configured from environment variables:

```bash
export DYNA_SCHEDBENCH_LLM_PROVIDER=openai
export DYNA_SCHEDBENCH_LLM_API_KEY=your_api_key
export DYNA_SCHEDBENCH_LLM_MODEL=gpt-4o-mini
```

Common CLI overrides:

```bash
dsbx-agent run \
  -d runs/minimal \
  -o runs/minimal/llm_scheduler \
  -a llm-scheduler \
  --llm-provider openai \
  --llm-model gpt-4o-mini \
  --llm-temperature 0.2 \
  --llm-sched-info-level L2 \
  --llm-sched-mode direct \
  --llm-sched-max-candidates 8
```

LLM scheduler options group into:

- provider and transport: `--llm-provider`, `--llm-model`,
  `--llm-base-url`, `--llm-timeout`;
- sampling: `--llm-temperature`, `--llm-top-p`, `--llm-top-k`;
- prompt context: `--llm-sched-info-level`, `--llm-sched-mode`,
  `--llm-sched-use-few-shot`, `--llm-sched-max-examples`;
- action selection: `--llm-sched-max-candidates`,
  `--llm-sched-select-machine`;
- refinement: `--llm-sched-refinement`, `--llm-sched-reflection-rounds`,
  `--llm-sched-voting-n`.

LLMCoder has additional candidate-generation and sandbox-evaluation options:

```bash
dsbx-agent agent-help llm-coder
```

If no LLM API key is available, DynaSchedBench uses a null client or fallback
heuristic behavior where implemented. This keeps local tests reproducible while
making it clear in logs that no real LLM call was made.

## Python Agent Interface

Custom agents can follow `dsbx.Agents.Base.BaseAgent`:

```python
from typing import Any


class MyAgent:
    def reset(self, scenario_info: dict[str, Any] | None = None) -> None:
        self.num_decisions = 0

    def act(self, obs: dict[str, Any], legal_actions: list[dict[str, Any]], env: Any):
        self.num_decisions += 1
        if not legal_actions:
            return None
        return min(legal_actions, key=lambda a: a.get("process_time", 0.0))
```

Use the environment loop shown in {doc}`quickstart` to evaluate custom agents.
