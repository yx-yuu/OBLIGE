#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROGRAMBENCH_ROOT="${PROGRAMBENCH_ROOT:-temp/external_repos/ProgramBench}"
SPLIT="configs/task_splits/programbench_main_100.json"
CONFIG="configs/experiments/opencode_paper_main_100.json"
RUN_DIR="${PAPER_MAIN_RUN_DIR:-runs/opencode_paper_main_100}"

PYTHONPATH=src python -m edos.cli.build_programbench_split \
  --programbench-root "$PROGRAMBENCH_ROOT" \
  --output "$SPLIT" \
  --limit 100 \
  --difficulty easy --difficulty medium --difficulty hard \
  --exclude-repository-prefix testorg/ \
  --seed 20260713 \
  --difficulty-quota easy=25 \
  --difficulty-quota medium=55 \
  --difficulty-quota hard=20 \
  --require-count 100

PYTHONPATH=src python -m edos.cli.audit_task_materials \
  --config "$CONFIG" \
  --output "$RUN_DIR/task_material_audit.preflight.json" \
  --require-status programbench_cleanroom_workspace

PYTHONPATH=src python -m edos.cli.docker_preflight \
  --config "$CONFIG" \
  --output "$RUN_DIR/docker_preflight.json"

PYTHONPATH=src python -m edos.cli.run_experiment \
  --config "$CONFIG" \
  --output-dir "$RUN_DIR" \
  --require-task-material-status programbench_cleanroom_workspace

PYTHONPATH=src python -m edos.cli.aggregate_results --run-dir "$RUN_DIR"

# Optional post-processing tools (require paper source files)
# Uncomment if you have the paper LaTeX files and placeholder scripts
# PYTHONPATH=src python -m edos.cli.build_paper_stats --run-dir "$RUN_DIR"
# PYTHONPATH=src python -m edos.cli.build_evaluation_artifacts \
#   --mode aggregate \
#   --run-dir "$RUN_DIR" \
#   --refresh-aggregate
# PYTHONPATH=src python -m edos.cli.audit_paper_admission \
#   --run-dir "$RUN_DIR" \
#   --profile paper_main \
#   --refresh-aggregate
# PYTHONPATH=src python -m edos.cli.build_paper_evidence \
#   --run-dir "$RUN_DIR" \
#   --refresh-admission \
#   --paper-tex paper/ieee_submission_source/main.tex \
#   --placeholder-script scripts/section6_placeholder_consistency.py
