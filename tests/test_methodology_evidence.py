import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from edos.analysis.methodology_evidence import build_methodology_evidence_bundle


class MethodologyEvidenceTest(unittest.TestCase):
    def test_bundle_maps_method_claims_to_logged_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_aggregate(root)
            self._write_run_logs(root)

            paths = build_methodology_evidence_bundle(root)

            claims = self._read_csv(paths["claims"])
            traces = self._read_csv(paths["trace_fields"])
            mechanisms = self._read_csv(paths["mechanisms"])
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            boundaries = paths["boundaries"].read_text(encoding="utf-8")

        by_claim = {row["claim_id"]: row for row in claims}
        self.assertEqual(by_claim["A1"]["coverage_status"], "covered_observed")
        self.assertEqual(by_claim["P3"]["coverage_status"], "covered_observed")
        self.assertEqual(by_claim["P5/RQ2"]["coverage_status"], "covered_observed")
        self.assertEqual(by_claim["A5/P4"]["coverage_status"], "covered_schema_only")
        self.assertEqual(summary["claim_rows"], 9)
        self.assertGreaterEqual(summary["covered_claims"], 3)
        self.assertEqual(summary["runs_with_controller_trace"], 1)
        self.assertIn("run logs expose the mechanism fields", summary["artifact_scope"])
        self.assertIn("Field coverage links methodology claims", boundaries)

        self.assertEqual(len(traces), 1)
        self.assertIn("P3_non_compressible_dependency", traces[0]["theory_source_values"])
        self.assertIn("latch", traces[0]["derivation_step_values"])

        self.assertEqual(len(mechanisms), 1)
        self.assertEqual(mechanisms[0]["condition"], "no_budget_control")
        self.assertEqual(mechanisms[0]["linked_claim_id"], "A6/P5")
        self.assertEqual(mechanisms[0]["mechanism_signal"], "budget_control_ablation_row")

    def test_cli_writes_methodology_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "bundle"
            self._write_aggregate(root)
            self._write_run_logs(root)

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "edos.cli.build_methodology_evidence",
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
            self.assertIn("methodology_claims.csv", completed.stdout)
            self.assertTrue((output / "methodology_evidence_summary.json").exists())

    def _write_aggregate(self, root: Path) -> None:
        aggregate = root / "aggregate"
        self._write_csv(
            aggregate / "runs.csv",
            [
                {
                    "run_id": "attack",
                    "run_dir": str(root / "attack"),
                    "experiment_name": "method_test",
                    "agent_runtime": "opencode",
                    "model": "model",
                    "task_id": "task",
                    "condition": "adaptive_full_medium",
                    "target_level": "medium",
                    "verifier_exposure_condition": "opencode_skill",
                    "entry_surface": "skill",
                    "input_tokens_est": "120",
                    "output_tokens_est": "30",
                    "api_calls": "2",
                    "usage_source": "opencode_reported_step_tokens",
                    "verifier_calls": "2",
                    "first_verifier_call_turn": "3",
                    "task_local_anchor_count": "2",
                    "validation_graph_surface_count": "1",
                    "candidate_build_success": "True",
                    "final_submission_seen": "True",
                    "tests_passed_fraction": "0.7",
                    "failure_label": "",
                    "controller_estimated_extra_cost": "5.0",
                    "target_extra_cost_lower": "4.0",
                    "target_extra_cost_upper": "6.0",
                    "utility_risk": "0.1",
                    "repair_needed": "False",
                    "batching_signal": "True",
                    "validation_graph_node_count": "2",
                    "validation_graph_branch_count": "1",
                    "validation_graph_max_depth": "1",
                    "validation_graph_surface_histogram": '{"stdin_stdout": 2}',
                }
            ],
        )
        self._write_csv(
            aggregate / "target_cost_error.csv",
            [
                {
                    "run_id": "attack",
                    "controller_target_interval_hit": "True",
                    "controller_target_cost_error": "0.0",
                    "target_interval_hit": "False",
                    "target_cost_error": "2.0",
                }
            ],
        )
        self._write_csv(
            aggregate / "ablation.csv",
            [
                {
                    "condition": "no_budget_control",
                    "target_level": "medium",
                    "removed_mechanism": "adaptive_budget_control",
                    "evidence_question": "Does removing budget control increase target-cost instability?",
                    "adaptive_baseline_condition": "adaptive_full_medium",
                    "delta_controller_hit_rate_vs_adaptive": "-1.0",
                    "delta_validation_graph_node_count_vs_adaptive": "1.0",
                    "delta_verifier_calls_vs_adaptive": "2.0",
                    "candidate_build_success_rate": "1.0",
                    "final_submission_rate": "1.0",
                }
            ],
        )
    def _write_run_logs(self, root: Path) -> None:
        current = root / "attack"
        current.mkdir(parents=True, exist_ok=True)
        (current / "usage.json").write_text(
            json.dumps({"usage_source": "opencode_reported_step_tokens"}) + "\n",
            encoding="utf-8",
        )
        (current / "events.jsonl").write_text(
            json.dumps({"event_type": "verifier_call", "turn_id": 3}) + "\n",
            encoding="utf-8",
        )
        (current / "trajectory.jsonl").write_text(
            json.dumps({"turn_id": 3, "message": "verifier response"}) + "\n",
            encoding="utf-8",
        )
        (current / "controller_trace.jsonl").write_text(
            json.dumps(
                {
                    "turn_id": 3,
                    "next_state": "EXPAND",
                    "behavior_surface": "stdin_stdout",
                    "theory_source": "P3_non_compressible_dependency",
                    "derivation_step": "latch",
                    "stage_marker": "PB-CHECK-123",
                    "marker_echoed": True,
                    "latch_state": "active",
                }
            )
            + "\n",
            encoding="utf-8",
        )

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
