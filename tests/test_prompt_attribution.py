from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.ai_model_middleware import prompt_attribution
from utils.prompt_preferences import PromptOverride


class PromptAttributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.prompt_path = Path(self.temporary_directory.name) / "default_prompts.json"
        self.prompt_path.write_text(
            json.dumps(
                {
                    "version": 7,
                    "prompts": {
                        "synthetic_purpose": {
                            "system": "Default system template",
                            "user_template": "Extract {material_text}",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_default_prompt_attribution_contains_version_and_template_hash(self) -> None:
        with patch(
            "utils.ai_model_middleware.prompt_override",
            return_value=PromptOverride(),
        ):
            attribution = prompt_attribution("synthetic_purpose", path=self.prompt_path)

        self.assertEqual(attribution.default_resource_version, 7)
        self.assertEqual(attribution.effective_source, "default")
        self.assertEqual(
            attribution.component_sources,
            {"system": "default", "user_template": "default"},
        )
        self.assertRegex(attribution.template_hash, r"^sha256:[0-9a-f]{64}$")

    def test_partial_override_is_attributed_without_exposing_template_text(self) -> None:
        override = PromptOverride(system="Custom system template")
        with patch("utils.ai_model_middleware.prompt_override", return_value=override):
            attribution = prompt_attribution("synthetic_purpose", path=self.prompt_path)

        serialized = attribution.model_dump_json()
        self.assertEqual(attribution.effective_source, "override")
        self.assertEqual(
            attribution.component_sources,
            {"system": "override", "user_template": "default"},
        )
        self.assertNotIn("Custom system template", serialized)
        self.assertNotIn("Extract {material_text}", serialized)


if __name__ == "__main__":
    unittest.main()
