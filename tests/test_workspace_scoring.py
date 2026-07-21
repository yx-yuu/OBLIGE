import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from edos.programbench.submission import (
    SubmissionArchiveError,
    create_submission_archive,
)
from edos.programbench.scoring import parse_score_output
from edos.programbench.workspace import prepare_workspace, preview_task_materials
from edos.types import ExperimentConfig, TaskSpec


def experiment(tmp):
    return ExperimentConfig(
        name="test",
        seed=1,
        output_dir=str(Path(tmp) / "runs"),
        task_list="",
        no_internet=True,
        programbench_root=None,
        workspace_root="workspaces",
        scoring_command=[],
        programbench_eval_command=[],
        programbench_eval_image_tag="task",
        agent_runtime="deterministic_local",
        agent_version="test",
        model="deterministic_local_model",
        model_version="test",
        max_steps=1,
        timeout_seconds=5,
        agent_command=[],
        conditions=[],
    )


class WorkspaceScoringTest(unittest.TestCase):
    def test_prepare_workspace_writes_valid_manifest_and_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = TaskSpec(task_id="task", docs="hello")
            workspace = prepare_workspace(
                experiment=experiment(tmp),
                task=task,
                run_id="run",
                run_dir=str(Path(tmp) / "run"),
            )
            manifest = Path(workspace.workspace_path) / "workspace_manifest.json"
            raw = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(raw["task_id"], "task")
            self.assertFalse(
                (Path(workspace.workspace_path) / "edos_workspace_manifest.json").exists()
            )
            self.assertTrue(Path(workspace.docs_path).exists())
            self.assertEqual(raw["task_material_status"], "local_docs_only")
            self.assertEqual(workspace.task_material_status, "local_docs_only")
            self.assertEqual(workspace.docs_source_type, "inline_task_docs")
            self.assertTrue(workspace.docs_materialized)
            self.assertFalse(workspace.gold_executable_available)

    def test_preview_task_materials_marks_programbench_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            pb_root = Path(tmp) / "ProgramBench"
            task_dir = pb_root / "src" / "programbench" / "data" / "tasks" / "org__repo.abcdef0"
            task_dir.mkdir(parents=True)
            tests_json = task_dir / "tests.json"
            tests_json.write_text("{}", encoding="utf-8")
            config = experiment(tmp)
            config = type(config)(
                **{
                    **config.__dict__,
                    "programbench_root": str(pb_root),
                }
            )
            task = TaskSpec(
                task_id="org__repo.abcdef0",
                docs="ProgramBench instance org__repo.abcdef0 from org/repo",
                metadata={
                    "image_name": "programbench/org_1776_repo.abcdef0",
                    "tests_json": str(tests_json),
                },
            )

            material = preview_task_materials(experiment=config, task=task)

            self.assertEqual(
                material["task_material_status"],
                "programbench_cleanroom_metadata_only",
            )
            self.assertEqual(
                material["docs_source_type"],
                "inline_programbench_metadata_summary",
            )
            self.assertTrue(material["programbench_tests_json_available"])
            self.assertIn(
                "requires_programbench_cleanroom_or_gold_export",
                material["task_material_warnings"],
            )

    def test_preview_task_materials_marks_cleanroom_workspace_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            pb_root = Path(tmp) / "ProgramBench"
            task_dir = pb_root / "src" / "programbench" / "data" / "tasks" / "org__repo.abcdef0"
            task_dir.mkdir(parents=True)
            tests_json = task_dir / "tests.json"
            tests_json.write_text("{}", encoding="utf-8")
            config = experiment(tmp)
            config = type(config)(
                **{
                    **config.__dict__,
                    "programbench_root": str(pb_root),
                    "programbench_workspace_source": "cleanroom_image",
                }
            )
            task = TaskSpec(
                task_id="org__repo.abcdef0",
                docs="ProgramBench instance org__repo.abcdef0 from org/repo",
                metadata={
                    "image_name": "programbench/org_1776_repo.abcdef0",
                    "tests_json": str(tests_json),
                },
            )

            material = preview_task_materials(experiment=config, task=task)

            self.assertEqual(
                material["task_material_status"],
                "programbench_cleanroom_workspace",
            )
            self.assertEqual(
                material["docs_source_type"],
                "programbench_cleanroom_workspace_expected",
            )
            self.assertTrue(material["docs_materialized"])
            self.assertTrue(material["gold_executable_available"])
            self.assertTrue(material["programbench_tests_json_available"])
            self.assertNotIn(
                "requires_programbench_cleanroom_or_gold_export",
                material["task_material_warnings"],
            )

    def test_prepare_workspace_materializes_programbench_cleanroom_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_json = root / "tests.json"
            tests_json.write_text("{}", encoding="utf-8")
            config = experiment(tmp)
            config = type(config)(
                **{
                    **config.__dict__,
                    "programbench_workspace_source": "cleanroom_image",
                    "programbench_inference_image_tag": "task_cleanroom",
                    "programbench_docker_executable": "docker",
                    "programbench_docker_host": "unix:///tmp/docker.sock",
                }
            )
            task = TaskSpec(
                task_id="org__repo.abcdef0",
                docs="ProgramBench instance org__repo.abcdef0 from org/repo",
                metadata={
                    "image_name": "programbench/org_1776_repo.abcdef0",
                    "tests_json": str(tests_json),
                },
            )
            calls = []

            def sample_run(args, **kwargs):
                calls.append((args, kwargs))
                if args[:2] == ["docker", "ps"]:
                    self.assertEqual(
                        kwargs["env"]["DOCKER_HOST"],
                        "unix:///tmp/docker.sock",
                    )
                    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
                if args[:2] == ["docker", "create"]:
                    self.assertIn(
                        "programbench/org_1776_repo.abcdef0:task_cleanroom",
                        args,
                    )
                    self.assertEqual(
                        kwargs["env"]["DOCKER_HOST"],
                        "unix:///tmp/docker.sock",
                    )
                    return subprocess.CompletedProcess(args, 0, stdout="container-1\n", stderr="")
                if args[:2] == ["docker", "cp"]:
                    workspace_path = Path(args[3])
                    (workspace_path / "README.md").write_text(
                        "cleanroom docs\n",
                        encoding="utf-8",
                    )
                    executable = workspace_path / "executable"
                    executable.write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
                    executable.chmod(0o755)
                    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
                if args[:3] == ["docker", "rm", "-f"]:
                    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
                self.fail(f"Unexpected subprocess call: {args}")

            with patch("edos.programbench.workspace.subprocess.run", side_effect=sample_run):
                workspace = prepare_workspace(
                    experiment=config,
                    task=task,
                    run_id="run",
                    run_dir=str(root / "run"),
                )

            workspace_path = Path(workspace.workspace_path)
            manifest = json.loads(
                (workspace_path / "workspace_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                workspace.task_material_status,
                "programbench_cleanroom_workspace",
            )
            self.assertEqual(workspace.docs_source_type, "programbench_cleanroom_workspace")
            self.assertEqual(Path(workspace.docs_path).name, "README.md")
            self.assertEqual(Path(workspace.gold_executable).name, "executable")
            self.assertTrue(workspace.docs_materialized)
            self.assertTrue(workspace.gold_executable_available)
            self.assertFalse((workspace_path / "TASK_DOCS.md").exists())
            self.assertEqual(
                manifest["task_material_status"],
                "programbench_cleanroom_workspace",
            )
            self.assertEqual(
                [call[0][:2] for call in calls],
                [["docker", "ps"], ["docker", "create"], ["docker", "cp"], ["docker", "rm"]],
            )

    def test_prepare_workspace_marks_local_complete_when_docs_and_gold_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "README.md"
            gold = root / "gold"
            docs.write_text("real docs", encoding="utf-8")
            gold.write_text("#!/usr/bin/env bash\necho gold\n", encoding="utf-8")
            task = TaskSpec(
                task_id="task",
                docs_path=str(docs),
                gold_executable=str(gold),
            )

            workspace = prepare_workspace(
                experiment=experiment(tmp),
                task=task,
                run_id="run",
                run_dir=str(root / "run"),
            )

            self.assertEqual(workspace.task_material_status, "local_complete")
            self.assertEqual(workspace.docs_source_type, "file_or_directory")
            self.assertTrue(workspace.gold_executable_available)

    def test_prepare_workspace_archives_existing_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = TaskSpec(task_id="task", docs="fresh docs")
            config = experiment(tmp)
            first = prepare_workspace(
                experiment=config,
                task=task,
                run_id="run",
                run_dir=str(Path(tmp) / "run"),
            )
            first_path = Path(first.workspace_path)
            (first_path / "main.py").write_text("stale\n", encoding="utf-8")
            (first_path / "executable").write_text("stale\n", encoding="utf-8")

            second = prepare_workspace(
                experiment=config,
                task=task,
                run_id="run",
                run_dir=str(Path(tmp) / "run"),
            )
            second_path = Path(second.workspace_path)

            self.assertFalse((second_path / "main.py").exists())
            self.assertFalse((second_path / "executable").exists())
            archives = list(second_path.parent.glob("run_archive_*"))
            self.assertEqual(len(archives), 1)
            self.assertTrue((archives[0] / "main.py").exists())

    def test_parse_score_output_derives_fraction(self):
        score = parse_score_output(
            '{"resolved": false, "tests_passed": 3, "tests_total": 4, '
            '"candidate_build_success": true, "final_submission_seen": true}'
        )
        self.assertEqual(score["tests_passed_fraction"], 0.75)

    def test_scorer_local_accepts_compile_script_without_candidate_py(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "main.py").write_text(
                "#!/usr/bin/env python3\nprint('ok')\n",
                encoding="utf-8",
            )
            compile_script = workspace / "compile.sh"
            compile_script.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "cp main.py executable\n"
                "chmod +x executable\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                ["python3", "scripts/reference_scorer.py", str(workspace)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            score = json.loads(completed.stdout)
            self.assertTrue(score["candidate_build_success"])
            self.assertTrue(score["final_submission_seen"])
            self.assertEqual(score["tests_passed"], 7)

    def test_submission_archive_excludes_agent_runtime_materials(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (workspace / "compile.sh").write_text("echo build\n", encoding="utf-8")
            (workspace / "executable").write_text("#!/bin/sh\necho old\n", encoding="utf-8")
            (workspace / "workspace_manifest.json").write_text("{}\n", encoding="utf-8")
            (workspace / "edos_workspace_manifest.json").write_text("{}\n", encoding="utf-8")
            (workspace / "TASK_INSTRUCTIONS.md").write_text("internal\n", encoding="utf-8")
            (workspace / "AGENTS.md").write_text("internal\n", encoding="utf-8")
            (workspace / "opencode.json").write_text("{}\n", encoding="utf-8")
            (workspace / "bin").mkdir()
            (workspace / "bin" / "behavior_check").write_text("#!/bin/sh\n", encoding="utf-8")
            (workspace / ".opencode" / "tools").mkdir(parents=True)
            (workspace / ".opencode" / "tools" / "behavior_check.ts").write_text(
                "internal\n",
                encoding="utf-8",
            )

            archive = create_submission_archive(
                workspace_path=workspace,
                output_path=Path(tmp) / "submission.tar.gz",
            )

            with tarfile.open(archive, "r:gz") as handle:
                names = set(handle.getnames())
            self.assertIn("main.py", names)
            self.assertIn("compile.sh", names)
            self.assertNotIn("executable", names)
            self.assertNotIn("workspace_manifest.json", names)
            self.assertNotIn("edos_workspace_manifest.json", names)
            self.assertNotIn("TASK_INSTRUCTIONS.md", names)
            self.assertNotIn("AGENTS.md", names)
            self.assertNotIn("opencode.json", names)
            self.assertNotIn("bin/behavior_check", names)
            self.assertFalse(any(name.startswith(".opencode/") for name in names))

    def test_submission_archive_requires_compile_script_before_tar_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "candidate.py").write_text("print('ok')\n", encoding="utf-8")

            with self.assertRaisesRegex(SubmissionArchiveError, "compile.sh"):
                create_submission_archive(
                    workspace_path=workspace,
                    output_path=Path(tmp) / "submission.tar.gz",
                )

            self.assertFalse((Path(tmp) / "submission.tar.gz").exists())


if __name__ == "__main__":
    unittest.main()
