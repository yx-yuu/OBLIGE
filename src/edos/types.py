from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ControllerState = str


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    difficulty: str = "unknown"
    category: str = "unknown"
    docs: str = ""
    gold_command: str | None = None
    docs_path: str | None = None
    gold_executable: str | None = None
    workspace_files: list[str] = field(default_factory=list)
    scorer_command: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConditionSpec:
    condition: str
    target_level: str = "none"
    verifier_exposure_condition: str = "unknown"
    entry_surface: str = "unknown"
    surface_artifact: str = ""
    verifier_config_path: str | None = None
    agent_prompt_hint: str = ""
    cost_proxy: dict[str, Any] = field(default_factory=dict)
    online_defense: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    seed: int
    output_dir: str
    task_list: str
    no_internet: bool
    programbench_root: str | None
    workspace_root: str
    scoring_command: list[str]
    programbench_eval_command: list[str]
    programbench_eval_image_tag: str
    agent_runtime: str
    agent_version: str
    model: str
    model_version: str
    max_steps: int
    timeout_seconds: int
    agent_command: list[str]
    conditions: list[ConditionSpec]
    programbench_workspace_source: str = "local"
    programbench_inference_image_tag: str = "task_cleanroom"
    programbench_docker_executable: str = "docker"
    programbench_docker_host: str = ""
    repeats: int = 1
    repeat_index: int = 0
    repeat_label: str = "rep000"


@dataclass
class CostState:
    api_calls: int = 0
    input_tokens_est: int = 0
    output_tokens_est: int = 0
    wall_clock_seconds: float = 0.0
    usage_source: str = "offline_estimate"
    estimated_extra_cost: float = 0.0
    target_extra_cost_lower: float = 0.0
    target_extra_cost_upper: float = 0.0
    cost_proxy_source: str = ""
    cost_proxy_units_per_verifier_call: float = 0.0
    cost_proxy_initial_free_calls: int = 0
    cost_proxy_chargeable_calls: int = 0
    cost_proxy_response_chars_per_unit: float = 0.0
    cost_proxy_projected_response_chars: int = 0
    cost_proxy_response_projection_mode: str = "fixed"
    cost_proxy_response_projection_floor: int = 0
    cost_proxy_response_projection_window: int = 0
    cost_proxy_chargeable_response_chars: int = 0
    cost_proxy_observed_response_chars_before_call: int = 0
    cost_proxy_observed_response_calls_before_call: int = 0


@dataclass
class ContextState:
    context_tokens_est: int = 0
    context_fraction_est: float = 0.0


@dataclass
class TaskProgress:
    has_candidate: bool = False
    has_build_script: bool = False
    last_compile_success: bool = False
    last_candidate_run_seen: bool = False
    first_candidate_turn: int | None = None
    first_build_success_turn: int | None = None
    final_submission_seen: bool = False
    recent_action_distribution: dict[str, int] = field(default_factory=dict)
    verifier_only_streak: int = 0


@dataclass
class VerifierAdoption:
    exposure_condition: str = "unknown"
    skill_exposure_condition: str = "unknown"
    skill_loaded: bool = False
    skill_name: str = ""
    skill_config_hash: str = ""
    first_verifier_call_turn: int | None = None
    verifier_calls_so_far: int = 0
    called_before_first_candidate: bool = False
    called_before_first_build: bool = False


@dataclass
class ControlSignals:
    utility_risk: float = 0.0
    utility_risk_reason: str = ""
    batching_signal: bool = False
    batching_signal_reason: str = ""
    repair_needed: bool = False
    repair_reason: str = ""
    context_growth_slope: float = 0.0


@dataclass
class VerifierRequest:
    run_id: str
    task_id: str
    turn_id: int
    condition: str
    behavior_surface: str
    agent_summary: dict[str, Any]
    cost_state: CostState
    context_state: ContextState
    task_progress: TaskProgress
    verifier_adoption: VerifierAdoption
    control_signals: ControlSignals
    schema_version: str = "1.0"


@dataclass
class ControlDecision:
    prev_state: ControllerState
    next_state: ControllerState
    decision_reason: str
    behavior_surface: str
    node_length_budget: int
    pagination_budget: int
    repair_allowed: bool
    terminate_flag: bool


@dataclass
class VerifierResponse:
    run_id: str
    node_id: str
    parent_node_id: str | None
    branch_id: str
    node_depth: int
    node_status: str
    controller_state: str
    behavior_surface: str
    theory_source: str
    derivation_step: str
    stage_marker: str
    marker_echoed: bool
    latch_state: str
    message: str
    suggested_next_check: str
    pagination: dict[str, Any]
    budget_update: dict[str, Any]
    safety_boundary: dict[str, Any]
    validation_graph: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"


@dataclass
class UsageReport:
    input_tokens_est: int = 0
    output_tokens_est: int = 0
    api_calls: int = 0
    wall_clock_seconds: float = 0.0
    usage_source: str = "offline_estimate"


@dataclass
class RunResult:
    run_id: str
    run_dir: str
    usage: UsageReport
    failure_label: str | None
    score: dict[str, Any]


@dataclass(frozen=True)
class WorkspaceSpec:
    task_id: str
    run_id: str
    workspace_path: str
    docs_path: str | None = None
    gold_executable: str | None = None
    candidate_path: str | None = None
    submission_archive: str | None = None
    task_material_status: str = "unknown"
    task_material_warnings: str = ""
    docs_source_type: str = "none"
    docs_materialized: bool = False
    gold_executable_available: bool = False
    programbench_cleanroom_image: str = ""
    programbench_tests_json: str = ""
    programbench_tests_json_available: bool = False
