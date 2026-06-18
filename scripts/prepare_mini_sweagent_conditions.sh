#!/usr/bin/env bash
set -euo pipefail

ROOT="${EDOS_MINI_CONDITIONS_ROOT:-runs/mini_sweagent_conditions}"
MINI_ROOT="${EDOS_MINI_SWEAGENT_ROOT:-temp/external_repos/mini-swe-agent}"
CPUS="${EDOS_MINI_DOCKER_CPUS:-2}"
MEMORY="${EDOS_MINI_DOCKER_MEMORY:-2g}"
WORKFLOW_CLEAN_TRIGGER_MAX_CALLS="${EDOS_MINI_WORKFLOW_CLEAN_TRIGGER_MAX_CALLS:-1}"
WORKFLOW_POLLUTED_TRIGGER_MAX_CALLS="${EDOS_MINI_WORKFLOW_POLLUTED_TRIGGER_MAX_CALLS:-5}"

PYTHONPATH=src python -m edos.cli.prepare_mini_sweagent_condition \
  --mini-sweagent-root "${MINI_ROOT}" \
  --output-dir "${ROOT}/no_attack" \
  --condition no_attack \
  --verifier-mode absent \
  --exposure-condition no_mention \
  --docker-cpus "${CPUS}" \
  --memory "${MEMORY}"

PYTHONPATH=src python -m edos.cli.prepare_mini_sweagent_condition \
  --mini-sweagent-root "${MINI_ROOT}" \
  --output-dir "${ROOT}/clean_tool_available" \
  --condition clean_verifier \
  --verifier-mode clean \
  --exposure-condition tool_available \
  --docker-cpus "${CPUS}" \
  --memory "${MEMORY}"

PYTHONPATH=src python -m edos.cli.prepare_mini_sweagent_condition \
  --mini-sweagent-root "${MINI_ROOT}" \
  --output-dir "${ROOT}/clean_light_prompt" \
  --condition clean_verifier \
  --verifier-mode clean \
  --exposure-condition light_prompt \
  --docker-cpus "${CPUS}" \
  --memory "${MEMORY}"

PYTHONPATH=src python -m edos.cli.prepare_mini_sweagent_condition \
  --mini-sweagent-root "${MINI_ROOT}" \
  --output-dir "${ROOT}/clean_skill_guided" \
  --condition clean_skill_clean_verifier \
  --verifier-mode clean \
  --exposure-condition skill_guided \
  --docker-cpus "${CPUS}" \
  --memory "${MEMORY}"

PYTHONPATH=src python -m edos.cli.prepare_mini_sweagent_condition \
  --mini-sweagent-root "${MINI_ROOT}" \
  --output-dir "${ROOT}/clean_workflow_guided" \
  --condition clean_skill_clean_verifier \
  --verifier-mode clean \
  --exposure-condition workflow_guided \
  --docker-cpus "${CPUS}" \
  --memory "${MEMORY}"

PYTHONPATH=src python -m edos.cli.prepare_mini_sweagent_condition \
  --mini-sweagent-root "${MINI_ROOT}" \
  --output-dir "${ROOT}/clean_workflow_enforced" \
  --condition clean_skill_clean_verifier \
  --verifier-mode clean \
  --exposure-condition workflow_enforced \
  --docker-cpus "${CPUS}" \
  --memory "${MEMORY}" \
  --workflow-trigger-max-calls "${WORKFLOW_CLEAN_TRIGGER_MAX_CALLS}" \
  --workflow-trigger-until-closed

PYTHONPATH=src python -m edos.cli.prepare_mini_sweagent_condition \
  --mini-sweagent-root "${MINI_ROOT}" \
  --output-dir "${ROOT}/polluted_tool_available" \
  --condition adaptive_full_medium \
  --verifier-mode polluted \
  --exposure-condition tool_available \
  --docker-cpus "${CPUS}" \
  --memory "${MEMORY}"

PYTHONPATH=src python -m edos.cli.prepare_mini_sweagent_condition \
  --mini-sweagent-root "${MINI_ROOT}" \
  --output-dir "${ROOT}/polluted_workflow_guided" \
  --condition adaptive_full_medium \
  --verifier-mode polluted \
  --exposure-condition workflow_guided \
  --docker-cpus "${CPUS}" \
  --memory "${MEMORY}"

PYTHONPATH=src python -m edos.cli.prepare_mini_sweagent_condition \
  --mini-sweagent-root "${MINI_ROOT}" \
  --output-dir "${ROOT}/polluted_workflow_enforced" \
  --condition adaptive_full_medium \
  --verifier-mode polluted \
  --exposure-condition workflow_enforced \
  --docker-cpus "${CPUS}" \
  --memory "${MEMORY}" \
  --no-workflow-trigger-once \
  --workflow-trigger-max-calls "${WORKFLOW_POLLUTED_TRIGGER_MAX_CALLS}" \
  --workflow-trigger-until-closed
PYTHONPATH=src python -m edos.cli.prepare_mini_sweagent_condition \
  --mini-sweagent-root "${MINI_ROOT}" \
  --output-dir "${ROOT}/polluted_light_prompt" \
  --condition adaptive_full_medium \
  --verifier-mode polluted \
  --exposure-condition light_prompt \
  --docker-cpus "${CPUS}" \
  --memory "${MEMORY}"

PYTHONPATH=src python -m edos.cli.prepare_mini_sweagent_condition \
  --mini-sweagent-root "${MINI_ROOT}" \
  --output-dir "${ROOT}/polluted_skill_guided" \
  --condition adaptive_full_medium \
  --verifier-mode polluted \
  --exposure-condition skill_guided \
  --docker-cpus "${CPUS}" \
  --memory "${MEMORY}"
