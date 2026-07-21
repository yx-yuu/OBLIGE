#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to install OpenHands CLI." >&2
  echo "Install uv first, then rerun this script." >&2
  exit 127
fi

uv tool install openhands --python 3.12
openhands --help

