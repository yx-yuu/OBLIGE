import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from edos.programbench.tasks import load_task_list, select_programbench_tasks
from edos.types import TaskSpec


class TaskLoadingTest(unittest.TestCase):
    def test_load_smoke_tasks(self):
        tasks = load_task_list("configs/task_splits/smoke_local.json")
        self.assertGreaterEqual(len(tasks), 1)
        self.assertEqual(tasks[0].task_id, "local_text_cli_easy")

    def test_select_programbench_tasks_supports_stratified_caps(self):
        tasks = [
            TaskSpec(task_id="easy_c_1", difficulty="easy", category="c"),
            TaskSpec(task_id="easy_c_2", difficulty="easy", category="c"),
            TaskSpec(task_id="medium_py_1", difficulty="medium", category="py"),
            TaskSpec(task_id="medium_py_2", difficulty="medium", category="py"),
            TaskSpec(task_id="hard_rs_1", difficulty="hard", category="rs"),
        ]

        selected = select_programbench_tasks(
            tasks,
            seed=7,
            per_difficulty_limit=1,
            per_category_limit=1,
        )

        self.assertLessEqual(
            max(count_by(selected, "difficulty").values()),
            1,
        )
        self.assertLessEqual(
            max(count_by(selected, "category").values()),
            1,
        )
        self.assertEqual(
            [task.task_id for task in selected],
            sorted(task.task_id for task in selected),
        )

    def test_build_programbench_split_cli_writes_selection_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            programbench = root / "ProgramBench"
            self._write_task_yaml(
                programbench,
                "org__easy-c.1111111",
                repository="org/easy-c",
                commit="1111111",
                language="c",
                difficulty="easy",
            )
            self._write_task_yaml(
                programbench,
                "org__medium-py.2222222",
                repository="org/medium-py",
                commit="2222222",
                language="py",
                difficulty="medium",
            )
            self._write_task_yaml(
                programbench,
                "org__hard-rs.3333333",
                repository="org/hard-rs",
                commit="3333333",
                language="rs",
                difficulty="hard",
            )
            self._write_task_yaml(
                programbench,
                "testorg__fixture.4444444",
                repository="testorg/fixture",
                commit="4444444",
                language="c",
                difficulty="easy",
            )
            output = root / "split.json"

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "edos.cli.build_programbench_split",
                    "--programbench-root",
                    str(programbench),
                    "--output",
                    str(output),
                    "--difficulty",
                    "easy",
                    "--difficulty",
                    "medium",
                    "--category",
                    "c",
                    "--category",
                    "py",
                    "--exclude-repository-prefix",
                    "testorg/",
                    "--seed",
                    "20260524",
                    "--limit",
                    "2",
                    "--per-difficulty-limit",
                    "1",
                    "--per-category-limit",
                    "1",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Wrote 2 ProgramBench tasks", completed.stdout)
        self.assertEqual(payload["metadata"]["selection_mode"], "stratified")
        self.assertEqual(payload["metadata"]["difficulty"], ["easy", "medium"])
        self.assertEqual(payload["metadata"]["category"], ["c", "py"])
        self.assertEqual(payload["metadata"]["exclude_repository_prefix"], ["testorg/"])
        self.assertEqual(len(payload["tasks"]), 2)
        self.assertNotIn(
            "testorg/fixture",
            {task["metadata"]["repository"] for task in payload["tasks"]},
        )
        self.assertEqual(
            {task["category"] for task in payload["tasks"]},
            {"c", "py"},
        )

    def _write_task_yaml(
        self,
        programbench_root: Path,
        instance_id: str,
        *,
        repository: str,
        commit: str,
        language: str,
        difficulty: str,
    ) -> None:
        task_dir = programbench_root / "src" / "programbench" / "data" / "tasks" / instance_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "task.yaml").write_text(
            "\n".join(
                [
                    f"repository: {repository}",
                    f"commit: {commit}",
                    f"language: {language}",
                    f"difficulty: {difficulty}",
                    "eval_clean_hashes:",
                    "  - hash",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (task_dir / "tests.json").write_text("{}", encoding="utf-8")


def count_by(tasks: list[TaskSpec], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        value = str(getattr(task, field))
        counts[value] = counts.get(value, 0) + 1
    return counts


if __name__ == "__main__":
    unittest.main()
