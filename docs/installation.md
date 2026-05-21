# Installation

DynaSchedBench is distributed on PyPI as `dsbx`. The Python import name is
`dsbx`, and every release command starts with `dsbx-`.

## Supported Python Versions

The package metadata declares support for Python 3.9 through Python 3.12.
Read the Docs builds this documentation with Python 3.11, as configured in
`.readthedocs.yaml`.

## Install From PyPI

```bash
python -m pip install dsbx
```

Check the installation:

```bash
python -c "import dsbx; print(dsbx.__version__)"
dsbx-gen --help
```

## Install From Source

Use this path when contributing to the project, editing documentation, or
running release checks locally.

```bash
git clone https://github.com/dsbx7/DynaSchedBench.git
cd DynaSchedBench
python -m pip install -e .[dev,docs]
```

The `dev` extra installs test and release tooling. The `docs` extra installs
Sphinx, the Read the Docs theme, MyST Markdown support, and autodoc helpers.

## Optional LLM Agent Configuration

The built-in heuristic and evolutionary agents do not require API keys. LLM
agents read credentials from environment variables:

```bash
export DYNA_SCHEDBENCH_LLM_PROVIDER=openai
export DYNA_SCHEDBENCH_LLM_API_KEY=your_api_key
export DYNA_SCHEDBENCH_LLM_MODEL=gpt-4o-mini
```

You can also pass provider, model, base URL, sampling, and timeout options to
`dsbx-agent run`. If no key is available, LLM agents fall back to a null client
or heuristic behavior where implemented.

## Verify Local Documentation Builds

From a source checkout:

```bash
python -m sphinx -W -b html docs docs/_build/html
```

Open `docs/_build/html/index.html` in a browser to inspect the generated site.
The `-W` flag treats warnings as errors, matching the Read the Docs policy in
this repository.
