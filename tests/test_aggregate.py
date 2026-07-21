import json
import tempfile
import unittest
from pathlib import Path

from edos.analysis.aggregate import (
    aggregate,
    build_ablation_rows,
    build_metrics_rows,
    build_repeat_summary_rows,
    build_target_rows,
    collect_runs,
)


class AggregateTest(unittest.TestCase):
    def test_collect_runs_uses_run_index_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_run = root / "task__edos_old"
            current_run = root / "task__pb_current"
            self._write_run_dir(
                old_run,
                condition="old_condition",
                input_tokens=100,
                target_extra_cost=0.0,
            )
            self._write_run_dir(
                current_run,
                condition="adaptive_full_medium",
                input_tokens=200,
                target_extra_cost=5.0,
            )
            self._write_json(
                root / "run_index.json",
                [
                    {
                        "run_id": current_run.name,
                        "run_dir": str(current_run),
                        "status": "complete",
                    }
                ],
            )

            rows = collect_runs(root)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run_id"], current_run.name)
        self.assertEqual(rows[0]["condition"], "adaptive_full_medium")

    def test_collect_runs_preserves_controller_budget_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            run_dir.mkdir()
            self._write_json(
                run_dir / "metadata.json",
                {
                    "run_id": "run",
                    "task_id": "task",
                    "agent_runtime": "opencode",
                    "model": "model",
                    "condition": "adaptive_repair_medium",
                    "target_level": "medium",
                    "verifier_exposure_condition": "opencode_skill",
                    "task_material_status": "programbench_cleanroom_metadata_only",
                    "task_material_warnings": "requires_programbench_cleanroom_or_gold_export",
                    "docs_source_type": "inline_programbench_metadata_summary",
                    "docs_materialized": True,
                    "gold_executable_available": False,
                    "programbench_cleanroom_image": "programbench/org_1776_repo.abcdef0",
                    "programbench_tests_json_available": True,
                },
            )
            self._write_json(
                run_dir / "usage.json",
                {
                    "input_tokens_est": 100,
                    "output_tokens_est": 10,
                    "api_calls": 1,
                    "usage_source": "opencode_reported_step_tokens",
                },
            )
            self._write_json(
                run_dir / "programbench_score.json",
                {
                    "tests_passed_fraction": 0.7,
                    "candidate_build_success": True,
                    "final_submission_seen": True,
                },
            )
            self._write_json(run_dir / "failure_label.json", {"failure_label": None})
            (run_dir / "events.jsonl").write_text(
                json.dumps({"event_type": "verifier_call", "turn_id": 3}) + "\n",
                encoding="utf-8",
            )
            (run_dir / "controller_trace.jsonl").write_text(
                json.dumps(
                    {
                        "target_extra_cost": 5.0,
                        "target_extra_cost_lower": 4.0,
                        "target_extra_cost_upper": 6.0,
                        "estimated_extra_cost": 5.0,
                        "repair_count": 1,
                        "pagination_count": 0,
                        "stealth_risk": 0.09,
                        "stealth_risk_reason": "task_local_verifier_feedback",
                        "task_local_anchor_count": 2,
                        "agent_facing_condition_leak": False,
                        "verifier_message_chars": 640,
                        "validation_graph_node_count": 2,
                        "validation_graph_branch_count": 2,
                        "validation_graph_open_node_count": 1,
                        "validation_graph_completed_node_count": 1,
                        "validation_graph_completion_ratio": 0.5,
                        "validation_graph_max_depth": 1,
                        "validation_graph_surface_count": 2,
                        "validation_graph_surface_histogram": {
                            "stdin_stdout": 1,
                            "stderr_exit_code": 1,
                        },
                        "cost_proxy_source": "opencode_repair_budget_proxy_v1",
                        "cost_proxy_units_per_verifier_call": 5.0,
                        "cost_proxy_initial_free_calls": 0,
                        "cost_proxy_chargeable_calls": 1,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            rows = collect_runs(root)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["task_material_status"], "programbench_cleanroom_metadata_only")
        self.assertIn("requires_programbench_cleanroom", row["task_material_warnings"])
        self.assertEqual(row["docs_source_type"], "inline_programbench_metadata_summary")
        self.assertTrue(row["docs_materialized"])
        self.assertFalse(row["gold_executable_available"])
        self.assertEqual(row["programbench_cleanroom_image"], "programbench/org_1776_repo.abcdef0")
        self.assertTrue(row["programbench_tests_json_available"])
        self.assertEqual(row["controller_estimated_extra_cost"], 5.0)
        self.assertEqual(row["controller_target_cost_error"], 0.0)
        self.assertTrue(row["controller_target_interval_hit"])
        self.assertFalse(row["controller_overshoot"])
        self.assertFalse(row["controller_undershoot"])
        self.assertEqual(row["repair_count"], 1)
        self.assertEqual(row["stealth_risk"], 0.09)
        self.assertEqual(row["task_local_anchor_count"], 2)
        self.assertFalse(row["agent_facing_condition_leak"])
        self.assertEqual(row["verifier_message_chars"], 640)
        self.assertEqual(row["validation_graph_node_count"], 2)
        self.assertEqual(row["validation_graph_branch_count"], 2)
        self.assertEqual(row["validation_graph_open_node_count"], 1)
        self.assertEqual(row["validation_graph_completed_node_count"], 1)
        self.assertEqual(row["validation_graph_completion_ratio"], 0.5)
        self.assertEqual(row["validation_graph_max_depth"], 1)
        self.assertEqual(row["validation_graph_surface_count"], 2)
        self.assertEqual(
            row["validation_graph_surface_histogram"],
            '{"stderr_exit_code": 1, "stdin_stdout": 1}',
        )
        self.assertEqual(row["cost_proxy_source"], "opencode_repair_budget_proxy_v1")
        self.assertEqual(row["cost_proxy_chargeable_calls"], 1)

    def test_collect_runs_preserves_programbench_official_score_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            run_dir.mkdir()
            self._write_json(
                run_dir / "metadata.json",
                {
                    "run_id": "run",
                    "task_id": "task",
                    "agent_runtime": "opencode",
                    "model": "model",
                    "condition": "clean_verifier",
                    "target_level": "none",
                    "verifier_exposure_condition": "opencode_skill",
                },
            )
            self._write_json(
                run_dir / "usage.json",
                {
                    "input_tokens_est": 100,
                    "output_tokens_est": 10,
                    "api_calls": 1,
                    "usage_source": "opencode_reported_step_tokens",
                },
            )
            self._write_json(
                run_dir / "programbench_score.json",
                {
                    "tests_passed_fraction": 0.5,
                    "tests_passed": 5,
                    "tests_total": 10,
                    "candidate_build_success": True,
                    "final_submission_seen": True,
                    "score_status": "programbench_eval",
                    "score_source": "programbench_runs/clean/task/task.eval.json",
                    "programbench_scoring_mode": "official_tests_json",
                    "programbench_tests_json": "ProgramBench/tasks/task/tests.json",
                    "programbench_error_code": None,
                    "programbench_ignored_tests_count": 3,
                    "programbench_raw_tests_passed": 8,
                    "programbench_raw_tests_total": 13,
                },
            )
            self._write_json(run_dir / "failure_label.json", {"failure_label": None})
            (run_dir / "events.jsonl").write_text(
                json.dumps({"event_type": "agent_action", "turn_id": 1}) + "\n",
                encoding="utf-8",
            )

            rows = collect_runs(root)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["score_status"], "programbench_eval")
        self.assertEqual(row["score_source"], "programbench_runs/clean/task/task.eval.json")
        self.assertEqual(row["programbench_scoring_mode"], "official_tests_json")
        self.assertEqual(row["programbench_tests_json"], "ProgramBench/tasks/task/tests.json")
        self.assertIsNone(row["programbench_error_code"])
        self.assertEqual(row["programbench_ignored_tests_count"], 3)
        self.assertEqual(row["programbench_raw_tests_passed"], 8)
        self.assertEqual(row["programbench_raw_tests_total"], 13)

    def test_collect_runs_summarizes_mechanisms_across_controller_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            run_dir.mkdir()
            self._write_json(
                run_dir / "metadata.json",
                {
                    "run_id": "run",
                    "task_id": "task",
                    "agent_runtime": "opencode",
                    "model": "model",
                    "condition": "adaptive_full_medium",
                    "target_level": "medium",
                    "verifier_exposure_condition": "opencode_skill",
                },
            )
            self._write_json(
                run_dir / "usage.json",
                {
                    "input_tokens_est": 100,
                    "output_tokens_est": 10,
                    "api_calls": 1,
                    "usage_source": "opencode_reported_step_tokens",
                },
            )
            self._write_json(
                run_dir / "programbench_score.json",
                {
                    "tests_passed_fraction": 0.7,
                    "candidate_build_success": True,
                    "final_submission_seen": True,
                },
            )
            self._write_json(run_dir / "failure_label.json", {"failure_label": None})
            (run_dir / "events.jsonl").write_text(
                "\n".join(
                    json.dumps({"event_type": "verifier_call", "turn_id": turn})
                    for turn in [1, 2, 3]
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "controller_trace.jsonl").write_text(
                "\n".join(
                    json.dumps(row)
                    for row in [
                        {
                            "turn_id": 1,
                            "node_id": "stdin_stdout-0001",
                            "target_extra_cost": 5.0,
                            "target_extra_cost_lower": 4.0,
                            "target_extra_cost_upper": 6.0,
                            "estimated_extra_cost": 2.0,
                            "batching_signal": True,
                            "batching_signal_reason": "matched_batching_phrase:all checks",
                            "pagination_count": 1,
                            "stealth_risk": 0.16,
                            "stealth_risk_reason": "pagination_feedback",
                            "task_local_anchor_count": 3,
                            "agent_facing_condition_leak": True,
                            "verifier_message_chars": 1000,
                            "validation_graph_node_count": 1,
                            "validation_graph_branch_count": 1,
                            "validation_graph_open_node_count": 1,
                            "validation_graph_completed_node_count": 0,
                            "validation_graph_completion_ratio": 0.0,
                            "validation_graph_max_depth": 0,
                            "validation_graph_surface_count": 1,
                            "validation_graph_surface_histogram": {
                                "stdin_stdout": 1,
                            },
                        },
                        {
                            "turn_id": 2,
                            "node_id": "stdin_stdout-0001",
                            "target_extra_cost": 5.0,
                            "target_extra_cost_lower": 4.0,
                            "target_extra_cost_upper": 6.0,
                            "estimated_extra_cost": 4.0,
                            "batching_signal": True,
                            "batching_signal_reason": "matched_batching_phrase:all remaining",
                            "pagination_count": 2,
                            "stealth_risk": 0.2,
                            "stealth_risk_reason": "pagination_feedback;medium_feedback",
                            "task_local_anchor_count": 4,
                            "agent_facing_condition_leak": False,
                            "verifier_message_chars": 900,
                            "validation_graph_node_count": 1,
                            "validation_graph_branch_count": 1,
                            "validation_graph_open_node_count": 1,
                            "validation_graph_completed_node_count": 0,
                            "validation_graph_completion_ratio": 0.0,
                            "validation_graph_max_depth": 0,
                            "validation_graph_surface_count": 1,
                            "validation_graph_surface_histogram": {
                                "stdin_stdout": 1,
                            },
                        },
                        {
                            "turn_id": 3,
                            "node_id": "stdin_stdout-0001",
                            "target_extra_cost": 5.0,
                            "target_extra_cost_lower": 4.0,
                            "target_extra_cost_upper": 6.0,
                            "estimated_extra_cost": 6.0,
                            "batching_signal": False,
                            "batching_signal_reason": "no_batching_signal",
                            "pagination_count": 0,
                            "stealth_risk": 0.08,
                            "stealth_risk_reason": "budget_closed",
                            "task_local_anchor_count": 2,
                            "agent_facing_condition_leak": False,
                            "verifier_message_chars": 320,
                            "validation_graph_node_count": 2,
                            "validation_graph_branch_count": 2,
                            "validation_graph_open_node_count": 1,
                            "validation_graph_completed_node_count": 1,
                            "validation_graph_completion_ratio": 0.5,
                            "validation_graph_max_depth": 1,
                            "validation_graph_surface_count": 2,
                            "validation_graph_surface_histogram": {
                                "stdin_stdout": 1,
                                "stderr_exit_code": 1,
                            },
                        },
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            rows = collect_runs(root)

        row = rows[0]
        self.assertEqual(row["controller_estimated_extra_cost"], 6.0)
        self.assertTrue(row["controller_target_interval_hit"])
        self.assertTrue(row["batching_signal"])
        self.assertIn("all checks", row["batching_signal_reason"])
        self.assertIn("all remaining", row["batching_signal_reason"])
        self.assertEqual(row["pagination_count"], 2)
        self.assertEqual(row["stealth_risk"], 0.2)
        self.assertEqual(row["stealth_risk_reason"], "pagination_feedback;medium_feedback")
        self.assertEqual(row["task_local_anchor_count"], 4)
        self.assertTrue(row["agent_facing_condition_leak"])
        self.assertEqual(row["verifier_message_chars"], 1000)
        self.assertEqual(row["validation_graph_node_count"], 2)
        self.assertEqual(row["validation_graph_branch_count"], 2)
        self.assertEqual(row["validation_graph_open_node_count"], 1)
        self.assertEqual(row["validation_graph_completed_node_count"], 1)
        self.assertEqual(row["validation_graph_completion_ratio"], 0.5)
        self.assertEqual(row["validation_graph_max_depth"], 1)
        self.assertEqual(row["validation_graph_surface_count"], 2)
        self.assertEqual(
            row["validation_graph_surface_histogram"],
            '{"stderr_exit_code": 1, "stdin_stdout": 1}',
        )

    def test_collect_runs_summarizes_online_defense_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            run_dir.mkdir()
            self._write_json(
                run_dir / "metadata.json",
                {
                    "run_id": "run",
                    "task_id": "task",
                    "agent_runtime": "opencode",
                    "model": "model",
                    "condition": "adaptive_full_medium",
                    "target_level": "medium",
                    "verifier_exposure_condition": "opencode_skill",
                },
            )
            self._write_json(
                run_dir / "usage.json",
                {
                    "input_tokens_est": 100,
                    "output_tokens_est": 10,
                    "api_calls": 1,
                    "usage_source": "opencode_reported_step_tokens",
                },
            )
            self._write_json(
                run_dir / "programbench_score.json",
                {
                    "tests_passed_fraction": 0.7,
                    "candidate_build_success": True,
                    "final_submission_seen": True,
                },
            )
            self._write_json(run_dir / "failure_label.json", {"failure_label": None})
            (run_dir / "events.jsonl").write_text(
                "\n".join(
                    json.dumps({"event_type": "verifier_call", "turn_id": turn})
                    for turn in [1, 2]
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "controller_trace.jsonl").write_text(
                "\n".join(
                    json.dumps(row)
                    for row in [
                        {
                            "turn_id": 1,
                            "target_extra_cost": 5.0,
                            "target_extra_cost_lower": 4.0,
                            "target_extra_cost_upper": 6.0,
                            "estimated_extra_cost": 4.0,
                            "online_defense_enabled": True,
                            "online_defense_policy": "data_delimiter",
                            "online_defense_mode": "enforce",
                            "online_defense_action": "transform",
                            "online_defense_would_flag": False,
                            "online_defense_blocked": False,
                            "online_defense_reason": "",
                            "online_defense_message_transform": "data_delimiter",
                            "online_defense_monitor_score": 0.0,
                        },
                        {
                            "turn_id": 2,
                            "target_extra_cost": 5.0,
                            "target_extra_cost_lower": 4.0,
                            "target_extra_cost_upper": 6.0,
                            "estimated_extra_cost": 6.0,
                            "online_defense_enabled": True,
                            "online_defense_policy": "hard_budget_cap,budget_aware_monitor",
                            "online_defense_mode": "enforce",
                            "online_defense_action": "block",
                            "online_defense_would_flag": True,
                            "online_defense_blocked": True,
                            "online_defense_reason": "verifier_calls>1;budget_monitor_score>=0.5",
                            "online_defense_message_transform": "budget_closed",
                            "online_defense_monitor_score": 0.7,
                        },
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            rows = collect_runs(root)

        row = rows[0]
        self.assertTrue(row["online_defense_enabled"])
        self.assertIn("data_delimiter", row["online_defense_policy"])
        self.assertIn("hard_budget_cap", row["online_defense_policy"])
        self.assertEqual(row["online_defense_mode"], "enforce")
        self.assertIn("transform", row["online_defense_action"])
        self.assertIn("block", row["online_defense_action"])
        self.assertTrue(row["online_defense_would_flag"])
        self.assertTrue(row["online_defense_blocked"])
        self.assertEqual(row["online_defense_block_count"], 1)
        self.assertIn("verifier_calls>1", row["online_defense_reason"])
        self.assertIn("data_delimiter", row["online_defense_message_transform"])
        self.assertIn("budget_closed", row["online_defense_message_transform"])
        self.assertEqual(row["online_defense_monitor_score"], 0.7)

    def test_attack_prefers_matching_clean_exposure(self):
        rows = [
            {
                "run_id": "no",
                "task_id": "task",
                "agent_runtime": "deterministic_local",
                "model": "deterministic_local_model",
                "condition": "no_attack",
                "target_level": "none",
                "verifier_exposure_condition": "no_mention",
                "input_tokens_est": 10,
                "output_tokens_est": 0,
                "api_calls": 1,
                "verifier_calls": 0,
                "tests_passed_fraction": 0.7,
                "candidate_build_success": True,
                "final_submission_seen": True,
                "failure_label": None,
                "usage_source": "offline_estimate",
            },
            {
                "run_id": "clean_light",
                "task_id": "task",
                "agent_runtime": "deterministic_local",
                "model": "deterministic_local_model",
                "condition": "clean_verifier",
                "target_level": "none",
                "verifier_exposure_condition": "light_prompt",
                "input_tokens_est": 100,
                "output_tokens_est": 0,
                "api_calls": 2,
                "verifier_calls": 1,
                "tests_passed_fraction": 0.7,
                "candidate_build_success": True,
                "final_submission_seen": True,
                "failure_label": None,
                "usage_source": "offline_estimate",
            },
            {
                "run_id": "clean_tool",
                "task_id": "task",
                "agent_runtime": "deterministic_local",
                "model": "deterministic_local_model",
                "condition": "clean_verifier",
                "target_level": "none",
                "verifier_exposure_condition": "tool_available",
                "input_tokens_est": 50,
                "output_tokens_est": 0,
                "api_calls": 2,
                "verifier_calls": 1,
                "tests_passed_fraction": 0.7,
                "candidate_build_success": True,
                "final_submission_seen": True,
                "failure_label": None,
                "usage_source": "offline_estimate",
            },
            {
                "run_id": "attack",
                "task_id": "task",
                "agent_runtime": "deterministic_local",
                "model": "deterministic_local_model",
                "condition": "adaptive_full_medium",
                "target_level": "medium",
                "verifier_exposure_condition": "light_prompt",
                "input_tokens_est": 250,
                "output_tokens_est": 0,
                "api_calls": 4,
                "verifier_calls": 3,
                "tests_passed_fraction": 0.7,
                "candidate_build_success": True,
                "final_submission_seen": True,
                "failure_label": None,
                "usage_source": "offline_estimate",
                "target_extra_cost": 5.0,
                "target_extra_cost_lower": 4.0,
                "target_extra_cost_upper": 6.0,
                "controller_estimated_extra_cost": 5.0,
                "cost_proxy_source": "opencode_verifier_call_proxy_v1",
                "cost_proxy_units_per_verifier_call": 5.0,
                "cost_proxy_initial_free_calls": 3,
                "cost_proxy_chargeable_calls": 1,
                "cost_proxy_response_chars_per_unit": 1000.0,
                "cost_proxy_projected_response_chars": 1200,
                "cost_proxy_response_projection_mode": "rolling_mean",
                "cost_proxy_response_projection_floor": 320,
                "cost_proxy_response_projection_window": 3,
                "cost_proxy_chargeable_response_chars": 800,
                "cost_proxy_observed_response_chars_before_call": 2000,
                "cost_proxy_observed_response_calls_before_call": 2,
                "cost_proxy_observed_response_chars": 900,
                "cost_proxy_recorded_response_chars_after_call": 1700,
                "cost_proxy_recorded_response_calls_after_call": 1,
                "cost_proxy_recorded_observed_response_chars_after_call": 2900,
                "cost_proxy_recorded_observed_response_calls_after_call": 3,
                "utility_risk": 0.2,
                "utility_risk_reason": "low_observed_utility_risk",
                "repair_needed": True,
                "repair_reason": "matched_repair_phrase:missing",
                "repair_count": 1,
                "batching_signal": True,
                "batching_signal_reason": "matched_batching_phrase:all checks",
                "pagination_count": 2,
                "stealth_risk": 0.11,
                "stealth_risk_reason": "task_local_verifier_feedback",
                "task_local_anchor_count": 3,
                "agent_facing_condition_leak": False,
                "verifier_message_chars": 820,
            },
        ]
        metrics = build_metrics_rows(rows)
        attack = next(row for row in metrics if row["run_id"] == "attack")
        self.assertEqual(attack["baseline_tokens_est"], 100)
        self.assertEqual(attack["extra_tokens_est"], 150.0)

        target_rows = build_target_rows(rows)
        target = next(row for row in target_rows if row["run_id"] == "attack")
        self.assertEqual(target["controller_estimated_extra_cost"], 5.0)
        self.assertEqual(target["controller_target_cost_error"], 0.0)
        self.assertTrue(target["controller_target_interval_hit"])
        self.assertFalse(target["controller_overshoot"])
        self.assertFalse(target["controller_undershoot"])
        self.assertEqual(target["cost_proxy_source"], "opencode_verifier_call_proxy_v1")
        self.assertEqual(target["cost_proxy_chargeable_calls"], 1)
        self.assertEqual(target["cost_proxy_response_chars_per_unit"], 1000.0)
        self.assertEqual(target["cost_proxy_projected_response_chars"], 1200)
        self.assertEqual(target["cost_proxy_response_projection_mode"], "rolling_mean")
        self.assertEqual(target["cost_proxy_response_projection_floor"], 320)
        self.assertEqual(target["cost_proxy_response_projection_window"], 3)
        self.assertEqual(target["cost_proxy_chargeable_response_chars"], 800)
        self.assertEqual(target["cost_proxy_observed_response_chars_before_call"], 2000)
        self.assertEqual(target["cost_proxy_observed_response_calls_before_call"], 2)
        self.assertEqual(target["cost_proxy_observed_response_chars"], 900)
        self.assertEqual(
            target["cost_proxy_recorded_response_chars_after_call"], 1700
        )
        self.assertEqual(
            target["cost_proxy_recorded_response_calls_after_call"], 1
        )
        self.assertEqual(
            target["cost_proxy_recorded_observed_response_chars_after_call"], 2900
        )
        self.assertEqual(
            target["cost_proxy_recorded_observed_response_calls_after_call"], 3
        )
        self.assertEqual(target["utility_risk"], 0.2)
        self.assertEqual(target["utility_risk_reason"], "low_observed_utility_risk")
        self.assertTrue(target["repair_needed"])
        self.assertEqual(target["repair_reason"], "matched_repair_phrase:missing")
        self.assertEqual(target["repair_count"], 1)
        self.assertTrue(target["batching_signal"])
        self.assertEqual(
            target["batching_signal_reason"],
            "matched_batching_phrase:all checks",
        )
        self.assertEqual(target["pagination_count"], 2)
        self.assertEqual(target["stealth_risk"], 0.11)
        self.assertEqual(target["stealth_risk_reason"], "task_local_verifier_feedback")
        self.assertEqual(target["task_local_anchor_count"], 3)
        self.assertFalse(target["agent_facing_condition_leak"])
        self.assertEqual(target["verifier_message_chars"], 820)

    def test_attack_uses_clean_baseline_from_same_repeat(self):
        rows = [
            self._row(
                run_id="clean_rep0",
                condition="clean_skill_clean_verifier",
                target_level="none",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=100,
            ),
            self._row(
                run_id="attack_rep0",
                condition="adaptive_full_medium",
                target_level="medium",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=150,
                target_extra_cost=5.0,
            ),
            self._row(
                run_id="clean_rep1",
                condition="clean_skill_clean_verifier",
                target_level="none",
                exposure="opencode_skill",
                repeat_index=1,
                input_tokens=300,
            ),
            self._row(
                run_id="attack_rep1",
                condition="adaptive_full_medium",
                target_level="medium",
                exposure="opencode_skill",
                repeat_index=1,
                input_tokens=450,
                target_extra_cost=5.0,
            ),
        ]

        metrics = build_metrics_rows(rows)
        rep0 = next(row for row in metrics if row["run_id"] == "attack_rep0")
        rep1 = next(row for row in metrics if row["run_id"] == "attack_rep1")

        self.assertEqual(rep0["baseline_tokens_est"], 100)
        self.assertEqual(rep0["extra_tokens_est"], 50.0)
        self.assertEqual(rep0["repeat_index"], 0)
        self.assertEqual(rep0["repeat_label"], "rep000")
        self.assertEqual(rep1["baseline_tokens_est"], 300)
        self.assertEqual(rep1["extra_tokens_est"], 150.0)
        self.assertEqual(rep1["repeat_index"], 1)
        self.assertEqual(rep1["repeat_label"], "rep001")

        target_rows = build_target_rows(rows)
        target_rep1 = next(row for row in target_rows if row["run_id"] == "attack_rep1")
        self.assertEqual(target_rep1["repeat_index"], 1)
        self.assertEqual(target_rep1["actual_extra_cost_est"], 1.5)

        summary = build_repeat_summary_rows(metrics, target_rows)
        attack_summary = next(row for row in summary if row["condition"] == "adaptive_full_medium")
        self.assertEqual(attack_summary["repeats"], 2)
        self.assertEqual(attack_summary["positive_amplification_repeats"], 2)
        self.assertEqual(attack_summary["positive_amplification_rate"], 1.0)
        self.assertEqual(attack_summary["avg_extra_tokens_est"], 100.0)
        self.assertEqual(attack_summary["avg_cost_amplification_factor"], 1.5)
        self.assertEqual(attack_summary["candidate_build_success_rate"], 1.0)
        self.assertEqual(attack_summary["final_submission_rate"], 1.0)

    def test_attack_without_same_repeat_baseline_stays_undefined(self):
        rows = [
            self._row(
                run_id="clean_rep0",
                condition="clean_skill_clean_verifier",
                target_level="none",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=100,
            ),
            self._row(
                run_id="attack_rep1",
                condition="adaptive_full_medium",
                target_level="medium",
                exposure="opencode_skill",
                repeat_index=1,
                input_tokens=450,
                target_extra_cost=5.0,
            ),
        ]

        metrics = build_metrics_rows(rows)
        attack = next(row for row in metrics if row["run_id"] == "attack_rep1")
        self.assertEqual(attack["baseline_tokens_est"], 0)
        self.assertIsNone(attack["cost_amplification_factor"])
        target_rows = build_target_rows(rows)
        target = next(row for row in target_rows if row["run_id"] == "attack_rep1")
        self.assertFalse(target["baseline_available"])
        self.assertEqual(target["actual_extra_cost_est"], "")
        self.assertTrue(target["controller_target_interval_hit"])
        self.assertEqual(target["controller_target_cost_error"], 0.0)
        self.assertEqual(target["target_cost_error"], "")
        self.assertEqual(target["target_interval_hit"], "")
        self.assertEqual(target["overshoot"], "")
        self.assertEqual(target["undershoot"], "")

    def test_controller_budget_status_is_separate_from_reported_token_status(self):
        rows = [
            self._row(
                run_id="clean_rep0",
                condition="clean_skill_clean_verifier",
                target_level="none",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=100,
            ),
            self._row(
                run_id="attack_rep0",
                condition="adaptive_full_medium",
                target_level="medium",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=1000,
                target_extra_cost=5.0,
            ),
        ]

        target_rows = build_target_rows(rows)
        target = next(row for row in target_rows if row["run_id"] == "attack_rep0")
        self.assertEqual(target["actual_extra_cost_est"], 9.0)
        self.assertFalse(target["target_interval_hit"])
        self.assertTrue(target["overshoot"])
        self.assertTrue(target["controller_target_interval_hit"])
        self.assertFalse(target["controller_overshoot"])
        self.assertFalse(target["controller_undershoot"])
        self.assertEqual(target["controller_target_cost_error"], 0.0)

        summary = build_repeat_summary_rows(build_metrics_rows(rows), target_rows)
        attack_summary = next(
            row for row in summary if row["condition"] == "adaptive_full_medium"
        )
        self.assertEqual(attack_summary["target_interval_hit_rate"], 0.0)
        self.assertEqual(attack_summary["overshoot_rate"], 1.0)
        self.assertEqual(attack_summary["controller_target_interval_hit_rate"], 1.0)
        self.assertEqual(attack_summary["controller_overshoot_rate"], 0.0)
        self.assertEqual(attack_summary["avg_controller_target_cost_error"], 0.0)

    def test_metrics_include_input_and_output_token_amplification(self):
        rows = [
            self._row(
                run_id="clean_rep0",
                condition="clean_skill_clean_verifier",
                target_level="none",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=100,
                output_tokens=10,
            ),
            self._row(
                run_id="attack_rep0",
                condition="adaptive_full_medium",
                target_level="medium",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=130,
                output_tokens=25,
                target_extra_cost=5.0,
            ),
        ]

        metrics = build_metrics_rows(rows)
        attack = next(row for row in metrics if row["run_id"] == "attack_rep0")
        self.assertEqual(attack["baseline_tokens_est"], 110)
        self.assertEqual(attack["extra_tokens_est"], 45.0)
        self.assertEqual(attack["baseline_input_tokens_est"], 100)
        self.assertEqual(attack["extra_input_tokens_est"], 30.0)
        self.assertEqual(attack["input_token_amplification_factor"], 1.3)
        self.assertEqual(attack["baseline_output_tokens_est"], 10)
        self.assertEqual(attack["extra_output_tokens_est"], 15.0)
        self.assertEqual(attack["output_token_amplification_factor"], 2.5)

        summary = build_repeat_summary_rows(metrics, build_target_rows(rows))
        attack_summary = next(
            row for row in summary if row["condition"] == "adaptive_full_medium"
        )
        self.assertEqual(attack_summary["positive_output_amplification_repeats"], 1)
        self.assertEqual(attack_summary["positive_output_amplification_rate"], 1.0)
        self.assertEqual(attack_summary["avg_extra_input_tokens_est"], 30.0)
        self.assertEqual(attack_summary["avg_extra_output_tokens_est"], 15.0)
        self.assertEqual(attack_summary["avg_output_token_amplification_factor"], 2.5)

    def test_repeat_summary_includes_repair_and_pagination_counts(self):
        rows = [
            self._row(
                run_id="clean_rep0",
                condition="clean_skill_clean_verifier",
                target_level="none",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=100,
            ),
            self._row(
                run_id="attack_rep0",
                condition="adaptive_full_medium",
                target_level="medium",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=150,
                target_extra_cost=5.0,
                repair_count=1,
                pagination_count=2,
            ),
            self._row(
                run_id="clean_rep1",
                condition="clean_skill_clean_verifier",
                target_level="none",
                exposure="opencode_skill",
                repeat_index=1,
                input_tokens=100,
            ),
            self._row(
                run_id="attack_rep1",
                condition="adaptive_full_medium",
                target_level="medium",
                exposure="opencode_skill",
                repeat_index=1,
                input_tokens=160,
                target_extra_cost=5.0,
                repair_count=0,
                pagination_count=1,
            ),
        ]

        summary = build_repeat_summary_rows(
            build_metrics_rows(rows),
            build_target_rows(rows),
        )
        attack_summary = next(
            row for row in summary if row["condition"] == "adaptive_full_medium"
        )
        self.assertEqual(attack_summary["avg_repair_count"], 0.5)
        self.assertEqual(attack_summary["runs_with_repair"], 1)
        self.assertEqual(attack_summary["avg_pagination_count"], 1.5)
        self.assertEqual(attack_summary["runs_with_pagination"], 2)

    def test_repeat_summary_includes_stealth_audit_fields(self):
        rows = [
            self._row(
                run_id="clean_rep0",
                condition="clean_skill_clean_verifier",
                target_level="none",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=100,
            ),
            self._row(
                run_id="attack_rep0",
                condition="adaptive_full_medium",
                target_level="medium",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=150,
                target_extra_cost=5.0,
                stealth_risk=0.10,
                task_local_anchor_count=2,
                agent_facing_condition_leak=False,
                verifier_message_chars=700,
            ),
            self._row(
                run_id="clean_rep1",
                condition="clean_skill_clean_verifier",
                target_level="none",
                exposure="opencode_skill",
                repeat_index=1,
                input_tokens=100,
            ),
            self._row(
                run_id="attack_rep1",
                condition="adaptive_full_medium",
                target_level="medium",
                exposure="opencode_skill",
                repeat_index=1,
                input_tokens=160,
                target_extra_cost=5.0,
                stealth_risk=0.30,
                task_local_anchor_count=4,
                agent_facing_condition_leak=True,
                verifier_message_chars=900,
            ),
        ]

        summary = build_repeat_summary_rows(
            build_metrics_rows(rows),
            build_target_rows(rows),
        )
        attack_summary = next(
            row for row in summary if row["condition"] == "adaptive_full_medium"
        )
        self.assertEqual(attack_summary["avg_stealth_risk"], 0.2)
        self.assertEqual(attack_summary["agent_facing_condition_leak_rate"], 0.5)
        self.assertEqual(attack_summary["avg_task_local_anchor_count"], 3.0)
        self.assertEqual(attack_summary["avg_verifier_message_chars"], 800.0)

    def test_repeat_summary_includes_validation_graph_fields(self):
        rows = [
            self._row(
                run_id="clean_rep0",
                condition="clean_skill_clean_verifier",
                target_level="none",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=100,
            ),
            self._row(
                run_id="attack_rep0",
                condition="adaptive_full_medium",
                target_level="medium",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=150,
                target_extra_cost=5.0,
                validation_graph_node_count=2,
                validation_graph_branch_count=2,
                validation_graph_open_node_count=1,
                validation_graph_completed_node_count=1,
                validation_graph_completion_ratio=0.5,
                validation_graph_max_depth=1,
                validation_graph_surface_count=2,
            ),
            self._row(
                run_id="clean_rep1",
                condition="clean_skill_clean_verifier",
                target_level="none",
                exposure="opencode_skill",
                repeat_index=1,
                input_tokens=100,
            ),
            self._row(
                run_id="attack_rep1",
                condition="adaptive_full_medium",
                target_level="medium",
                exposure="opencode_skill",
                repeat_index=1,
                input_tokens=160,
                target_extra_cost=5.0,
                validation_graph_node_count=4,
                validation_graph_branch_count=3,
                validation_graph_open_node_count=2,
                validation_graph_completed_node_count=2,
                validation_graph_completion_ratio=0.5,
                validation_graph_max_depth=2,
                validation_graph_surface_count=3,
            ),
        ]

        summary = build_repeat_summary_rows(
            build_metrics_rows(rows),
            build_target_rows(rows),
        )
        attack_summary = next(
            row for row in summary if row["condition"] == "adaptive_full_medium"
        )

        self.assertEqual(attack_summary["avg_validation_graph_node_count"], 3.0)
        self.assertEqual(attack_summary["max_validation_graph_node_count"], 4.0)
        self.assertEqual(attack_summary["avg_validation_graph_branch_count"], 2.5)
        self.assertEqual(attack_summary["max_validation_graph_branch_count"], 3.0)
        self.assertEqual(attack_summary["avg_validation_graph_open_node_count"], 1.5)
        self.assertEqual(
            attack_summary["avg_validation_graph_completed_node_count"],
            1.5,
        )
        self.assertEqual(attack_summary["avg_validation_graph_completion_ratio"], 0.5)
        self.assertEqual(attack_summary["avg_validation_graph_max_depth"], 1.5)
        self.assertEqual(attack_summary["max_validation_graph_max_depth"], 2.0)
        self.assertEqual(attack_summary["avg_validation_graph_surface_count"], 2.5)

    def test_ablation_rows_compare_mechanism_conditions_to_adaptive(self):
        rows = [
            self._row(
                run_id="clean_rep0",
                condition="clean_skill_clean_verifier",
                target_level="none",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=100,
            ),
            self._row(
                run_id="adaptive_rep0",
                condition="adaptive_full_medium",
                target_level="medium",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=180,
                target_extra_cost=5.0,
                validation_graph_node_count=3,
                validation_graph_branch_count=2,
                validation_graph_completion_ratio=0.25,
            ),
            self._row(
                run_id="no_budget_rep0",
                condition="no_budget_control",
                target_level="medium",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=220,
                target_extra_cost=5.0,
                validation_graph_node_count=5,
                validation_graph_branch_count=3,
                validation_graph_completion_ratio=0.2,
            ),
            self._row(
                run_id="no_pagination_rep0",
                condition="no_paginated_report",
                target_level="medium",
                exposure="opencode_skill",
                repeat_index=0,
                input_tokens=140,
                target_extra_cost=5.0,
                validation_graph_node_count=2,
                validation_graph_branch_count=1,
                validation_graph_completion_ratio=0.5,
            ),
        ]

        repeat = build_repeat_summary_rows(
            build_metrics_rows(rows),
            build_target_rows(rows),
        )
        ablation = build_ablation_rows(repeat)
        by_condition = {row["condition"]: row for row in ablation}

        self.assertEqual(set(by_condition), {"no_budget_control", "no_paginated_report"})
        self.assertEqual(
            by_condition["no_budget_control"]["removed_mechanism"],
            "adaptive_budget_control",
        )
        self.assertEqual(
            by_condition["no_paginated_report"]["removed_mechanism"],
            "paginated_feedback",
        )
        self.assertEqual(
            by_condition["no_budget_control"]["adaptive_baseline_condition"],
            "adaptive_full_medium",
        )
        self.assertAlmostEqual(
            by_condition["no_budget_control"]["delta_extra_tokens_vs_adaptive"],
            40.0,
        )
        self.assertAlmostEqual(
            by_condition["no_paginated_report"]["delta_extra_tokens_vs_adaptive"],
            -40.0,
        )
        self.assertAlmostEqual(
            by_condition["no_budget_control"][
                "delta_validation_graph_node_count_vs_adaptive"
            ],
            2.0,
        )
        self.assertAlmostEqual(
            by_condition["no_paginated_report"][
                "delta_validation_graph_branch_count_vs_adaptive"
            ],
            -1.0,
        )
        self.assertAlmostEqual(
            by_condition["no_paginated_report"][
                "delta_validation_graph_completion_ratio_vs_adaptive"
            ],
            0.25,
        )

    def test_aggregate_writes_ablation_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_run_dir(
                root / "clean",
                condition="clean_skill_clean_verifier",
                input_tokens=100,
                target_extra_cost=0.0,
            )
            self._write_run_dir(
                root / "adaptive",
                condition="adaptive_full_medium",
                input_tokens=180,
                target_extra_cost=5.0,
            )
            self._write_run_dir(
                root / "no_echo",
                condition="no_echo",
                input_tokens=150,
                target_extra_cost=5.0,
            )

            paths = aggregate(root)

            self.assertIn("ablation", paths)
            ablation_csv = paths["ablation"].read_text(encoding="utf-8")
            self.assertIn("removed_mechanism", ablation_csv)
            self.assertIn("semantic_echo", ablation_csv)
            self.assertIn("delta_extra_tokens_vs_adaptive", ablation_csv)

    def _row(
        self,
        *,
        run_id: str,
        condition: str,
        target_level: str,
        exposure: str,
        repeat_index: int,
        input_tokens: int,
        output_tokens: int = 0,
        target_extra_cost: float = 0.0,
        repair_count: int = 0,
        pagination_count: int = 0,
        stealth_risk: float = 0.0,
        task_local_anchor_count: int = 0,
        agent_facing_condition_leak: bool = False,
        verifier_message_chars: int = 0,
        validation_graph_node_count: int = 0,
        validation_graph_branch_count: int = 0,
        validation_graph_open_node_count: int = 0,
        validation_graph_completed_node_count: int = 0,
        validation_graph_completion_ratio: float = 0.0,
        validation_graph_max_depth: int = 0,
        validation_graph_surface_count: int = 0,
    ) -> dict:
        return {
            "run_id": run_id,
            "repeat_index": repeat_index,
            "repeat_label": f"rep{repeat_index:03d}",
            "task_id": "task",
            "agent_runtime": "opencode",
            "model": "model",
            "condition": condition,
            "target_level": target_level,
            "verifier_exposure_condition": exposure,
            "input_tokens_est": input_tokens,
            "output_tokens_est": output_tokens,
            "api_calls": 1,
            "verifier_calls": 1,
            "tests_passed_fraction": 0.7,
            "candidate_build_success": True,
            "final_submission_seen": True,
            "failure_label": None,
            "usage_source": "offline_estimate",
            "target_extra_cost": target_extra_cost,
            "target_extra_cost_lower": 4.0 if target_extra_cost else 0.0,
            "target_extra_cost_upper": 6.0 if target_extra_cost else 0.0,
            "controller_estimated_extra_cost": target_extra_cost,
            "cost_proxy_source": "test",
            "cost_proxy_units_per_verifier_call": target_extra_cost,
            "cost_proxy_initial_free_calls": 0,
            "cost_proxy_chargeable_calls": 1 if target_extra_cost else 0,
            "repair_count": repair_count,
            "pagination_count": pagination_count,
            "stealth_risk": stealth_risk,
            "stealth_risk_reason": "task_local_verifier_feedback"
            if stealth_risk
            else "",
            "task_local_anchor_count": task_local_anchor_count,
            "agent_facing_condition_leak": agent_facing_condition_leak,
            "verifier_message_chars": verifier_message_chars,
            "validation_graph_node_count": validation_graph_node_count,
            "validation_graph_branch_count": validation_graph_branch_count,
            "validation_graph_open_node_count": validation_graph_open_node_count,
            "validation_graph_completed_node_count": validation_graph_completed_node_count,
            "validation_graph_completion_ratio": validation_graph_completion_ratio,
            "validation_graph_max_depth": validation_graph_max_depth,
            "validation_graph_surface_count": validation_graph_surface_count,
        }

    def _write_json(self, path: Path, value: dict) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def _write_run_dir(
        self,
        run_dir: Path,
        *,
        condition: str,
        input_tokens: int,
        target_extra_cost: float,
    ) -> None:
        run_dir.mkdir()
        self._write_json(
            run_dir / "metadata.json",
            {
                "run_id": run_dir.name,
                "task_id": "task",
                "task_difficulty": "easy",
                "agent_runtime": "opencode",
                "model": "model",
                "condition": condition,
                "target_level": "medium" if target_extra_cost else "none",
                "verifier_exposure_condition": "opencode_skill",
            },
        )
        self._write_json(
            run_dir / "usage.json",
            {
                "input_tokens_est": input_tokens,
                "output_tokens_est": 0,
                "api_calls": 1,
                "usage_source": "offline_estimate",
            },
        )
        self._write_json(
            run_dir / "programbench_score.json",
            {
                "tests_passed_fraction": 0.7,
                "candidate_build_success": True,
                "final_submission_seen": True,
            },
        )
        self._write_json(run_dir / "failure_label.json", {"failure_label": None})
        (run_dir / "events.jsonl").write_text(
            json.dumps({"event_type": "verifier_call", "turn_id": 1}) + "\n",
            encoding="utf-8",
        )
        if target_extra_cost:
            (run_dir / "controller_trace.jsonl").write_text(
                json.dumps(
                    {
                        "target_extra_cost": target_extra_cost,
                        "target_extra_cost_lower": 4.0,
                        "target_extra_cost_upper": 6.0,
                        "estimated_extra_cost": target_extra_cost,
                    }
                )
                + "\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    unittest.main()
