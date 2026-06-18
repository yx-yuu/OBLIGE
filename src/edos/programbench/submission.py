from __future__ import annotations

import os
import tarfile
from pathlib import Path


class SubmissionArchiveError(RuntimeError):
    """Raised when a workspace cannot be exported as a ProgramBench submission."""


def create_submission_archive(
    *,
    workspace_path: str | Path,
    output_path: str | Path,
) -> Path:
    workspace = Path(workspace_path)
    compile_script = workspace / "compile.sh"
    if not compile_script.is_file():
        raise SubmissionArchiveError(
            f"ProgramBench submission workspace is missing top-level compile.sh: {workspace}"
        )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_name(f"{output.name}.tmp")
    try:
        with tarfile.open(temp_output, "w:gz") as archive:
            for path in sorted(workspace.rglob("*")):
                if should_skip(path, workspace=workspace):
                    continue
                if path.is_file() and not os.access(path, os.R_OK):
                    raise SubmissionArchiveError(
                        f"ProgramBench submission contains unreadable file: "
                        f"{path.relative_to(workspace)}"
                    )
                archive.add(path, arcname=path.relative_to(workspace), recursive=False)
        temp_output.replace(output)
    except Exception:
        temp_output.unlink(missing_ok=True)
        raise
    return output


def should_skip(path: Path, *, workspace: Path | None = None) -> bool:
    if workspace is not None and path == workspace / "executable":
        return True
    parts = set(path.parts)
    if "__pycache__" in parts or ".git" in parts or ".opencode" in parts:
        return True
    if path.as_posix().endswith("bin/behavior_check"):
        return True
    if path.name in {
        "AGENTS.md",
        "TASK_INSTRUCTIONS.md",
        "edos_workspace_manifest.json",
        "opencode.json",
        "workspace_manifest.json",
        "submission.tar.gz",
    }:
        return True
    return False


def export_programbench_submission(
    *,
    workspace_path: str | Path,
    export_root: str | Path,
    instance_id: str,
) -> Path:
    output = Path(export_root) / instance_id / "submission.tar.gz"
    return create_submission_archive(workspace_path=workspace_path, output_path=output)
