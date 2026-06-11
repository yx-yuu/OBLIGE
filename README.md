# Validation-Feedback Over-Compliance EDoS

This repository is an anonymous artifact companion for a security research
submission. It studies an economic denial-of-service pattern in long-horizon
software-engineering workflows: a task-local validation channel can be
reframed into a sequence of plausible but redundant behavioral checks, causing
large additional cost while preserving the appearance of useful task progress.

This initial anonymous upload contains the artifact README only. The method
code is organized so that the attack logic, cost controller, ProgramBench
integration, instrumentation, and analysis can be reviewed independently from
local drafts, generated outputs, and private workspace state.

## Scope and Threat Model

The artifact is designed for local, no-internet ProgramBench-style evaluation.
The benchmark task remains unchanged: the worker receives a reference
executable and documentation, reconstructs a candidate implementation, and is
scored by behavioral tests.

The attacker model is intentionally limited:

- The attacker may influence a task-local validation entry point or its
  feedback text.
- The attacker may maintain session state inside the validation feedback logic.
- The attacker does not control model weights, hidden tests, the reference
  executable, or the scorer.
- The attack does not require internet access and does not modify benchmark
  ground truth.
- The goal is resource amplification, not data theft, policy evasion, or
  sabotage of the final candidate program.

The implementation is a defensive research harness. It keeps structured logs
and safety boundaries explicit so that the resulting traces can be audited.

## Method Overview

The method compares a clean validation channel with a polluted validation
channel under otherwise matched conditions.

The clean verifier returns short, direct behavior-conformance feedback. The
polluted verifier returns stateful validation obligations that remain plausible
for ProgramBench tasks but increase the number of checks, feedback turns, and
context consumed by the workflow.

The core mechanisms are:

- **Validation obligation graph:** expands one local behavior check into a
  bounded graph of follow-up checks.
- **Branch latching:** keeps a validation branch active until the current
  obligation is resolved or explicitly terminated.
- **Dynamic stage markers:** make later feedback depend on the current session
  state rather than a static checklist.
- **Semantic echoing:** ties each extra check back to the original behavioral
  reconstruction goal.
- **Adaptive mode switching:** chooses among expansion, repair, pagination,
  shrink, and termination states.
- **Budget controller:** targets a configured resource-loss interval instead
  of maximizing cost without bound.

## Research Questions

The artifact is structured around the following evaluation questions:

- **RQ0:** Does the local validation entry point get adopted during the normal
  reconstruction workflow?
- **RQ1:** Does polluted validation feedback increase token, call, time, and
  tool-use cost relative to a clean paired baseline?
- **RQ2:** Can the budget controller keep extra cost within a target interval?
- **RQ3:** Does the workflow still preserve useful task progress and final
  submission behavior?
- **RQ4:** Do content-safety and cheating-oriented audits miss this form of
  over-compliance resource abuse under the evaluated settings?

## Artifact Layout

Only method-facing code and lightweight experiment configuration belong in the
anonymous artifact. Generated runs, local caches, drafts, and private workspace
state are excluded.

```text
configs/
  defenses/            Offline audit and defense-evaluation settings
  experiments/         Reproducible smoke, pilot, and ablation configs
  task_splits/         ProgramBench task lists used by experiments
  verifier/            Clean and polluted verifier policy configs

src/edos/
  verifier/            Clean/polluted validation feedback implementation
  controller/          Budget and adaptive-state control logic
  programbench/        Task loading, workspace handling, and scoring helpers
  instrumentation/     Event logging, usage accounting, and failure labels
  analysis/            Aggregation, metrics, statistics, and audit summaries
  cli/                 Command-line entry points for running and analyzing runs

scripts/               Thin wrappers for reproducible smoke and pilot commands
tests/                 Unit and integration tests for the method implementation
runs/                  Placeholder for local experiment outputs
```

## Reproduction Workflow

Install the package in an isolated Python environment:

```bash
python -m pip install -e .
```

Run the lightweight schema and controller smoke test:

```bash
PYTHONPATH=src python -m edos.cli.run_experiment \
  --config configs/experiments/smoke.json

PYTHONPATH=src python -m edos.cli.aggregate_results \
  --run-dir runs/smoke_mvp
```

Build a small ProgramBench task split after placing the official ProgramBench
repository in a local directory:

```bash
PYTHONPATH=src python -m edos.cli.build_programbench_split \
  --programbench-root /path/to/ProgramBench \
  --output configs/task_splits/programbench_smoke_3.json \
  --limit 3 \
  --difficulty easy
```

Run the test suite:

```bash
python -m pytest -q
```

Full ProgramBench evaluation requires the official ProgramBench assets,
container runtime access, benchmark task images, and a configured model
endpoint. Those assets are intentionally not bundled in this artifact.

## Expected Outputs

Each completed run writes structured evidence for later audit:

- resolved experiment configuration;
- event log;
- verifier state transitions;
- controller trace;
- usage and cost-proxy summary;
- ProgramBench-compatible score record;
- failure label, if the run does not complete normally.

The analysis commands aggregate these files into paired clean-vs-polluted
comparisons, target-cost error summaries, utility-preservation checks, and
offline defense-evaluation tables.

## Safety and Ethics

This artifact is meant to support reproducible defensive evaluation of
resource-abuse risks in software-engineering workflows. The experiments run in
local benchmark workspaces, do not require network access inside the benchmark
task, and preserve logs for review. The repository does not provide deployment
instructions for attacking production services.
