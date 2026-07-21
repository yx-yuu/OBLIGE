#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROGRAMBENCH_ROOT="${PROGRAMBENCH_ROOT:-temp/external_repos/ProgramBench}"
SPLIT="configs/task_splits/programbench_model_60.json"
CONFIG="configs/experiments/opencode_paper_model_60.json"
OUTPUT_ROOT="${PAPER_MODEL_OUTPUT_ROOT:-runs/paper_model_matrix}"

python -m edos.cli.build_programbench_split \
  --programbench-root "$PROGRAMBENCH_ROOT" \
  --output "$SPLIT" \
  --limit 60 \
  --difficulty easy --difficulty medium --difficulty hard \
  --exclude-repository-prefix testorg/ \
  --seed 20260712 \
  --difficulty-quota easy=20 \
  --difficulty-quota medium=20 \
  --difficulty-quota hard=20 \
  --require-count 60

MODELS=(
  "qwen/Qwen3.5-397B-A17B"
  "deepseek/DeepSeek-v4-pro"
  "minimax/minimax-m2.7"
  "bigmodel/glm-5.1"
  "anthropic/claude-opus-4-7"
  "openai/gpt-5.1"
)

RUN_DIRS=()
for model in "${MODELS[@]}"; do
  slug="$(printf '%s' "$model" | tr '/[:upper:]' '_[:lower:]' | tr -cd 'a-z0-9_.-')"
  run_dir="$OUTPUT_ROOT/$slug"
  RUN_DIRS+=("$run_dir")
  python -m edos.cli.run_experiment \
    --config "$CONFIG" \
    --experiment-name "paper_model_60_$slug" \
    --output-dir "$run_dir" \
    --model "$model" \
    --condition clean_skill_clean_verifier \
    --condition adaptive_full_medium \
    --require-task-material-status programbench_cleanroom_workspace
  python -m edos.cli.aggregate_results --run-dir "$run_dir"
done

args=()
for run_dir in "${RUN_DIRS[@]}"; do
  args+=(--run-dir "$run_dir")
done
python -m edos.cli.build_external_validity_evidence \
  "${args[@]}" \
  --output-dir "$OUTPUT_ROOT/aggregate"
