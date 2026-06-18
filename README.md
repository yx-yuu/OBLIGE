# OBLIGE Artifact

This repository contains the code companion for OBLIGE, a local experimental
harness for studying validation-feedback over-compliance in long-horizon
coding-agent workflows.

The artifact includes:

- the validation-feedback mechanism and budget controller;
- ProgramBench-compatible task loading, workspace, and scoring helpers;
- agent adapters for mock, local-command, OpenCode, OpenHands, and
  mini-SWE-agent based workflows;
- experiment configurations for smoke, reviewer quick checks, pilot runs,
  ablations, and defenses;
- analysis code for aggregation and Evaluation table/figure generation;
- unit and integration tests for the public code path.

Generated runs, private notes, draft materials, paper sources, API keys, caches,
and local benchmark assets are intentionally not included.

## Install

Use Python 3.10 or newer.

```bash
python -m pip install -e .
```

The default reviewer checks use the mock adapter and do not require API keys,
Docker, internet access, or ProgramBench assets.

## Quick Reviewer Check

Run a single-task end-to-end check:

```bash
scripts/reviewer_quickstart.sh 1 runs/reviewer_single artifacts/reviewer_single_eval
```

Run a small 10-task check:

```bash
scripts/reviewer_quickstart.sh 10 runs/reviewer_10 artifacts/reviewer_10_eval
```

The quickstart script runs the deterministic reviewer fixture, aggregates run
artifacts, and generates the Evaluation tables and figures under the requested
artifact directory. These checks validate the public code path and schema; they
are not full-study ProgramBench results.

## Generate Evaluation Artifacts

Generate deterministic smoke-mode Evaluation artifacts without running agents:

```bash
PYTHONPATH=src python -m edos.cli.build_evaluation_artifacts \
  --mode smoke \
  --output-dir artifacts/evaluation_smoke
```

Generate the same table/figure schema from an observed run directory:

```bash
PYTHONPATH=src python -m edos.cli.build_evaluation_artifacts \
  --mode aggregate \
  --run-dir runs/reviewer_10 \
  --output-dir artifacts/evaluation_observed
```

Each generated artifact directory contains:

- `evaluation_artifacts_manifest.json`;
- CSV and LaTeX fragments for the Evaluation tables;
- PDF data figures.

## Run Tests

The test suite uses Python's standard `unittest` runner:

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

If `pytest` is available, the same tests can also be run with:

```bash
PYTHONPATH=src python -m pytest -q
```

## ProgramBench Runs

Full ProgramBench evaluation requires the official ProgramBench assets,
container runtime access, task images, and configured model endpoints. Those
external assets are not bundled in this repository.

After preparing a local ProgramBench checkout, a task split can be built with:

```bash
PYTHONPATH=src python -m edos.cli.build_programbench_split \
  --programbench-root /path/to/ProgramBench \
  --output configs/task_splits/programbench_smoke_3.json \
  --limit 3 \
  --difficulty easy
```

Real-agent scripts under `scripts/` are thin wrappers around the same public
configuration and CLI entry points. They expect the corresponding external
agent CLI, Docker access, and model credentials to be configured locally.
