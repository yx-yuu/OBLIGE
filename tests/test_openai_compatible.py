import json
import tempfile
import unittest
from pathlib import Path

from edos.llm.openai_compatible import (
    OpenAICompatibleProfile,
    load_openai_compatible_profile,
)


class OpenAICompatibleProfileTest(unittest.TestCase):
    def test_load_profile_and_build_mini_sweagent_specs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.json"
            path.write_text(
                json.dumps(
                    {
                        "profile_name": "local_vllm",
                        "model": "hosted_vllm/test-model",
                        "base_url": "http://localhost:8000/v1",
                        "api_key_env": "LOCAL_LLM_API_KEY",
                        "target_api_key_env": "OPENAI_API_KEY",
                        "model_class": "litellm",
                        "custom_llm_provider": "hosted_vllm",
                        "temperature": 0,
                        "max_tokens": 1024,
                        "timeout_seconds": 30,
                        "max_retries": 1,
                        "require_api_key": False,
                        "model_kwargs": {"drop_params": True},
                    }
                ),
                encoding="utf-8",
            )

            profile = load_openai_compatible_profile(path)
            specs = profile.mini_sweagent_config_specs()

        self.assertEqual(profile.profile_name, "local_vllm")
        self.assertIn('model.model_name="hosted_vllm/test-model"', specs)
        self.assertIn('model.model_class="litellm"', specs)
        self.assertIn('model.model_kwargs.api_base="http://localhost:8000/v1"', specs)
        self.assertIn('model.model_kwargs.custom_llm_provider="hosted_vllm"', specs)
        self.assertIn("model.model_kwargs.drop_params=true", specs)
        self.assertIn("model.model_kwargs.max_tokens=1024", specs)

    def test_env_for_subprocess_maps_key_without_snapshot_secret(self):
        profile = OpenAICompatibleProfile(
            profile_name="proxy",
            model="openai/test",
            base_url="https://proxy.example/v1",
            api_key_env="EDOS_TEST_API_KEY",
            target_api_key_env="OPENAI_API_KEY",
            model_kwargs={"api_key": "dummy-value"},
            extra_body={"nested": {"access_token": "dummy-value"}},
        )

        env = profile.env_for_subprocess({"EDOS_TEST_API_KEY": "dummy-value"})
        snapshot = profile.redacted_snapshot()

        self.assertEqual(env["OPENAI_API_KEY"], "dummy-value")
        self.assertNotIn("dummy-value", json.dumps(snapshot))
        self.assertEqual(snapshot["api_key_env"], "EDOS_TEST_API_KEY")
        self.assertEqual(snapshot["model_kwargs"]["api_key"], "<redacted>")
        self.assertEqual(snapshot["extra_body"]["nested"]["access_token"], "<redacted>")

    def test_env_for_subprocess_requires_key_by_default(self):
        profile = OpenAICompatibleProfile(
            profile_name="missing",
            model="openai/test",
            base_url="https://proxy.example/v1",
            api_key_env="MISSING_KEY",
        )

        with self.assertRaisesRegex(EnvironmentError, "MISSING_KEY"):
            profile.env_for_subprocess({})


if __name__ == "__main__":
    unittest.main()
