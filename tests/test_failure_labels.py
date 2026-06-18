import unittest

from edos.instrumentation.failure_labels import reconcile_failure_label_with_score


class FailureLabelTest(unittest.TestCase):
    def test_score_build_success_clears_weak_build_failure(self):
        self.assertIsNone(
            reconcile_failure_label_with_score(
                "build_failure",
                {"candidate_build_success": True, "final_submission_seen": True},
            )
        )

    def test_infrastructure_failure_is_not_cleared_by_score(self):
        self.assertEqual(
            reconcile_failure_label_with_score(
                "llm_api_auth_error",
                {"candidate_build_success": True, "final_submission_seen": True},
            ),
            "llm_api_auth_error",
        )


if __name__ == "__main__":
    unittest.main()
