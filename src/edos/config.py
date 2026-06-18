from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from edos.surfaces import normalize_entry_surface
from edos.types import ConditionSpec, ExperimentConfig


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    raw = load_json(path)
    experiment = raw["experiment"]
    programbench = raw["programbench"]
    agent = raw["agent"]
    condition_defaults = raw.get("condition_defaults", {})
    if not isinstance(condition_defaults, dict):
        condition_defaults = {}
    conditions = [
        build_condition_spec(item, condition_defaults)
        for item in raw["conditions"]
    ]
    return ExperimentConfig(
        name=experiment["name"],
        seed=int(experiment.get("seed", 0)),
        output_dir=experiment["output_dir"],
        task_list=programbench["task_list"],
        no_internet=bool(programbench.get("no_internet", True)),
        programbench_root=programbench.get("root"),
        workspace_root=programbench.get("workspace_root", "runs/workspaces"),
        scoring_command=programbench.get("scoring_command", []),
        programbench_eval_command=programbench.get("eval_command", []),
        programbench_eval_image_tag=programbench.get("eval_image_tag", "task"),
        programbench_workspace_source=programbench.get("workspace_source", "local"),
        programbench_inference_image_tag=programbench.get(
            "inference_image_tag", "task_cleanroom"
        ),
        programbench_docker_executable=programbench.get("docker_executable", "docker"),
        programbench_docker_host=os.environ.get(
            "EDOS_DOCKER_HOST", programbench.get("docker_host", "")
        ),
        agent_runtime=agent.get("runtime", "mock"),
        agent_version=agent.get("version", "mock"),
        model=agent.get("model", "mock-model"),
        model_version=agent.get("model_version", "mock"),
        max_steps=int(agent.get("max_steps", 20)),
        timeout_seconds=int(agent.get("timeout_seconds", 300)),
        agent_command=agent.get("command", []),
        conditions=conditions,
        repeats=max(1, int(experiment.get("repeats", 1))),
    )


def stable_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def build_condition_spec(
    item: dict[str, Any],
    defaults: dict[str, Any],
) -> ConditionSpec:
    if "cost_proxy" in item:
        cost_proxy = dict(item.get("cost_proxy") or {})
    else:
        cost_proxy = dict(defaults.get("cost_proxy", {}) or {})
    if "online_defense" in item:
        online_defense = dict(item.get("online_defense") or {})
    else:
        online_defense = dict(defaults.get("online_defense", {}) or {})
    verifier_exposure_condition = item.get(
        "verifier_exposure_condition",
        defaults.get("verifier_exposure_condition", "unknown"),
    )
    entry_surface = normalize_entry_surface(
        verifier_exposure_condition,
        item.get("entry_surface", defaults.get("entry_surface")),
    )
    return ConditionSpec(
        condition=item["condition"],
        target_level=item.get("target_level", defaults.get("target_level", "none")),
        verifier_exposure_condition=verifier_exposure_condition,
        entry_surface=entry_surface,
        surface_artifact=item.get(
            "surface_artifact",
            defaults.get("surface_artifact", ""),
        ),
        verifier_config_path=item.get(
            "verifier_config_path",
            defaults.get("verifier_config_path"),
        ),
        agent_prompt_hint=item.get(
            "agent_prompt_hint",
            defaults.get("agent_prompt_hint", ""),
        ),
        cost_proxy=cost_proxy,
        online_defense=online_defense,
    )
