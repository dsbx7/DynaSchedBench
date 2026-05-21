# DynaSchedBench

[![PyPI latest](https://img.shields.io/badge/PyPI-latest-blue)](https://pypi.org/project/dsbx/)
[![Python](https://img.shields.io/pypi/pyversions/dsbx.svg)](https://pypi.org/project/dsbx/)
[![Docs](https://readthedocs.org/projects/dsbx/badge/?version=latest)](https://dsbx.readthedocs.io/)
[![Website](https://img.shields.io/badge/Website-dsbx7.github.io-0f766e)](https://dsbx7.github.io/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

DynaSchedBench accompanies the ICML 2026 paper
*DynaSchedBench: Calibrated Dynamic Scheduling Benchmarks and Observability
Paradox in LLM-based Scheduling Agents*. It provides calibrated benchmark
generation for Dynamic Flexible Job Shop Scheduling, an event-driven simulator,
a unified single-agent environment, trajectory-based evaluation, visualization
tools, and lightweight scheduling baselines.

Official website: [dsbx7.github.io](https://dsbx7.github.io/).

## Highlights

- Sequential Event-Space Calibrator (SESC) for calibrated dynamic event streams.
- Schedule Stress Index (SSI) for stratifying instance difficulty.
- Event-driven dynamic scheduling simulator with explicit state snapshots.
- Unified single-agent environment for heuristic, RL, and LLM schedulers.
- Reproducible generator for Dynamic Flexible Job Shop Scheduling instances.
- Trajectory metrics, hard-constraint checks, and visual diagnostics.
- Support for evaluating observability levels and reasoning strategies in
  LLM-based scheduling agents.
- Lightweight `dsbx-*` command-line tools for generation, simulation,
  evaluation, visualization, and agent rollouts.
- Research assets kept separate from the PyPI wheel for fast installation.

## Installation

Install the public package:

```bash
pip install dsbx
```

Install from source for development:

```bash
git clone https://github.com/dsbx7/DynaSchedBench.git
cd DynaSchedBench
python -m pip install -e .[dev,docs]
```

## Quickstart

```python
from pathlib import Path

from dsbx.Agents import SPTAgent
from dsbx.Env import DynaSchedEnv
from dsbx.Eval.Metrics import evaluate_trajectory
from dsbx.Gen import load_input_model

model = load_input_model(Path("docs/examples/minimal_input_model.json"))
env = DynaSchedEnv(model)
agent = SPTAgent()

obs = env.reset()
done = False

while not done:
    legal_actions = env.legal_actions()
    if not legal_actions:
        obs = env.advance_if_idle()
        continue

    action = agent.act(obs, legal_actions, env)
    obs, reward, done, info = env.step(action)

metrics = evaluate_trajectory(env.get_trajectory())
print(metrics)
```

## Command Line

```bash
dsbx-gen --help
dsbx-agent --help
dsbx-eval --help
dsbx-vis --help
dsbx-sim --help
```

A typical workflow is:

```bash
dsbx-gen gen -i docs/examples/minimal_input_model.json -o runs/minimal
dsbx-agent run -d runs/minimal -o runs/minimal/spt -a spt
dsbx-eval from-trajectory -t runs/minimal/spt/trajectory_light.jsonl
dsbx-vis gantt -t runs/minimal/spt/trajectory_light.jsonl -o runs/minimal/spt/gantt.pdf
```

## Repository Layout

```text
src/dsbx/            # Release Python package
docs/                # Sphinx and Read the Docs documentation
data/                # Benchmark data and generated instance collections
tests/               # Release and package guard tests
```

## Documentation

The documentation is maintained with Sphinx and Read the Docs. It includes
quickstart material, CLI references, benchmark notes, release instructions, and
API pages generated from docstrings.

## Citation

```bibtex
@inproceedings{dynaschedbench2026,
  title = {DynaSchedBench: Calibrated Dynamic Scheduling Benchmarks and Observability Paradox in LLM-based Scheduling Agents},
  author = {Shijie Cao and Yuan Yuan and Jing Liu},
  booktitle = {Proceedings of the 43rd International Conference on Machine Learning},
  year = {2026}
}
```

## License

DynaSchedBench is released under the Apache License 2.0.
