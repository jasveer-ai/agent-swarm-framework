# Contributing

Thanks for helping improve Agent Swarm Framework. The project is intentionally
small: prefer focused changes that strengthen typed boundaries, provider
isolation, evidence, or operational clarity.

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Verification

The default checks are hermetic and do not call a model provider:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/ruff check agent_swarm examples tests swarm.py
./run_smoke_test.sh
```

The live integration check is opt-in because it can consume quota and may edit
the working directory:

```bash
RUN_LIVE_SWARM=1 .venv/bin/python tests/integration_swarm_test.py
```

Run it only in a disposable checkout with provider credentials and model IDs
you have explicitly configured.

## Change expectations

- Keep provider calls behind `ModelProvider`; do not put subprocess logic in
  agents or the runner.
- Preserve caller-supplied plans as a zero-overseer-call path.
- Treat access labels as enforced boundaries, not descriptive metadata.
- Add a hermetic regression for every behavior change.
- Never add credentials, provider reasoning, local paths, or private task data
  to fixtures or run artifacts.
- Update `README.md` for operator-facing behavior and `docs/architecture.md`
  for ownership or flow changes.

By contributing, you agree that your contribution is licensed under the MIT
License in this repository.
