# FAQ

## Is The PyPI Name `DynaSchedBench` Or `dsbx`?

The PyPI project name is `dsbx`.

```bash
pip install dsbx
```

The Python import name is `dsbx`.

```python
import dsbx
```

All release command-line tools start with `dsbx-`.

## Why Does `dsbx-agent run` Use `-d` Instead Of `-c`?

Agents run on a generated instance directory:

```bash
dsbx-agent run -d runs/minimal -o runs/minimal/spt -a spt
```

The original input-model JSON is used by `dsbx-gen gen`. After generation,
the agent needs the generated `events.jsonl`, `static_jobs.json`,
`static_machines.json`, and normalized `input_model.json`.

## Should I Use `trajectory.json` Or `trajectory_light.jsonl`?

Use `trajectory_light.jsonl` for most command-line workflows. It is streamed to
disk and is safer for long horizons or large instances.

Use `trajectory.json` for small examples where you want a full serialized
Pydantic trajectory in one file.

## Why Is My Read the Docs Build Failing On A Warning?

The project intentionally sets:

```yaml
sphinx:
  fail_on_warning: true
```

This prevents broken links, failed autodoc imports, and missing pages from
silently reaching users. Reproduce locally with:

```bash
python -m sphinx -W -b html docs docs/_build/html
```

## Do I Commit `docs/_build/html`?

No. Read the Docs builds HTML itself from the source files in `docs/`.
`docs/_build/` is local generated output and is ignored by `.gitignore`.

## How Do I Add A New CLI Tutorial?

Add a Markdown page under `docs/`, add it to `docs/index.rst`, and verify:

```bash
python -m sphinx -W -b html docs docs/_build/html
```

Prefer workflow examples that start from an input model, produce a generated
instance directory, then run evaluation or visualization. This keeps examples
consistent with the actual `dsbx-*` command flow.
