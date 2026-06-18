#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"${ROOT_DIR}/scripts/openhands_real_smoke.sh" \
  --config "${ROOT_DIR}/configs/experiments/openhands_real_online_defense_pilot.json" \
  --output-dir "${ROOT_DIR}/runs/openhands_real_online_defense_pilot" \
  "$@"
