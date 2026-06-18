import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from edos.cli.run_experiment import (
    apply_cli_overrides,
    archive_existing_output_dir,
    archive_existing_run_dir,
    build_task_material_audit,
    build_run_id,
    is_completed_run,
    select_tasks,
    validate_task_material_statuses,
)
from edos.conditions import ALL_EVALUATION_CONDITIONS
from edos.config import load_experiment_config
from edos.types import ExperimentConfig, TaskSpec


class RunExperimentCliTest(unittest.TestCase):
    def test_apply_cli_overrides_keeps_conditions_and_changes_run_scope(self):
        config = ExperimentConfig(
            name="pilot",
            seed=1,
            output_dir="runs/pilot",
            task_list="tasks.json",
            no_internet=True,
            programbench_root=None,
            workspace_root="workspaces",
            scoring_command=[],
            programbench_eval_command=[],
            programbench_eval_image_tag="task",
            agent_runtime="opencode",
            agent_version="real-cli",
            model="model",
            model_version="model",
            max_steps=9,
            timeout_seconds=600,
            agent_command=[],
            conditions=[],
            repeats=1,
        )

        updated = apply_cli_overrides(
            config,
            experiment_name="repeat",
            output_dir="runs/repeat",
            repeats=3,
        )

        self.assertEqual(updated.name, "repeat")
        self.assertEqual(updated.output_dir, "runs/repeat")
        self.assertEqual(updated.repeats, 3)
        self.assertEqual(updated.model, "model")
        self.assertEqual(updated.conditions, [])

    def test_apply_cli_overrides_clamps_repeat_count(self):
        config = ExperimentConfig(
            name="pilot",
            seed=1,
            output_dir="runs/pilot",
            task_list="tasks.json",
            no_internet=True,
            programbench_root=None,
            workspace_root="workspaces",
            scoring_command=[],
            programbench_eval_command=[],
            programbench_eval_image_tag="task",
            agent_runtime="opencode",
            agent_version="real-cli",
            model="model",
            model_version="model",
            max_steps=9,
            timeout_seconds=600,
            agent_command=[],
            conditions=[],
            repeats=2,
        )

        updated = apply_cli_overrides(config, repeats=0)

        self.assertEqual(updated.repeats, 1)

    def test_build_run_id_uses_opaque_condition_free_suffix(self):
        single = build_run_id(
            task_id="task",
            condition="adaptive",
            target_level="medium",
            verifier_exposure_condition="opencode_skill",
            repeat_label="rep001",
            include_repeat=False,
        )
        repeated = build_run_id(
            task_id="task",
            condition="adaptive",
            target_level="medium",
            verifier_exposure_condition="opencode_skill",
            repeat_label="rep001",
            include_repeat=True,
        )

        self.assertTrue(single.startswith("task__pb_"))
        self.assertTrue(repeated.startswith("task__pb_"))
        self.assertNotEqual(single, repeated)
        for value in [single, repeated]:
            self.assertNotIn("adaptive", value)
            self.assertNotIn("medium", value)
            self.assertNotIn("opencode_skill", value)
            self.assertNotIn("rep001", value)
            self.assertNotIn("edos", value)

    def test_archive_existing_run_dir_moves_stale_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "metadata.json").write_text('{"old": true}\n', encoding="utf-8")

            archived = archive_existing_run_dir(run_dir)

            self.assertIsNotNone(archived)
            self.assertFalse(run_dir.exists())
            self.assertTrue(Path(archived).exists())
            self.assertEqual(
                (Path(archived) / "metadata.json").read_text(encoding="utf-8"),
                '{"old": true}\n',
            )
            self.assertEqual(Path(archived).parent.name, "_archives")

    def test_archive_existing_output_dir_moves_stale_experiment_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "experiment"
            old_run = output_dir / "old_condition_named_run"
            old_run.mkdir(parents=True)
            (old_run / "metadata.json").write_text('{"old": true}\n', encoding="utf-8")

            archived = archive_existing_output_dir(output_dir)

            self.assertIsNotNone(archived)
            self.assertFalse(output_dir.exists())
            self.assertTrue((Path(archived) / "old_condition_named_run" / "metadata.json").exists())
            self.assertEqual(Path(archived).parent.name, "_archives")

    def test_select_tasks_supports_slice_limit_and_shard(self):
        tasks = [
            TaskSpec(task_id=f"task_{index}")
            for index in range(6)
        ]

        selected = select_tasks(
            tasks,
            task_start=1,
            task_stop=6,
            task_limit=4,
            shard_index=1,
            shard_count=2,
        )

        self.assertEqual([task.task_id for task in selected], ["task_2", "task_4"])

    def test_task_material_status_gate_rejects_metadata_only_programbench_tasks(self):
        config = load_experiment_config("configs/experiments/programbench_export_smoke.json")
        tasks = select_tasks(
            [TaskSpec(
                task_id="pb_task",
                docs="ProgramBench instance pb_task from org/repo",
                metadata={
                    "image_name": "programbench/org_1776_repo.abcdef0",
                    "tests_json": "missing/tests.json",
                },
            )],
        )

        audit = build_task_material_audit(experiment=config, tasks=tasks)

        self.assertEqual(
            audit["summary"],
            {"programbench_cleanroom_metadata_only": 1},
        )
        with self.assertRaisesRegex(ValueError, "Task material status check failed"):
            validate_task_material_statuses(
                audit,
                allowed_statuses=["local_complete"],
            )

    def test_task_material_status_gate_accepts_allowed_status(self):
        config = load_experiment_config("configs/experiments/programbench_export_smoke.json")
        audit = {
            "tasks": [
                {
                    "task_id": "pb_task",
                    "task_material_status": "programbench_cleanroom_metadata_only",
                }
            ]
        }

        validate_task_material_statuses(
            audit,
            allowed_statuses=["programbench_cleanroom_metadata_only"],
        )

    def test_task_material_status_gate_accepts_cleanroom_workspace_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests_json = Path(tmp) / "tests.json"
            tests_json.write_text("{}", encoding="utf-8")
            config = load_experiment_config("configs/experiments/programbench_export_smoke.json")
            config = type(config)(
                **{
                    **config.__dict__,
                    "programbench_workspace_source": "cleanroom_image",
                }
            )
            tasks = [
                TaskSpec(
                    task_id="pb_task",
                    docs="ProgramBench instance pb_task from org/repo",
                    metadata={
                        "image_name": "programbench/org_1776_repo.abcdef0",
                        "tests_json": str(tests_json),
                    },
                )
            ]

            audit = build_task_material_audit(experiment=config, tasks=tasks)

            self.assertEqual(audit["summary"], {"programbench_cleanroom_workspace": 1})
            validate_task_material_statuses(
                audit,
                allowed_statuses=["programbench_cleanroom_workspace"],
            )

    def test_is_completed_run_requires_end_marker_and_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            for name in [
                "usage.json",
                "programbench_score.json",
                "failure_label.json",
                "events.jsonl",
            ]:
                (run_dir / name).write_text("{}\n", encoding="utf-8")
            (run_dir / "metadata.json").write_text(
                json.dumps({"run_id": "run", "ended_at": None}) + "\n",
                encoding="utf-8",
            )

            self.assertFalse(is_completed_run(run_dir))

            (run_dir / "metadata.json").write_text(
                json.dumps({"run_id": "run", "ended_at": "2026-05-25T00:00:00Z"}) + "\n",
                encoding="utf-8",
            )

            self.assertTrue(is_completed_run(run_dir))

    def test_run_experiment_resume_skips_completed_run_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "resume_smoke"
            command = [
                sys.executable,
                "-m",
                "edos.cli.run_experiment",
                "--config",
                "configs/experiments/smoke.json",
                "--output-dir",
                str(output_dir),
                "--task-limit",
                "1",
                "--condition",
                "no_attack",
            ]
            first = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            run_dirs = [
                path
                for path in output_dir.iterdir()
                if path.is_dir() and path.name != "_archives"
            ]
            self.assertEqual(len(run_dirs), 1)
            run_dir = run_dirs[0]
            manifest = json.loads(
                (run_dir / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["condition"]["condition"], "no_attack")

            second = subprocess.run(
                command + ["--resume", "--skip-completed"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("skipped=1", second.stdout)
            run_index = json.loads(
                (output_dir / "run_index.json").read_text(encoding="utf-8")
            )
            self.assertEqual(run_index[0]["status"], "skipped")
            self.assertEqual(run_index[0]["skip_reason"], "completed_run_present")
            manifest = json.loads(
                (run_dir / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "skipped")
            self.assertEqual(manifest["skip_reason"], "completed_run_present")
            self.assertFalse((output_dir / "_archives").exists())

    def test_mechanism_ablation_repeat_reuses_pilot_config(self):
        script = Path("scripts/opencode_real_mechanism_ablation_repeat.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "--config configs/experiments/opencode_real_mechanism_ablation_pilot.json",
            script,
        )
        self.assertIn("--experiment-name opencode_real_mechanism_ablation_repeat", script)
        self.assertIn("--output-dir runs/opencode_real_mechanism_ablation_repeat", script)
        self.assertIn("--repeats 3", script)
        self.assertFalse(
            Path("configs/experiments/opencode_real_mechanism_ablation_repeat.json").exists()
        )

        config = load_experiment_config(
            "configs/experiments/opencode_real_mechanism_ablation_pilot.json"
        )
        updated = apply_cli_overrides(
            config,
            experiment_name="opencode_real_mechanism_ablation_repeat",
            output_dir="runs/opencode_real_mechanism_ablation_repeat",
            repeats=3,
        )

        self.assertEqual(updated.name, "opencode_real_mechanism_ablation_repeat")
        self.assertEqual(updated.output_dir, "runs/opencode_real_mechanism_ablation_repeat")
        self.assertEqual(updated.repeats, 3)
        self.assertEqual(config.conditions, updated.conditions)

    def test_opencode_programbench_cleanroom_pilot_requires_cleanroom_material(self):
        config_path = "configs/experiments/opencode_real_programbench_mechanism_cleanroom_pilot.json"
        config = load_experiment_config(config_path)
        script = Path(
            "scripts/opencode_real_programbench_mechanism_cleanroom_pilot.sh"
        ).read_text(encoding="utf-8")

        self.assertEqual(config.programbench_workspace_source, "cleanroom_image")
        self.assertEqual(config.programbench_inference_image_tag, "task_cleanroom")
        self.assertEqual(config.programbench_eval_image_tag, "task")
        self.assertEqual(config.programbench_root, "temp/external_repos/ProgramBench")
        self.assertEqual(config.task_list, "configs/task_splits/programbench_smoke_3.json")
        self.assertEqual(config.agent_runtime, "opencode")
        self.assertEqual(config.model, "bigmodel/glm-5.1")
        self.assertGreaterEqual(len(config.conditions), 26)
        self.assertTrue(self._programbench_pilot_conditions().issubset(
            {item.condition for item in config.conditions}
        ))
        self.assertIn("--require-status programbench_cleanroom_workspace", script)
        self.assertIn(
            "--require-task-material-status programbench_cleanroom_workspace",
            script,
        )
        self.assertIn("edos.cli.docker_preflight", script)
        self.assertIn("EDOS_DOCKER_HOST", script)
        self.assertIn(config_path, script)

    def test_opencode_programbench_cleanroom_pilot30_has_split_recipe_and_preflight(self):
        config_path = "configs/experiments/opencode_real_programbench_mechanism_cleanroom_pilot30.json"
        config = load_experiment_config(config_path)
        script = Path(
            "scripts/opencode_real_programbench_mechanism_cleanroom_pilot30.sh"
        ).read_text(encoding="utf-8")
        recipe = json.loads(
            Path("configs/task_splits/programbench_pilot_30.recipe.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(config.programbench_workspace_source, "cleanroom_image")
        self.assertEqual(config.task_list, "configs/task_splits/programbench_pilot_30.json")
        self.assertEqual(config.agent_runtime, "opencode")
        self.assertEqual(config.model, "bigmodel/glm-5.1")
        self.assertGreaterEqual(len(config.conditions), 26)
        self.assertTrue(self._programbench_pilot_conditions().issubset(
            {item.condition for item in config.conditions}
        ))
        self.assertEqual(recipe["selection"]["limit"], 30)
        self.assertEqual(recipe["selection"]["per_difficulty_limit"], 10)
        self.assertEqual(recipe["selection"]["per_category_limit"], 6)
        self.assertIn("edos.cli.build_programbench_split", script)
        self.assertIn("--limit 30", script)
        self.assertIn("--seed 20260524", script)
        self.assertIn("--per-difficulty-limit 10", script)
        self.assertIn("--per-category-limit 6", script)
        self.assertIn("--require-status programbench_cleanroom_workspace", script)
        self.assertIn("edos.cli.docker_preflight", script)
        self.assertIn("--require-task-material-status programbench_cleanroom_workspace", script)
        self.assertIn(config_path, script)

    def test_config_reads_edos_docker_host_override(self):
        import os

        config_path = "configs/experiments/opencode_real_programbench_mechanism_cleanroom_pilot.json"
        old_value = os.environ.get("EDOS_DOCKER_HOST")
        os.environ["EDOS_DOCKER_HOST"] = "unix:///tmp/edos-docker.sock"
        try:
            config = load_experiment_config(config_path)
        finally:
            if old_value is None:
                os.environ.pop("EDOS_DOCKER_HOST", None)
            else:
                os.environ["EDOS_DOCKER_HOST"] = old_value

        self.assertEqual(config.programbench_docker_host, "unix:///tmp/edos-docker.sock")

    def test_openhands_real_smoke_has_runtime_and_docker_preflight(self):
        config_path = "configs/experiments/openhands_real_smoke.json"
        config = load_experiment_config(config_path)
        script = Path("scripts/openhands_real_smoke.sh").read_text(encoding="utf-8")

        self.assertEqual(config.agent_runtime, "openhands")
        self.assertEqual(config.model, "openai/glm-5.1")
        self.assertEqual(len(config.conditions), 2)
        self.assertIn("command -v openhands", script)
        self.assertIn("OPENAI_API_KEY or LLM_API_KEY", script)
        self.assertIn("edos.cli.docker_preflight", script)
        self.assertIn("EDOS_DOCKER_HOST", script)
        self.assertIn(config_path, script)

    def test_openhands_online_defense_pilot_config_and_wrapper(self):
        config_path = "configs/experiments/openhands_real_online_defense_pilot.json"
        config = load_experiment_config(config_path)
        script = Path("scripts/openhands_real_online_defense_pilot.sh").read_text(
            encoding="utf-8"
        )

        self.assertEqual(config.agent_runtime, "openhands")
        self.assertEqual(config.output_dir, "runs/openhands_real_online_defense_pilot")
        self.assertEqual(len(config.conditions), 3)
        defended = config.conditions[2]
        self.assertEqual(defended.condition, "adaptive_full_medium_online_defended")
        self.assertEqual(defended.entry_surface, "mcp_or_tool_manifest")
        self.assertEqual(defended.online_defense["mode"], "enforce")
        self.assertIn("budget_aware_monitor", defended.online_defense["policies"])
        self.assertIn("openhands_real_smoke.sh", script)
        self.assertIn(config_path, script)
        self.assertIn("runs/openhands_real_online_defense_pilot", script)

    def test_mini_sweagent_online_defense_pilot_is_dry_run_by_default(self):
        script = Path(
            "scripts/mini_sweagent_workflow_enforced_online_defense_pilot.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("DRY_RUN=\"${EDOS_MINI_DRY_RUN:-1}\"", script)
        self.assertIn("adaptive_full_medium_online_defended", script)
        self.assertIn("--online-defense-policy hard_budget_cap", script)
        self.assertIn("--online-defense-policy data_delimiter", script)
        self.assertIn("--online-defense-policy budget_aware_monitor", script)
        self.assertIn("--online-defense-mode enforce", script)
        self.assertIn("raw_defended", script)
        self.assertIn("edos.cli.ingest_mini_sweagent_results", script)

    def _programbench_pilot_conditions(self) -> set[str]:
        excluded = {
            "clean_verifier",
            "clean_surface_clean_verifier",
            "no_attack",
            "no_paginated_report",
        }
        return set(ALL_EVALUATION_CONDITIONS) - excluded


if __name__ == "__main__":
    unittest.main()
