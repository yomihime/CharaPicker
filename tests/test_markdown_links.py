from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.validate_markdown_links import validate_markdown_links


class MarkdownLinkValidationTests(unittest.TestCase):
    def test_relative_link_and_image_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (root / "image.png").write_bytes(b"png")
            (docs / "target.md").write_text("target\n", encoding="utf-8")
            source = docs / "source.md"
            source.write_text(
                "[target](target.md#section)\n![image](../image.png)\n",
                encoding="utf-8",
            )

            self.assertEqual(validate_markdown_links([source], root=root), [])

    def test_missing_relative_link_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.md"
            source.write_text("[missing](docs/missing.md)\n", encoding="utf-8")

            errors = validate_markdown_links([source], root=root)

            self.assertTrue(any("does not exist" in error for error in errors))

    def test_links_in_code_fences_and_external_links_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.md"
            source.write_text(
                "```markdown\n[example](missing.md)\n```\n"
                "[website](https://example.com/path)\n",
                encoding="utf-8",
            )

            self.assertEqual(validate_markdown_links([source], root=root), [])


if __name__ == "__main__":
    unittest.main()
