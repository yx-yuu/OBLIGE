from __future__ import annotations


ENTRY_SURFACES = frozenset(
    {
        "none",
        "user_prompt",
        "workflow_instruction",
        "skill",
        "mcp_or_tool_manifest",
        "local_command",
        "runtime_hook",
        "file_feedback",
        "verifier_feedback",
        "unknown",
    }
)


EXPOSURE_TO_ENTRY_SURFACE = {
    "no_mention": "none",
    "light_prompt": "user_prompt",
    "user_prompt": "user_prompt",
    "workflow_guided": "workflow_instruction",
    "workflow_instruction": "workflow_instruction",
    "skill": "skill",
    "skill_guided": "skill",
    "opencode_skill": "skill",
    "tool_available": "local_command",
    "local_command": "local_command",
    "tool_or_manifest_guided": "mcp_or_tool_manifest",
    "mcp_or_tool_manifest": "mcp_or_tool_manifest",
    "openhands_mcp": "mcp_or_tool_manifest",
    "workflow_enforced": "runtime_hook",
    "runtime_hook": "runtime_hook",
    "fixed_feedback": "runtime_hook",
    "file_feedback": "file_feedback",
}


def normalize_entry_surface(
    verifier_exposure_condition: str,
    explicit_entry_surface: str | None = None,
) -> str:
    value = (explicit_entry_surface or "").strip()
    if value:
        if value not in ENTRY_SURFACES:
            raise ValueError(f"Unsupported entry_surface: {value}")
        return value
    exposure = (verifier_exposure_condition or "").strip()
    return EXPOSURE_TO_ENTRY_SURFACE.get(exposure, exposure or "unknown")

