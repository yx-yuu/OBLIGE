#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=src python -m edos.cli.build_programbench_split \
  --programbench-root temp/external_repos/ProgramBench \
  --output configs/task_splits/programbench_smoke_3.json \
  --limit 3 --difficulty easy

PYTHONPATH=src python -m edos.cli.audit_task_materials \
  --config configs/experiments/programbench_export_smoke.json \
  --output runs/programbench_export_smoke_task_material_audit.json

PYTHONPATH=src python -m edos.cli.run_experiment --config configs/experiments/programbench_export_smoke.json
PYTHONPATH=src python -m edos.cli.aggregate_results --run-dir runs/programbench_export_smoke
