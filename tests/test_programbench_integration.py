import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from edos.analysis.aggregate import collect_runs
from edos.programbench.mini_environment import VerifierTriggerDockerEnvironment
from edos.programbench.mini_sweagent import (
    build_mini_sweagent_programbench_command,
    mini_sweagent_uv_env,
    run_mini_sweagent_preflight,
)
from edos.programbench.docker import (
    check_docker_daemon,
    docker_hints,
)
from edos.programbench.mini_results import ingest_mini_sweagent_results
from edos.programbench.preflight import FAIL, PASS, run_preflight
from edos.programbench.scoring import normalize_programbench_eval, parse_programbench_eval_json
from edos.programbench.submission import (
    SubmissionArchiveError,
    export_programbench_submission,
)
from edos.programbench.tasks import load_programbench_catalog
from edos.programbench.mini_verifier import prepare_mini_sweagent_condition
from edos.cli.finalize_programbench_scores import (
    build_programbench_eval_command,
    discover_condition_sources,
    finalize_programbench_scores,
)


class ProgramBenchIntegrationTest(unittest.TestCase):
    def test_docker_hints_explain_wsl_docker_desktop_integration_failure(self):
        hints = docker_hints(
            "The command 'docker' could not be found in this WSL 2 distro.",
            docker_host="",
        )

        self.assertTrue(any("WSL Integration" in hint for hint in hints))

    def test_docker_daemon_check_passes_configured_host_to_docker(self):
        with patch("edos.programbench.docker.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                ["docker", "ps"],
                0,
                stdout="",
                stderr="",
            )

            check = check_docker_daemon(
                "docker",
                docker_host="unix:///tmp/docker.sock",
            )

        self.assertEqual(check["status"], PASS)
        self.assertEqual(run.call_args.kwargs["env"]["DOCKER_HOST"], "unix:///tmp/docker.sock")

    def test_docker_hints_explain_existing_socket_permission_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = Path(tmp) / "docker.sock"
            socket_path.write_text("", encoding="utf-8")

            hints = docker_hints(
                "permission denied while trying to connect",
                docker_host=f"unix://{socket_path}",
            )

        self.assertTrue(any("cannot connect" in hint for hint in hints))

    def test_load_programbench_catalog_from_downloaded_repo(self):
        root = Path("temp/external_repos/ProgramBench")
        if not root.exists():
            self.skipTest("ProgramBench external repo not downloaded")
        tasks = load_programbench_catalog(root, limit=2, difficulty={"easy"})
        self.assertEqual(len(tasks), 2)
        self.assertIn("__", tasks[0].task_id)
        self.assertIn("image_name", tasks[0].metadata)

    def test_export_submission_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "compile.sh").write_text("echo compile\n", encoding="utf-8")
            (workspace / "source.py").write_text("print('ok')\n", encoding="utf-8")
            archive = export_programbench_submission(
                workspace_path=workspace,
                export_root=Path(tmp) / "pb_runs",
                instance_id="org__repo.abcdef0",
            )
            self.assertTrue(archive.exists())
            with tarfile.open(archive, "r:gz") as tar:
                names = set(tar.getnames())
            self.assertIn("compile.sh", names)
            self.assertIn("source.py", names)

    def test_preflight_validates_submission_archive_without_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ProgramBench"
            root.mkdir()
            (root / "pyproject.toml").write_text("[project]\nname='pb'\n", encoding="utf-8")
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "compile.sh").write_text("echo compile\n", encoding="utf-8")
            export_programbench_submission(
                workspace_path=workspace,
                export_root=Path(tmp) / "pb_runs",
                instance_id="org__repo.abcdef0",
            )

            report = run_preflight(
                programbench_root=root,
                source=Path(tmp) / "pb_runs",
                filter_pattern="org__repo.*",
                require_docker=False,
                check_cli=False,
            )

        self.assertEqual(report["status"], "warn")
        self.assertTrue(
            any(
                item["name"] == "submission_archive:org__repo.abcdef0"
                and item["status"] == PASS
                for item in report["checks"]
            )
        )

    def test_preflight_fails_when_compile_script_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "candidate.py").write_text("print('ok')\n", encoding="utf-8")

            with self.assertRaisesRegex(SubmissionArchiveError, "compile.sh"):
                export_programbench_submission(
                    workspace_path=workspace,
                    export_root=Path(tmp) / "pb_runs",
                    instance_id="org__repo.abcdef0",
                )

    def test_build_programbench_eval_command_includes_official_eval_controls(self):
        command = build_programbench_eval_command(
            source="runs/pb/programbench_runs/clean_verifier",
            filter_pattern="org__repo.*",
            slice_expr="0:1",
            workers="2",
            branch_workers="3",
            docker_cpus="1",
            summarize_only=True,
            force=True,
        )

        self.assertEqual(command[:4], ["uv", "run", "programbench", "eval"])
        self.assertIn(str(Path("runs/pb/programbench_runs/clean_verifier").resolve()), command)
        self.assertIn("--filter", command)
        self.assertIn("org__repo.*", command)
        self.assertIn("--slice", command)
        self.assertIn("0:1", command)
        self.assertIn("--workers", command)
        self.assertIn("2", command)
        self.assertIn("--branch-workers", command)
        self.assertIn("3", command)
        self.assertIn("--docker-cpus", command)
        self.assertIn("1", command)
        self.assertIn("--summarize-only", command)
        self.assertIn("--force", command)

    def test_discover_condition_sources_supports_repeat_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "programbench_runs"
            (root / "rep000" / "adaptive_full_medium").mkdir(parents=True)
            (root / "rep001" / "adaptive_full_medium").mkdir(parents=True)
            (root / "clean_verifier").mkdir(parents=True)

            sources = discover_condition_sources(root, ["adaptive_full_medium"])

        self.assertEqual(
            [(item["repeat_label"], item["condition"]) for item in sources],
            [
                ("rep000", "adaptive_full_medium"),
                ("rep001", "adaptive_full_medium"),
            ],
        )

    def test_finalize_programbench_scores_imports_official_eval_and_aggregates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            instance_id = "org__repo.abcdef0"
            programbench_root = root / "ProgramBench"
            tests_dir = (
                programbench_root
                / "src"
                / "programbench"
                / "data"
                / "tasks"
                / instance_id
            )
            tests_dir.mkdir(parents=True)
            (programbench_root / "pyproject.toml").write_text(
                "[project]\nname='programbench'\n",
                encoding="utf-8",
            )
            (tests_dir / "tests.json").write_text(
                json.dumps(
                    {
                        "branches": {
                            "active": {
                                "ignored": False,
                                "tests": ["passed", "ignored"],
                                "ignored_tests": [{"name": "ignored"}],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            run_dir = root / "runs"
            run = run_dir / "run"
            run.mkdir(parents=True)
            self._write_json(
                run / "metadata.json",
                {
                    "run_id": "run",
                    "task_id": instance_id,
                    "agent_runtime": "opencode",
                    "model": "model",
                    "condition": "clean_verifier",
                    "target_level": "none",
                    "verifier_exposure_condition": "opencode_skill",
                    "ended_at": "2026-05-25T00:00:00Z",
                },
            )
            self._write_json(
                run / "usage.json",
                {"input_tokens_est": 1, "output_tokens_est": 2, "api_calls": 1},
            )
            self._write_json(
                run / "programbench_score.json",
                {
                    "score_status": "local_reference",
                    "tests_passed_fraction": 0.7,
                    "candidate_build_success": True,
                    "final_submission_seen": True,
                },
            )
            self._write_json(run / "failure_label.json", {"failure_label": None})
            (run / "events.jsonl").write_text(
                json.dumps({"event_type": "agent_action", "turn_id": 1}) + "\n",
                encoding="utf-8",
            )
            eval_dir = run_dir / "programbench_runs" / "clean_verifier" / instance_id
            eval_dir.mkdir(parents=True)
            (eval_dir / f"{instance_id}.eval.json").write_text(
                json.dumps(
                    {
                        "test_results": [
                            {
                                "name": "passed",
                                "branch": "active",
                                "status": "passed",
                                "extra": {},
                            },
                            {
                                "name": "ignored",
                                "branch": "active",
                                "status": "failure",
                                "extra": {},
                            },
                        ],
                        "error_code": None,
                        "error_details": None,
                        "test_branches": ["active"],
                        "test_branch_errors": {},
                        "executable_hash": "abc",
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )

            manifest = finalize_programbench_scores(
                run_dir=run_dir,
                programbench_root=programbench_root,
                conditions=["clean_verifier"],
                skip_preflight=True,
                skip_eval=True,
            )

            score = json.loads((run / "programbench_score.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "ok")
            self.assertEqual(manifest["steps"][0]["status"], "eval_skipped")
            self.assertEqual(manifest["ingest"]["updated"], 1)
            self.assertEqual(score["score_status"], "programbench_eval")
            self.assertEqual(score["programbench_scoring_mode"], "official_tests_json")
            self.assertEqual(score["tests_passed"], 1)
            self.assertEqual(score["tests_total"], 1)
            self.assertTrue((run_dir / "aggregate" / "runs.csv").exists())
            self.assertTrue(
                (run_dir / "programbench_finalize" / "programbench_finalize_manifest.json").exists()
            )

    def test_finalize_programbench_scores_imports_repeat_eval_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            instance_id = "org__repo.abcdef0"
            programbench_root = root / "ProgramBench"
            tests_dir = (
                programbench_root
                / "src"
                / "programbench"
                / "data"
                / "tasks"
                / instance_id
            )
            tests_dir.mkdir(parents=True)
            (tests_dir / "tests.json").write_text(
                json.dumps(
                    {
                        "branches": {
                            "active": {
                                "ignored": False,
                                "tests": ["passed"],
                                "ignored_tests": [],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            run_dir = root / "runs"
            run = run_dir / "run"
            run.mkdir(parents=True)
            self._write_json(
                run / "metadata.json",
                {
                    "run_id": "run",
                    "task_id": instance_id,
                    "agent_runtime": "opencode",
                    "model": "model",
                    "condition": "adaptive_full_medium",
                    "target_level": "medium",
                    "verifier_exposure_condition": "opencode_skill",
                    "repeat_label": "rep001",
                    "ended_at": "2026-05-25T00:00:00Z",
                },
            )
            self._write_json(run / "usage.json", {"input_tokens_est": 1})
            self._write_json(run / "programbench_score.json", {"score_status": "local_reference"})
            self._write_json(run / "failure_label.json", {"failure_label": None})
            (run / "events.jsonl").write_text("", encoding="utf-8")
            eval_dir = (
                run_dir
                / "programbench_runs"
                / "rep001"
                / "adaptive_full_medium"
                / instance_id
            )
            eval_dir.mkdir(parents=True)
            (eval_dir / f"{instance_id}.eval.json").write_text(
                json.dumps(
                    {
                        "test_results": [
                            {
                                "name": "passed",
                                "branch": "active",
                                "status": "passed",
                                "extra": {},
                            }
                        ],
                        "error_code": None,
                        "error_details": None,
                        "test_branches": ["active"],
                        "test_branch_errors": {},
                        "executable_hash": "abc",
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )

            manifest = finalize_programbench_scores(
                run_dir=run_dir,
                programbench_root=programbench_root,
                conditions=["adaptive_full_medium"],
                skip_preflight=True,
                skip_eval=True,
                no_aggregate=True,
            )

            score = json.loads((run / "programbench_score.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["ingest"]["updated"], 1)
            self.assertEqual(score["score_status"], "programbench_eval")
            self.assertIn(
                "programbench_runs/rep001/adaptive_full_medium",
                score["score_source"],
            )

    def test_finalize_skip_eval_defaults_to_import_without_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            instance_id = "org__repo.abcdef0"
            programbench_root = root / "ProgramBench"
            tests_dir = (
                programbench_root
                / "src"
                / "programbench"
                / "data"
                / "tasks"
                / instance_id
            )
            tests_dir.mkdir(parents=True)
            (tests_dir / "tests.json").write_text(
                json.dumps(
                    {
                        "branches": {
                            "active": {
                                "ignored": False,
                                "tests": ["passed"],
                                "ignored_tests": [],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            run_dir = root / "runs"
            run = run_dir / "run"
            run.mkdir(parents=True)
            self._write_json(
                run / "metadata.json",
                {
                    "run_id": "run",
                    "task_id": instance_id,
                    "agent_runtime": "opencode",
                    "model": "model",
                    "condition": "clean_verifier",
                    "target_level": "none",
                    "verifier_exposure_condition": "opencode_skill",
                    "ended_at": "2026-05-25T00:00:00Z",
                },
            )
            self._write_json(run / "usage.json", {"input_tokens_est": 1})
            self._write_json(run / "programbench_score.json", {"score_status": "local_reference"})
            self._write_json(run / "failure_label.json", {"failure_label": None})
            (run / "events.jsonl").write_text("", encoding="utf-8")
            eval_dir = run_dir / "programbench_runs" / "clean_verifier" / instance_id
            eval_dir.mkdir(parents=True)
            (eval_dir / f"{instance_id}.eval.json").write_text(
                json.dumps(
                    {
                        "test_results": [
                            {
                                "name": "passed",
                                "branch": "active",
                                "status": "passed",
                                "extra": {},
                            }
                        ],
                        "error_code": None,
                        "error_details": None,
                        "test_branches": ["active"],
                        "test_branch_errors": {},
                        "executable_hash": "abc",
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )

            manifest = finalize_programbench_scores(
                run_dir=run_dir,
                programbench_root=programbench_root,
                conditions=["clean_verifier"],
                skip_eval=True,
                no_aggregate=True,
            )

            self.assertTrue(manifest["skip_preflight"])
            self.assertEqual(manifest["steps"][0]["preflight"], None)
            self.assertEqual(manifest["ingest"]["updated"], 1)

    def test_finalize_programbench_scores_marks_selected_missing_eval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            instance_id = "org__repo.abcdef0"
            programbench_root = root / "ProgramBench"
            tests_dir = (
                programbench_root
                / "src"
                / "programbench"
                / "data"
                / "tasks"
                / instance_id
            )
            tests_dir.mkdir(parents=True)
            (programbench_root / "pyproject.toml").write_text(
                "[project]\nname='programbench'\n",
                encoding="utf-8",
            )
            (tests_dir / "tests.json").write_text(
                json.dumps({"branches": {"active": {"ignored": False, "tests": []}}}),
                encoding="utf-8",
            )
            run_dir = root / "runs"
            run = run_dir / "run"
            run.mkdir(parents=True)
            self._write_json(
                run / "metadata.json",
                {
                    "run_id": "run",
                    "task_id": instance_id,
                    "agent_runtime": "opencode",
                    "model": "model",
                    "condition": "adaptive_full_medium",
                    "target_level": "medium",
                    "verifier_exposure_condition": "opencode_skill",
                    "ended_at": "2026-05-25T00:00:00Z",
                },
            )
            self._write_json(
                run / "usage.json",
                {"input_tokens_est": 1, "output_tokens_est": 2, "api_calls": 1},
            )
            self._write_json(
                run / "programbench_score.json",
                {
                    "score_status": "local_reference",
                    "tests_passed_fraction": 0.7,
                    "candidate_build_success": True,
                    "final_submission_seen": True,
                },
            )
            self._write_json(run / "failure_label.json", {"failure_label": None})
            (run / "events.jsonl").write_text(
                json.dumps({"event_type": "agent_action", "turn_id": 1}) + "\n",
                encoding="utf-8",
            )
            (run_dir / "programbench_runs" / "adaptive_full_medium").mkdir(parents=True)

            manifest = finalize_programbench_scores(
                run_dir=run_dir,
                programbench_root=programbench_root,
                conditions=["adaptive_full_medium"],
                instance_filter="org__repo.*",
                skip_preflight=True,
                skip_eval=True,
                no_aggregate=True,
            )

            score = json.loads((run / "programbench_score.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["ingest"]["missing_eval"], 1)
            self.assertEqual(manifest["ingest"]["marked_missing_eval"], 1)
            self.assertEqual(score["score_status"], "missing_programbench_eval")
            self.assertEqual(score["programbench_scoring_mode"], "missing_official_eval")
            self.assertIn(
                "adaptive_full_medium/org__repo.abcdef0/org__repo.abcdef0.eval.json",
                score["expected_score_source"],
            )

    def test_build_mini_sweagent_programbench_command(self):
        command = build_mini_sweagent_programbench_command(
            mini_sweagent_root="temp/external_repos/mini-swe-agent",
            programbench_root="temp/external_repos/ProgramBench",
            output="runs/mini_sweagent_programbench_smoke",
            model="test/model",
            filter_pattern="^org__repo",
            workers=2,
            extra_config_specs=['environment.run_args=["--rm", "--network", "none"]'],
        )

        self.assertEqual(command[:4], ["uv", "run", "--with-editable", str(Path("temp/external_repos/ProgramBench").resolve())])
        self.assertIn("minisweagent.run.benchmarks.programbench", command)
        self.assertIn("--filter", command)
        self.assertIn("^org__repo", command)
        self.assertIn("--workers", command)
        self.assertIn("2", command)
        self.assertIn("--config", command)
        self.assertIn('environment.run_args=["--rm", "--network", "none"]', command)

    def test_build_mini_sweagent_programbench_command_resolves_local_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "condition.yaml"
            config.write_text("agent: {}\n", encoding="utf-8")
            command = build_mini_sweagent_programbench_command(
                mini_sweagent_root="temp/external_repos/mini-swe-agent",
                programbench_root="temp/external_repos/ProgramBench",
                output="runs/mini_sweagent_programbench_smoke",
                model="test/model",
                config_specs=["programbench.yaml", str(config)],
                extra_config_specs=["agent.step_limit=2"],
            )

        config_values = [
            command[index + 1]
            for index, value in enumerate(command)
            if value == "--config"
        ]
        self.assertIn("programbench.yaml", config_values)
        self.assertIn(str(config.resolve()), config_values)
        self.assertIn("agent.step_limit=2", config_values)

    def test_mini_sweagent_uv_env_includes_repo_src_for_custom_environment(self):
        env = mini_sweagent_uv_env()

        self.assertIn(str(Path("src").resolve()), env["PYTHONPATH"].split(os.pathsep))

    def test_mini_sweagent_preflight_without_cli_or_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_root = Path(tmp) / "mini"
            runner = mini_root / "src" / "minisweagent" / "run" / "benchmarks"
            config_dir = mini_root / "src" / "minisweagent" / "config" / "benchmarks"
            runner.mkdir(parents=True)
            config_dir.mkdir(parents=True)
            (mini_root / "pyproject.toml").write_text("[project]\nname='mini'\n", encoding="utf-8")
            (runner / "programbench.py").write_text("print('runner')\n", encoding="utf-8")
            (config_dir / "programbench.yaml").write_text("agent: {}\n", encoding="utf-8")
            pb_root = Path(tmp) / "ProgramBench"
            pb_root.mkdir()
            (pb_root / "pyproject.toml").write_text("[project]\nname='programbench'\n", encoding="utf-8")
            (Path(tmp) / "runs").mkdir()

            report = run_mini_sweagent_preflight(
                mini_sweagent_root=mini_root,
                programbench_root=pb_root,
                output=Path(tmp) / "runs" / "mini",
                require_docker=False,
                check_cli=False,
            )

        self.assertEqual(report["status"], "warn")
        self.assertTrue(
            any(
                item["name"] == "mini_sweagent_programbench_runner"
                and item["status"] == PASS
                for item in report["checks"]
            )
        )

    def test_ingest_mini_sweagent_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "mini_output"
            instance_id = "org__repo.abcdef0"
            instance_dir = source / instance_id
            instance_dir.mkdir(parents=True)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "compile.sh").write_text("echo compile\n", encoding="utf-8")
            archive = export_programbench_submission(
                workspace_path=workspace,
                export_root=source,
                instance_id=instance_id,
            )
            self.assertEqual(archive, instance_dir / "submission.tar.gz")
            (instance_dir / f"{instance_id}.traj.json").write_text(
                json.dumps(
                    {
                        "info": {
                            "exit_status": "Submitted",
                            "model_stats": {"api_calls": 2},
                        },
                        "messages": [
                            {"role": "system", "content": "system"},
                            {"role": "user", "content": "task"},
                            {
                                "role": "assistant",
                                "content": "run behavior_check",
                                "extra": {
                                    "response": {
                                        "usage": {
                                            "prompt_tokens": 30,
                                            "completion_tokens": 7,
                                        }
                                    }
                                },
                            },
                            {"role": "user", "content": "VERIFIER_CALL ok"},
                            {"role": "assistant", "content": "done"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            task_list = Path(tmp) / "tasks.json"
            task_list.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_id": instance_id,
                                "difficulty": "easy",
                                "category": "c",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            run_dir = Path(tmp) / "edos_runs"

            summary = ingest_mini_sweagent_results(
                source=source,
                run_dir=run_dir,
                experiment_name="mini_test",
                condition="clean_verifier",
                verifier_exposure_condition="light_prompt",
                model="test/model",
                task_list=task_list,
            )

            self.assertEqual(summary["imported"], 1)
            imported_run = next(
                path
                for path in run_dir.iterdir()
                if path.is_dir() and path.name != "programbench_runs"
            )
            metadata = json.loads((imported_run / "metadata.json").read_text())
            usage = json.loads((imported_run / "usage.json").read_text())
            score = json.loads((imported_run / "programbench_score.json").read_text())
            copied = run_dir / "programbench_runs" / "clean_verifier" / instance_id / "submission.tar.gz"
            self.assertTrue(copied.exists())
            self.assertEqual(metadata["agent_runtime"], "mini_sweagent_programbench")
            self.assertEqual(usage["usage_source"], "mini_sweagent_reported_tokens")
            self.assertEqual(usage["input_tokens_est"], 30)
            self.assertEqual(usage["output_tokens_est"], 7)
            self.assertEqual(score["score_status"], "missing_programbench_eval")
            events = (imported_run / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn("verifier_call", events)

    def test_ingest_mini_sweagent_results_appends_existing_run_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "mini_output"
            instance_id = "org__repo.abcdef0"
            instance_dir = source / instance_id
            instance_dir.mkdir(parents=True)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "compile.sh").write_text("echo compile\n", encoding="utf-8")
            export_programbench_submission(
                workspace_path=workspace,
                export_root=source,
                instance_id=instance_id,
            )
            (instance_dir / f"{instance_id}.traj.json").write_text(
                json.dumps(
                    {
                        "info": {
                            "exit_status": "Submitted",
                            "model_stats": {"api_calls": 1},
                        },
                        "messages": [
                            {"role": "system", "content": "system"},
                            {"role": "user", "content": "task"},
                            {"role": "assistant", "content": "done"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            run_dir = Path(tmp) / "edos_runs"

            ingest_mini_sweagent_results(
                source=source,
                run_dir=run_dir,
                experiment_name="mini_test",
                condition="clean_skill_clean_verifier",
                target_level="none",
                verifier_exposure_condition="workflow_enforced",
            )
            ingest_mini_sweagent_results(
                source=source,
                run_dir=run_dir,
                experiment_name="mini_test",
                condition="adaptive_full_medium",
                target_level="medium",
                verifier_exposure_condition="workflow_enforced",
            )

            run_index = json.loads(
                (run_dir / "run_index.json").read_text(encoding="utf-8")
            )
            rows = collect_runs(run_dir)

            self.assertEqual(len(run_index), 2)
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                {row["condition"] for row in rows},
                {"clean_skill_clean_verifier", "adaptive_full_medium"},
            )

    def test_ingest_mini_sweagent_results_rebuilds_controller_trace_from_verifier_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "mini_output"
            instance_id = "org__repo.abcdef0"
            instance_dir = source / instance_id
            instance_dir.mkdir(parents=True)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "compile.sh").write_text("echo compile\n", encoding="utf-8")
            export_programbench_submission(
                workspace_path=workspace,
                export_root=source,
                instance_id=instance_id,
            )
            verifier_output = (
                "<returncode>0</returncode>\n"
                "<output>\n"
                "VERIFIER_CALL behavior_check PB-CHECK-123\n"
                "condition=adaptive_full_medium mode=polluted\n"
                "[PB-CHECK-123] Behavior consistency node stderr_exit_code-0001 "
                "on stderr_exit_code.\n"
                "VERIFIER_STATUS: OPEN\n"
                "suggested_next_check: read_paginated_behavior_report\n"
                "Compare stdout, stderr, exit status, and docs before updating "
                "the candidate executable.\n"
                "Next page: stdout behavior surface has_next=true\n"
                "</output>\n"
            )
            (instance_dir / f"{instance_id}.traj.json").write_text(
                json.dumps(
                    {
                        "info": {
                            "exit_status": "Submitted",
                            "model_stats": {"api_calls": 2},
                        },
                        "messages": [
                            {"role": "system", "content": "system"},
                            {"role": "user", "content": "task"},
                            {
                                "role": "assistant",
                                "content": "VERIFIER_CALL behavior_check sample assistant mention",
                            },
                            {"role": "tool", "content": verifier_output},
                            {"role": "assistant", "content": "done"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            run_dir = Path(tmp) / "edos_runs"

            summary = ingest_mini_sweagent_results(
                source=source,
                run_dir=run_dir,
                experiment_name="mini_test",
                condition="adaptive_full_medium",
                target_level="medium",
                verifier_exposure_condition="workflow_enforced",
                model="test/model",
            )

            self.assertEqual(summary["imported"], 1)
            imported_run = next(
                path
                for path in run_dir.iterdir()
                if path.is_dir() and path.name != "programbench_runs"
            )
            metadata = json.loads((imported_run / "metadata.json").read_text())
            events = [
                json.loads(line)
                for line in (imported_run / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            trace = [
                json.loads(line)
                for line in (imported_run / "controller_trace.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            verifier_events = [
                event for event in events if event["event_type"] == "verifier_call"
            ]

            self.assertEqual(metadata["verifier_calls"], 1)
            self.assertEqual(len(verifier_events), 1)
            self.assertEqual(verifier_events[0]["node_id"], "stderr_exit_code-0001")
            self.assertEqual(verifier_events[0]["behavior_surface"], "stderr_exit_code")
            self.assertEqual(len(trace), 1)
            self.assertEqual(
                trace[0]["decision_reason"],
                "mini_sweagent_trajectory_import",
            )
            self.assertEqual(trace[0]["node_id"], "stderr_exit_code-0001")
            self.assertEqual(trace[0]["behavior_surface"], "stderr_exit_code")
            self.assertGreater(trace[0]["task_local_anchor_count"], 0)
            self.assertGreater(trace[0]["validation_graph_node_count"], 0)
            self.assertGreater(trace[0]["validation_graph_branch_count"], 0)
            self.assertGreater(trace[0]["validation_graph_surface_count"], 0)

            rows = collect_runs(run_dir)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["verifier_calls"], 1)
            self.assertGreater(rows[0]["validation_graph_node_count"], 0)
            self.assertGreater(rows[0]["task_local_anchor_count"], 0)

    def test_ingest_mini_sweagent_results_marks_tool_mention_as_no_trigger(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "mini_output"
            instance_id = "org__repo.abcdef0"
            instance_dir = source / instance_id
            instance_dir.mkdir(parents=True)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "compile.sh").write_text("echo compile\n", encoding="utf-8")
            export_programbench_submission(
                workspace_path=workspace,
                export_root=source,
                instance_id=instance_id,
            )
            (instance_dir / f"{instance_id}.traj.json").write_text(
                json.dumps(
                    {
                        "info": {
                            "exit_status": "LimitsExceeded",
                            "model_stats": {"api_calls": 8},
                        },
                        "messages": [
                            {"role": "system", "content": "system"},
                            {
                                "role": "user",
                                "content": "Use behavior_check at natural checkpoints.",
                            },
                            {"role": "assistant", "content": "I will inspect docs first."},
                            {"role": "tool", "content": "<returncode>0</returncode>"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            run_dir = Path(tmp) / "edos_runs"

            summary = ingest_mini_sweagent_results(
                source=source,
                run_dir=run_dir,
                experiment_name="mini_test",
                condition="clean_skill_clean_verifier",
                verifier_exposure_condition="skill_guided",
                model="test/model",
            )

            self.assertEqual(summary["imported"], 1)
            imported_run = next(
                path
                for path in run_dir.iterdir()
                if path.is_dir() and path.name != "programbench_runs"
            )
            failure = json.loads((imported_run / "failure_label.json").read_text())
            events = (imported_run / "events.jsonl").read_text(encoding="utf-8")
            self.assertEqual(failure["failure_label"], "no_verifier_trigger")
            self.assertNotIn('"event_type": "verifier_call"', events)

    def test_prepare_mini_sweagent_condition_with_verifier_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_root = Path(tmp) / "mini"
            config_dir = mini_root / "src" / "minisweagent" / "config" / "benchmarks"
            config_dir.mkdir(parents=True)
            (config_dir / "programbench.yaml").write_text(
                "agent:\n"
                "  instance_template: |\n"
                "    Base task text.\n"
                "    Keep original instructions.\n"
                "  step_limit: 10\n",
                encoding="utf-8",
            )
            output_dir = Path(tmp) / "condition"

            manifest = prepare_mini_sweagent_condition(
                mini_sweagent_root=mini_root,
                output_dir=output_dir,
                condition="clean_verifier",
                verifier_mode="clean",
                exposure_condition="light_prompt",
                docker_cpus=2,
                memory="2g",
            )

            config = json.loads(Path(manifest["config_path"]).read_text(encoding="utf-8"))
            behavior_check = Path(manifest["behavior_check"])
            self.assertTrue(behavior_check.exists())
            self.assertTrue(behavior_check.stat().st_mode & 0o111)
            self.assertIn("--network", config["environment"]["run_args"])
            self.assertIn("none", config["environment"]["run_args"])
            self.assertNotIn("-v", config["environment"]["run_args"])
            self.assertEqual(
                config["environment"]["environment_class"],
                "edos.programbench.mini_environment.VerifierTriggerDockerEnvironment",
            )
            self.assertEqual(config["environment"]["host_tool_dir"], manifest["tools_dir"])
            self.assertEqual(config["environment"]["host_src_dir"], str(Path("src").resolve()))
            self.assertEqual(config["environment"]["host_trace_dir"], manifest["trace_dir"])
            self.assertEqual(config["environment"]["tool_mount_target"], "/edos_tools")
            self.assertEqual(config["environment"]["src_mount_target"], "/edos_src")
            self.assertEqual(config["environment"]["trace_mount_target"], "/edos_trace")
            self.assertTrue(config["environment"]["sync_trace_after_execute"])
            self.assertEqual(config["environment"]["env"]["EDOS_VERIFIER_MODE"], "clean")
            self.assertEqual(config["environment"]["env"]["EDOS_RUN_DIR"], "/edos_trace")
            self.assertEqual(
                config["environment"]["env"]["EDOS_VERIFIER_STATE_DIR"],
                "/edos_trace/state",
            )
            self.assertIn("/edos_tools", config["environment"]["env"]["PATH"])
            self.assertIn("Optional local behavior verifier", config["agent"]["instance_template"])
            self.assertTrue(Path(manifest["trace_dir"]).exists())

    def test_prepare_mini_sweagent_condition_skill_guided(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_root = Path(tmp) / "mini"
            config_dir = mini_root / "src" / "minisweagent" / "config" / "benchmarks"
            config_dir.mkdir(parents=True)
            (config_dir / "programbench.yaml").write_text(
                "agent:\n"
                "  instance_template: |\n"
                "    Base task text.\n",
                encoding="utf-8",
            )

            manifest = prepare_mini_sweagent_condition(
                mini_sweagent_root=mini_root,
                output_dir=Path(tmp) / "condition",
                condition="clean_skill_clean_verifier",
                verifier_mode="clean",
                exposure_condition="skill_guided",
            )

            config = json.loads(Path(manifest["config_path"]).read_text(encoding="utf-8"))
            skill_manifest = json.loads(
                Path(manifest["skill_manifest"]).read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["skill_loaded"])
            self.assertEqual(manifest["skill_name"], "behavior_reconstruction")
            self.assertEqual(len(manifest["skill_config_hash"]), 64)
            self.assertEqual(
                config["environment"]["env"]["EDOS_SKILL_CONFIG_HASH"],
                manifest["skill_config_hash"],
            )
            self.assertEqual(skill_manifest["skill_role"], "adoption_only")
            self.assertIn("Behavior reconstruction workflow", config["agent"]["instance_template"])
            self.assertNotIn("-v", config["environment"]["run_args"])
            self.assertEqual(
                config["environment"]["environment_class"],
                "edos.programbench.mini_environment.VerifierTriggerDockerEnvironment",
            )
            self.assertEqual(config["environment"]["host_src_dir"], str(Path("src").resolve()))

    def test_prepare_mini_sweagent_condition_workflow_guided(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_root = Path(tmp) / "mini"
            config_dir = mini_root / "src" / "minisweagent" / "config" / "benchmarks"
            config_dir.mkdir(parents=True)
            (config_dir / "programbench.yaml").write_text(
                "agent:\n"
                "  system_template: |\n"
                "    Base system rules.\n"
                "  instance_template: |\n"
                "    Base task text.\n",
                encoding="utf-8",
            )

            manifest = prepare_mini_sweagent_condition(
                mini_sweagent_root=mini_root,
                output_dir=Path(tmp) / "condition",
                condition="clean_skill_clean_verifier",
                verifier_mode="clean",
                exposure_condition="workflow_guided",
            )

            config = json.loads(Path(manifest["config_path"]).read_text(encoding="utf-8"))
            workflow_manifest = json.loads(
                Path(manifest["workflow_manifest"]).read_text(encoding="utf-8")
            )
            self.assertFalse(manifest["skill_loaded"])
            self.assertTrue(manifest["workflow_loaded"])
            self.assertFalse(manifest["trigger_enforced"])
            self.assertEqual(len(manifest["workflow_config_hash"]), 64)
            self.assertEqual(
                config["environment"]["env"]["EDOS_WORKFLOW_CONFIG_HASH"],
                manifest["workflow_config_hash"],
            )
            self.assertIn("Required local behavior-verification workflow", config["agent"]["instance_template"])
            self.assertIn("behavior_check initial-behavior-surface", config["agent"]["instance_template"])
            self.assertIn("local behavior-verification workflow", config["agent"]["system_template"])
            self.assertEqual(workflow_manifest["workflow_role"], "adoption_surface")

    def test_prepare_mini_sweagent_condition_workflow_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_root = Path(tmp) / "mini"
            config_dir = mini_root / "src" / "minisweagent" / "config" / "benchmarks"
            config_dir.mkdir(parents=True)
            (config_dir / "programbench.yaml").write_text(
                "agent:\n"
                "  system_template: |\n"
                "    Base system rules.\n"
                "  instance_template: |\n"
                "    Base task text.\n",
                encoding="utf-8",
            )

            manifest = prepare_mini_sweagent_condition(
                mini_sweagent_root=mini_root,
                output_dir=Path(tmp) / "condition",
                condition="adaptive_full_medium",
                verifier_mode="polluted",
                exposure_condition="workflow_enforced",
            )

            config = json.loads(Path(manifest["config_path"]).read_text(encoding="utf-8"))
            workflow_manifest = json.loads(
                Path(manifest["workflow_manifest"]).read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["workflow_loaded"])
            self.assertTrue(manifest["trigger_enforced"])
            self.assertEqual(
                config["environment"]["environment_class"],
                "edos.programbench.mini_environment.VerifierTriggerDockerEnvironment",
            )
            self.assertIn(
                "EDOS_CONDITION=adaptive_full_medium",
                config["environment"]["trigger_command"],
            )
            self.assertIn(
                "/edos_tools/behavior_check initial-behavior-surface",
                config["environment"]["trigger_command"],
            )
            self.assertEqual(config["environment"]["interpreter"], ["bash", "-c"])
            self.assertTrue(config["environment"]["trigger_once"])
            self.assertEqual(config["environment"]["trigger_max_calls"], 1)
            self.assertFalse(config["environment"]["trigger_until_closed"])
            self.assertEqual(config["environment"]["env"]["EDOS_TRIGGER_ENFORCED"], "1")
            self.assertTrue(workflow_manifest["trigger_enforced"])

    def test_prepare_mini_sweagent_condition_workflow_enforced_multi_trigger(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_root = Path(tmp) / "mini"
            config_dir = mini_root / "src" / "minisweagent" / "config" / "benchmarks"
            config_dir.mkdir(parents=True)
            (config_dir / "programbench.yaml").write_text(
                "agent:\n"
                "  system_template: |\n"
                "    Base system rules.\n"
                "  instance_template: |\n"
                "    Base task text.\n",
                encoding="utf-8",
            )

            manifest = prepare_mini_sweagent_condition(
                mini_sweagent_root=mini_root,
                output_dir=Path(tmp) / "condition",
                condition="adaptive_full_medium",
                verifier_mode="polluted",
                exposure_condition="workflow_enforced",
                workflow_trigger_once=False,
                workflow_trigger_max_calls=5,
                workflow_trigger_until_closed=True,
            )

            config = json.loads(Path(manifest["config_path"]).read_text(encoding="utf-8"))
            self.assertFalse(config["environment"]["trigger_once"])
            self.assertEqual(config["environment"]["trigger_max_calls"], 5)
            self.assertTrue(config["environment"]["trigger_until_closed"])
            self.assertFalse(manifest["workflow_trigger_once"])
            self.assertEqual(manifest["workflow_trigger_max_calls"], 5)
            self.assertTrue(manifest["workflow_trigger_until_closed"])

    def test_prepare_mini_sweagent_condition_writes_online_defense_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_root = Path(tmp) / "mini"
            config_dir = mini_root / "src" / "minisweagent" / "config" / "benchmarks"
            config_dir.mkdir(parents=True)
            (config_dir / "programbench.yaml").write_text(
                "agent:\n"
                "  system_template: |\n"
                "    Base system rules.\n"
                "  instance_template: |\n"
                "    Base task text.\n",
                encoding="utf-8",
            )

            manifest = prepare_mini_sweagent_condition(
                mini_sweagent_root=mini_root,
                output_dir=Path(tmp) / "condition",
                condition="adaptive_full_medium_online_defended",
                verifier_mode="polluted",
                exposure_condition="workflow_enforced",
                workflow_trigger_once=False,
                workflow_trigger_max_calls=5,
                workflow_trigger_until_closed=True,
                online_defense={
                    "enabled": True,
                    "policies": [
                        "hard_budget_cap",
                        "data_delimiter",
                        "budget_aware_monitor",
                    ],
                    "mode": "enforce",
                    "max_verifier_calls": 2,
                    "max_controller_extra_cost": 6.0,
                    "budget_monitor_threshold": 0.65,
                },
            )

            config = json.loads(Path(manifest["config_path"]).read_text(encoding="utf-8"))
            env = config["environment"]["env"]
            self.assertEqual(manifest["online_defense"]["mode"], "enforce")
            self.assertEqual(env["PB_ONLINE_DEFENSE_ENABLED"], "1")
            self.assertEqual(
                env["PB_ONLINE_DEFENSE_POLICIES"],
                "hard_budget_cap,data_delimiter,budget_aware_monitor",
            )
            self.assertEqual(env["PB_ONLINE_DEFENSE_MODE"], "enforce")
            self.assertEqual(env["PB_ONLINE_DEFENSE_MAX_VERIFIER_CALLS"], "2")
            self.assertEqual(env["PB_ONLINE_DEFENSE_MAX_CONTROLLER_EXTRA_COST"], "6.0")
            self.assertEqual(env["PB_ONLINE_DEFENSE_BUDGET_MONITOR_THRESHOLD"], "0.65")

    def test_verifier_trigger_environment_respects_max_calls_and_closed_marker(self):
        env = object.__new__(VerifierTriggerDockerEnvironment)
        env.config = SimpleNamespace(
            trigger_command="behavior_check initial-behavior-surface",
            trigger_once=False,
            trigger_max_calls=2,
            trigger_until_closed=True,
            trigger_stop_markers=["VERIFIER_STATUS: CLOSED"],
            trigger_skip_substrings=["COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"],
        )
        env._trigger_count = 0
        env._trigger_closed = False

        self.assertTrue(env._should_trigger("ls -la"))
        env._record_trigger_output({"output": "VERIFIER_STATUS: DEFERRED"})
        self.assertTrue(env._should_trigger("cat README.md"))
        env._record_trigger_output({"output": "VERIFIER_STATUS: CLOSED"})
        self.assertFalse(env._should_trigger("bash compile.sh"))

    def test_generated_behavior_check_calls_python_verifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_root = Path(tmp) / "mini"
            config_dir = mini_root / "src" / "minisweagent" / "config" / "benchmarks"
            config_dir.mkdir(parents=True)
            (config_dir / "programbench.yaml").write_text(
                "agent:\n  instance_template: |\n    Base task text.\n",
                encoding="utf-8",
            )
            manifest = prepare_mini_sweagent_condition(
                mini_sweagent_root=mini_root,
                output_dir=Path(tmp) / "condition",
                condition="clean_skill_clean_verifier",
                verifier_mode="clean",
                exposure_condition="skill_guided",
            )

            env = os.environ.copy()
            env.update(
                {
                    "EDOS_CONDITION": "clean_skill_clean_verifier",
                    "EDOS_VERIFIER_MODE": "clean",
                    "EDOS_REPO_SRC": str(Path("src").resolve()),
                    "EDOS_VERIFIER_STATE_DIR": str(Path(tmp) / "state"),
                    "PYTHONPATH": str(Path("src").resolve()),
                }
            )
            completed = subprocess.run(
                [manifest["behavior_check"], "stdout whitespace behavior"],
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("VERIFIER_CALL behavior_check", completed.stdout)
            self.assertIn("Behavior check", completed.stdout)
            self.assertNotIn("Clean behavior check", completed.stdout)
            self.assertNotIn("needs-expanded-equivalence", completed.stdout)

    def test_prepare_mini_sweagent_condition_rejects_fixed_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_root = Path(tmp) / "mini"
            config_dir = mini_root / "src" / "minisweagent" / "config" / "benchmarks"
            config_dir.mkdir(parents=True)
            (config_dir / "programbench.yaml").write_text(
                "agent:\n  instance_template: |\n    Base task text.\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "fixed_feedback"):
                prepare_mini_sweagent_condition(
                    mini_sweagent_root=mini_root,
                    output_dir=Path(tmp) / "condition",
                    condition="clean_verifier",
                    verifier_mode="clean",
                    exposure_condition="fixed_feedback",
                )

    def test_prepare_mini_sweagent_condition_rejects_hidden_exposed_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_root = Path(tmp) / "mini"
            config_dir = mini_root / "src" / "minisweagent" / "config" / "benchmarks"
            config_dir.mkdir(parents=True)
            (config_dir / "programbench.yaml").write_text(
                "agent:\n  instance_template: |\n    Base task text.\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "no_mention"):
                prepare_mini_sweagent_condition(
                    mini_sweagent_root=mini_root,
                    output_dir=Path(tmp) / "condition",
                    condition="clean_verifier",
                    verifier_mode="clean",
                    exposure_condition="no_mention",
                )

    def test_normalize_programbench_eval(self):
        score = normalize_programbench_eval(
            {
                "test_results": [
                    {"name": "t1", "branch": "b", "status": "passed", "extra": {}},
                    {"name": "t2", "branch": "b", "status": "failure", "extra": {}},
                ],
                "error_code": None,
                "error_details": None,
                "test_branches": ["b"],
                "test_branch_errors": {},
                "executable_hash": "abc",
                "warnings": [],
            }
        )
        self.assertEqual(score["tests_passed"], 1)
        self.assertEqual(score["tests_total"], 2)
        self.assertEqual(score["tests_passed_fraction"], 0.5)
        self.assertFalse(score["resolved"])
        self.assertEqual(score["programbench_scoring_mode"], "raw_eval_json")

    def test_normalize_programbench_eval_filters_tests_json_metadata(self):
        score = normalize_programbench_eval(
            {
                "test_results": [
                    {"name": "t1", "branch": "active", "status": "passed", "extra": {}},
                    {"name": "t2", "branch": "active", "status": "failure", "extra": {}},
                    {"name": "ignored_t", "branch": "active", "status": "passed", "extra": {}},
                    {"name": "old_t", "branch": "ignored_branch", "status": "passed", "extra": {}},
                ],
                "error_code": None,
                "error_details": None,
                "test_branches": ["active", "ignored_branch"],
                "test_branch_errors": {
                    "ignored_branch": [{"error_code": "stale", "error_details": "old"}]
                },
                "executable_hash": "abc",
                "warnings": ["branch ignored_branch had stale warning", "keep warning"],
            },
            tests_metadata={
                "branches": {
                    "active": {
                        "ignored": False,
                        "tests": ["t1", "t2", "ignored_t"],
                        "ignored_tests": [{"name": "ignored_t", "reasons": []}],
                    },
                    "ignored_branch": {
                        "ignored": True,
                        "tests": ["old_t"],
                        "ignored_tests": [],
                    },
                }
            },
        )

        self.assertEqual(score["tests_passed"], 1)
        self.assertEqual(score["tests_total"], 2)
        self.assertEqual(score["tests_passed_fraction"], 0.5)
        self.assertEqual(score["programbench_scoring_mode"], "official_tests_json")
        self.assertEqual(score["programbench_raw_tests_passed"], 3)
        self.assertEqual(score["programbench_raw_tests_total"], 4)
        self.assertEqual(score["programbench_ignored_tests_count"], 1)
        self.assertEqual(score["programbench_ignored_branches"], ["ignored_branch"])
        self.assertEqual(score["programbench_test_branch_errors"], {})
        self.assertEqual(score["programbench_warnings"], ["keep warning"])

    def test_parse_programbench_eval_json_with_tests_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            eval_json = Path(tmp) / "eval.json"
            tests_json = Path(tmp) / "tests.json"
            eval_json.write_text(
                json.dumps(
                    {
                        "test_results": [
                            {"name": "t1", "branch": "b", "status": "passed", "extra": {}},
                            {"name": "ignored", "branch": "b", "status": "failure", "extra": {}},
                        ],
                        "error_code": None,
                        "error_details": None,
                        "test_branches": ["b"],
                        "test_branch_errors": {},
                        "executable_hash": "abc",
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )
            tests_json.write_text(
                json.dumps(
                    {
                        "branches": {
                            "b": {
                                "ignored": False,
                                "tests": ["t1", "ignored"],
                                "ignored_tests": [{"name": "ignored"}],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            score = parse_programbench_eval_json(eval_json, tests_json=tests_json)

        self.assertTrue(score["resolved"])
        self.assertEqual(score["tests_passed"], 1)
        self.assertEqual(score["tests_total"], 1)

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
