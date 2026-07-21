#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${ROOT_DIR}/configs/experiments/openhands_real_smoke.json"
RUN_DIR="${ROOT_DIR}/runs/openhands_real_smoke"
RUN_ARGS=()
DOCKER_ARGS=()

usage() {
  cat <<'EOF'
usage: scripts/openhands_real_smoke.sh [options]

Options:
  --condition NAME       Run one condition. Can be passed multiple times.
  --task-limit N         Limit selected tasks.
  --task-start N         Start task slice at index N.
  --task-stop N          Stop task slice at index N.
  --resume               Keep the existing output directory.
  --skip-completed       Skip completed runs when used with --resume.
  --output-dir PATH      Override experiment output directory.
  --experiment-name NAME Override experiment name.
  --repeats N            Override repeat count.
  --config PATH          Use a different experiment config.
  --help                 Show this message.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --condition|--task-limit|--task-start|--task-stop|--experiment-name|--repeats)
      if [ "$#" -lt 2 ]; then
        echo "$1 requires a value" >&2
        exit 2
      fi
      RUN_ARGS+=("$1" "$2")
      shift 2
      ;;
    --output-dir)
      if [ "$#" -lt 2 ]; then
        echo "$1 requires a value" >&2
        exit 2
      fi
      RUN_DIR="$2"
      RUN_ARGS+=("$1" "$2")
      shift 2
      ;;
    --config)
      if [ "$#" -lt 2 ]; then
        echo "$1 requires a value" >&2
        exit 2
      fi
      CONFIG_PATH="$2"
      shift 2
      ;;
    --resume|--skip-completed)
      RUN_ARGS+=("$1")
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cd "${ROOT_DIR}"

if ! command -v openhands >/dev/null 2>&1; then
  echo "openhands is not installed or not on PATH." >&2
  echo "Install it first with: scripts/install_openhands_cli.sh" >&2
  exit 127
fi

if [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${LLM_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY or LLM_API_KEY must be set for OpenHands." >&2
  exit 2
fi

export OPENHANDS_DISABLE_TELEMETRY=1
export LLM_MODEL="${LLM_MODEL:-openai/glm-5.1}"
export LLM_BASE_URL="${LLM_BASE_URL:-https://open.bigmodel.cn/api/coding/paas/v4}"
if [ -z "${DOCKER_HOST:-}" ] && [ -S /mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.proxy.sock ]; then
  export DOCKER_HOST="unix:///mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.proxy.sock"
fi
if [ -n "${EDOS_DOCKER_HOST:-}" ]; then
  DOCKER_ARGS=(--docker-host "${EDOS_DOCKER_HOST}")
elif [ -n "${DOCKER_HOST:-}" ]; then
  DOCKER_ARGS=(--docker-host "${DOCKER_HOST}")
fi
if [ -n "${OPENAI_API_KEY:-}" ] && [ -z "${LLM_API_KEY:-}" ]; then
  export LLM_API_KEY="$OPENAI_API_KEY"
fi

PYTHONPATH="${ROOT_DIR}/src" python -m edos.cli.docker_preflight \
  --config "${CONFIG_PATH}" \
  --output "${RUN_DIR}/docker_preflight.json" \
  "${DOCKER_ARGS[@]}"

PYTHONPATH="${ROOT_DIR}/src" python -m edos.cli.run_experiment \
  --config "${CONFIG_PATH}" \
  "${RUN_ARGS[@]}"
PYTHONPATH="${ROOT_DIR}/src" python -m edos.cli.aggregate_results \
  --run-dir "${RUN_DIR}"
