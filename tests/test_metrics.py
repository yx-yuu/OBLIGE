import unittest

from edos.analysis.metrics import interval_status, target_cost_error


class MetricsTest(unittest.TestCase):
    def test_target_cost_error(self):
        self.assertEqual(target_cost_error(5.0, 5.0), 0.0)
        self.assertEqual(target_cost_error(6.0, 3.0), 1.0)
        self.assertIsNone(target_cost_error(1.0, 0.0))

    def test_interval_status(self):
        self.assertEqual(interval_status(5.0, 4.0, 6.0), (True, False, False))
        self.assertEqual(interval_status(7.0, 4.0, 6.0), (False, True, False))
        self.assertEqual(interval_status(3.0, 4.0, 6.0), (False, False, True))


if __name__ == "__main__":
    unittest.main()

