import unittest

from edos.config import load_experiment_config
from edos.surfaces import normalize_entry_surface


class SurfaceTest(unittest.TestCase):
    def test_normalize_entry_surface_maps_legacy_exposures(self):
        self.assertEqual(normalize_entry_surface("opencode_skill"), "skill")
        self.assertEqual(normalize_entry_surface("workflow_enforced"), "runtime_hook")
        self.assertEqual(normalize_entry_surface("openhands_mcp"), "mcp_or_tool_manifest")
        self.assertEqual(normalize_entry_surface("light_prompt"), "user_prompt")

    def test_config_can_override_entry_surface(self):
        config = load_experiment_config("configs/experiments/openhands_headless_stub.json")
        self.assertEqual(config.conditions[0].entry_surface, "mcp_or_tool_manifest")
        self.assertEqual(config.conditions[0].verifier_exposure_condition, "openhands_mcp")


if __name__ == "__main__":
    unittest.main()

