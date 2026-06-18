import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from edos.analysis.cost_calibration import build_cost_calibration_bundle


class CostCalibrationEvidenceTest(unittest.TestCase):
    def test_bundle_separates_controller_proxy_from_reported_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_aggregate(root)

            paths = build_cost_calibration_bundle(root)

            pairs = self._read_csv(paths["pairs"])
            summary_rows = self._read_csv(paths["summary_table"])
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            boundaries = paths["boundaries"].read_text(encoding="utf-8")

        by_run = {row["run_id"]: row for row in pairs}
        self.assertEqual(len(pairs), 2)
        self.assertEqual(
            by_run["attack"]["calibration_status"],
            "controller_hit_reported_overshoot",
        )
        self.assertEqual(
            by_run["attack_no_baseline"]["calibration_status"],
            "controller_hit_reported_unavailable",
        )
        self.assertEqual(
            by_run["attack"]["reported_to_controller_extra_cost_ratio"],
            "4.0",
        )
        self.assertEqual(summary["controller_target_interval_hit_rate"], 1.0)
        self.assertEqual(summary["reported_token_target_interval_hit_rate"], 0.0)
        self.assertEqual(summary["reported_token_overshoot_rate"], 1.0)
        self.assertEqual(summary["runs_with_reported_token_baseline"], 1)
        self.assertIn("controller hits do not imply reported-token hits", boundaries)

        by_condition = {row["condition"]: row for row in summary_rows}
        self.assertEqual(
            by_condition["adaptive_full_medium"][
                "reported_token_target_interval_hit_rate"
            ],
            "0.0",
        )
        self.assertEqual(
            by_condition["adaptive_no_baseline_medium"][
                "reported_token_target_interval_hit_rate"
            ],
            "",
        )

    def test_cli_writes_cost_calibration_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "bundle"
            self._write_aggregate(root)

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "edos.cli.build_cost_calibration",
                    "--run-dir",
                    str(root),
                    "--output-dir",
                    str(output),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("cost_calibration_pairs.csv", completed.stdout)
            self.assertTrue((output / "cost_calibration_summary.json").exists())

    def _write_aggregate(self, root: Path) -> None:
        aggregate = root / "aggregate"
        self._write_csv(
            aggregate / "runs.csv",
            [
                self._run_row(
                    run_id="clean",
                    condition="clean_skill_clean_verifier",
                    target_level="none",
                    input_tokens="100",
                    output_tokens="0",
                    verifier_calls="1",
                ),
                self._run_row(
                    run_id="attack",
                    condition="adaptive_full_medium",
                    target_level="medium",
                    input_tokens="300",
                    output_tokens="0",
                    verifier_calls="3",
                ),
                self._run_row(
                    run_id="attack_no_baseline",
                    condition="adaptive_no_baseline_medium",
                    target_level="medium",
                    input_tokens="150",
                    output_tokens="0",
                    verifier_calls="2",
                ),
            ],
        )
        self._write_csv(
            aggregate / "metrics.csv",
            [
                {
                    "run_id": "clean",
                    "experiment_name": "cost_test",
                    "repeat_index": "0",
                    "repeat_label": "rep000",
                    "task_id": "task",
                    "agent_runtime": "opencode",
                    "model": "model",
                    "verifier_exposure_condition": "opencode_skill",
                    "entry_surface": "skill",
                    "condition": "clean_skill_clean_verifier",
                    "target_level": "none",
                    "total_tokens_est": "100",
                    "baseline_tokens_est": "100",
                    "extra_tokens_est": "0.0",
                    "cost_amplification_factor": "1.0",
                    "usage_source": "opencode_reported_step_tokens",
                },
                {
                    "run_id": "attack",
                    "experiment_name": "cost_test",
                    "repeat_index": "0",
                    "repeat_label": "rep000",
                    "task_id": "task",
                    "agent_runtime": "opencode",
                    "model": "model",
                    "verifier_exposure_condition": "opencode_skill",
                    "entry_surface": "skill",
                    "condition": "adaptive_full_medium",
                    "target_level": "medium",
                    "total_tokens_est": "300",
                    "baseline_tokens_est": "100",
                    "extra_tokens_est": "200.0",
                    "cost_amplification_factor": "3.0",
                    "input_token_amplification_factor": "3.0",
                    "output_token_amplification_factor": "",
                    "usage_source": "opencode_reported_step_tokens",
                },
                {
                    "run_id": "attack_no_baseline",
                    "experiment_name": "cost_test",
                    "repeat_index": "1",
                    "repeat_label": "rep001",
                    "task_id": "task",
                    "agent_runtime": "opencode",
                    "model": "model",
                    "verifier_exposure_condition": "opencode_skill",
                    "entry_surface": "skill",
                    "condition": "adaptive_no_baseline_medium",
                    "target_level": "medium",
                    "total_tokens_est": "150",
                    "baseline_tokens_est": "0",
                    "extra_tokens_est": "150.0",
                    "cost_amplification_factor": "",
                    "usage_source": "opencode_reported_step_tokens",
                },
            ],
        )
        self._write_csv(
            aggregate / "target_cost_error.csv",
            [
                {
                    "run_id": "attack",
                    "agent_runtime": "opencode",
                    "model": "model",
                    "verifier_exposure_condition": "opencode_skill",
                    "entry_surface": "skill",
                    "repeat_index": "0",
                    "repeat_label": "rep000",
                    "task_id": "task",
                    "condition": "adaptive_full_medium",
                    "target_level": "medium",
                    "baseline_available": "True",
                    "actual_extra_cost_est": "20.0",
                    "controller_estimated_extra_cost": "5.0",
                    "controller_target_cost_error": "0.0",
                    "controller_target_interval_hit": "True",
                    "controller_overshoot": "False",
                    "controller_undershoot": "False",
                    "repair_count": "0",
                    "pagination_count": "1",
                    "cost_proxy_source": "proxy_v1",
                    "target_extra_cost": "5.0",
                    "target_extra_cost_lower": "4.0",
                    "target_extra_cost_upper": "6.0",
                    "target_cost_error": "3.0",
                    "target_interval_hit": "False",
                    "overshoot": "True",
                    "undershoot": "False",
                },
                {
                    "run_id": "attack_no_baseline",
                    "agent_runtime": "opencode",
                    "model": "model",
                    "verifier_exposure_condition": "opencode_skill",
                    "entry_surface": "skill",
                    "repeat_index": "1",
                    "repeat_label": "rep001",
                    "task_id": "task",
                    "condition": "adaptive_no_baseline_medium",
                    "target_level": "medium",
                    "baseline_available": "False",
                    "actual_extra_cost_est": "",
                    "controller_estimated_extra_cost": "5.0",
                    "controller_target_cost_error": "0.0",
                    "controller_target_interval_hit": "True",
                    "controller_overshoot": "False",
                    "controller_undershoot": "False",
                    "repair_count": "1",
                    "pagination_count": "0",
                    "cost_proxy_source": "proxy_v1",
                    "target_extra_cost": "5.0",
                    "target_extra_cost_lower": "4.0",
                    "target_extra_cost_upper": "6.0",
                    "target_cost_error": "",
                    "target_interval_hit": "",
                    "overshoot": "",
                    "undershoot": "",
                },
            ],
        )

    def _run_row(
        self,
        *,
        run_id: str,
        condition: str,
        target_level: str,
        input_tokens: str,
        output_tokens: str,
        verifier_calls: str,
    ) -> dict[str, str]:
        return {
            "run_id": run_id,
            "experiment_name": "cost_test",
            "repeat_index": "0",
            "repeat_label": "rep000",
            "task_id": "task",
            "agent_runtime": "opencode",
            "model": "model",
            "condition": condition,
            "target_level": target_level,
            "verifier_exposure_condition": "opencode_skill",
            "entry_surface": "skill",
            "input_tokens_est": input_tokens,
            "output_tokens_est": output_tokens,
            "usage_source": "opencode_reported_step_tokens",
            "verifier_calls": verifier_calls,
            "candidate_build_success": "True",
            "final_submission_seen": "True",
            "failure_label": "",
        }

    def _write_csv(self, path: Path, rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fields: list[str] = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def _read_csv(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
