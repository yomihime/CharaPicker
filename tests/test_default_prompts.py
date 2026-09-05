from __future__ import annotations

import json
import unittest

from utils.ai_model_middleware import DEFAULT_PROMPTS_PATH


CONTENT_FACING_PURPOSES = (
    "targeted_insight",
    "preview_video_chunk_extraction",
    "preview_text_unit_extraction",
    "formal_text_unit_extraction",
    "preview_image_unit_extraction",
    "formal_image_unit_extraction",
    "formal_native_media_insight",
    "formal_video_chunk_extraction",
    "formal_contextual_video_chunk_extraction",
    "formal_episode_content_merge",
    "formal_episode_summary",
    "formal_season_content_merge",
    "formal_season_summary",
    "character_compile",
    "character_card_compile",
    "final_polish",
)


class DefaultPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(DEFAULT_PROMPTS_PATH.read_text(encoding="utf-8"))

    def test_semantic_prompt_resource_version_is_incremented(self) -> None:
        self.assertEqual(self.payload["version"], 3)

    def test_content_facing_prompts_keep_neutral_fiction_boundaries(self) -> None:
        prompts = self.payload["prompts"]

        for purpose in CONTENT_FACING_PURPOSES:
            with self.subTest(purpose=purpose):
                system_prompt = prompts[purpose]["system"]
                self.assertIn("虚构", system_prompt)
                self.assertIn("中立", system_prompt)
                self.assertIn("JSON", system_prompt)

    def test_default_prompts_do_not_request_safety_bypass(self) -> None:
        serialized = json.dumps(self.payload, ensure_ascii=False)

        for forbidden in ("忽略安全策略", "绕过安全策略", "关闭安全策略", "隐藏安全策略"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)

    def test_chat_prompts_keep_reality_and_evidence_boundaries(self) -> None:
        prompts = self.payload["prompts"]
        for purpose in (
            "preview_chat_log_extraction",
            "formal_chat_log_extraction",
        ):
            with self.subTest(purpose=purpose):
                system_prompt = prompts[purpose]["system"]
                user_template = prompts[purpose]["user_template"]
                self.assertIn("不能默认", system_prompt)
                self.assertIn("消息", system_prompt)
                self.assertIn("JSON", system_prompt)
                self.assertIn("message_refs", user_template)
                self.assertIn("relationship_inference=disabled", user_template)


if __name__ == "__main__":
    unittest.main()
