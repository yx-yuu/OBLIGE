import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from edos.analysis.evaluation_artifacts import FIGURE_SPECS, TABLE_SPECS
from edos.config import load_experiment_config
from edos.programbench.tasks import load_task_list


class ReviewerQuickstartTest(unittest.TestCase):
    def test_reviewer_config_covers_twenty_tasks_and_full_condition_matrix(self):
        config = load_experiment_config("configs/experiments/reviewer_quick_mock.json")
        smoke = load_experiment_config("configs/experiments/smoke.json")
        tasks = load_task_list("configs/task_splits/reviewer_mock_20.json")
        conditions = [item.condition for item in config.conditions]

        self.assertEqual(config.name, "reviewer_quick_mock")
        self.assertEqual(config.agent_runtime, "mock")
        self.assertEqual(config.task_list, "configs/task_splits/reviewer_mock_20.json")
        self.assertEqual(len(tasks), 20)
        self.assertEqual(len(config.conditions), len(smoke.conditions) + 1)
        for condition in [item.condition for item in smoke.conditions]:
            self.assertIn(condition, conditions)
        self.assertIn("adaptive_full_medium_online_defended", conditions)

    def test_reviewer_quickstart_script_generates_complete_evaluation_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "reviewer_single"
            eval_dir = root / "reviewer_single_eval"
            env = {
                **os.environ,
                "PYTHONPATH": "src",
                "PYTHON": sys.executable,
            }

            completed = subprocess.run(
                [
                    "bash",
                    "scripts/reviewer_quickstart.sh",
                    "1",
                    str(run_dir),
                    str(eval_dir),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((run_dir / "aggregate" / "runs.csv").exists())
            manifest_path = eval_dir / "evaluation_artifacts_manifest.json"
            self.assertTrue(manifest_path.exists())

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(set(manifest["tables"]), {label for label, _, _ in TABLE_SPECS})
            self.assertEqual(set(manifest["figures"]), {label for label, _ in FIGURE_SPECS})
            for label, table in manifest["tables"].items():
                csv_path = Path(table["csv"])
                self.assertTrue(csv_path.exists(), label)
                self.assertGreaterEqual(table["rows"], 1, label)
                self.assertGreater(len(self._read_csv(csv_path)), 0, label)
            for label, figure in manifest["figures"].items():
                self.assertTrue(Path(figure["path"]).exists(), label)

            run_index = json.loads((run_dir / "run_index.json").read_text(encoding="utf-8"))
            config = load_experiment_config("configs/experiments/reviewer_quick_mock.json")
            self.assertEqual(len(run_index), len(config.conditions))
            defense_rows = self._read_csv(eval_dir / "tables" / "table_defense.csv")
            self.assertGreater(len(defense_rows), 0)

    def _read_csv(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
