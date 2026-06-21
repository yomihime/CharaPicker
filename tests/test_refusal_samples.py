from __future__ import annotations

import json
import shutil
import unittest
import zipfile
from pathlib import Path
from uuid import uuid4

from core.refusal_samples import (
    ExtractionFailureSampleRequest,
    load_refusal_sample,
    package_refusal_sample,
    record_extraction_failure_sample,
)
from utils.paths import project_paths


class RefusalSampleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_id = f"test-refusal-{uuid4().hex[:8]}"
        self.paths = project_paths(self.project_id)
        self.paths.materials.mkdir(parents=True, exist_ok=True)
        self.paths.cache.mkdir(parents=True, exist_ok=True)
        self.paths.output.mkdir(parents=True, exist_ok=True)
        self.paths.config.write_text(
            json.dumps({"project_id": self.project_id, "name": "Refusal Sample Test"}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        root = self.paths.root.resolve()
        projects_root = project_paths("dummy").root.parent.resolve()
        if root.exists() and root != projects_root and projects_root in root.parents:
            shutil.rmtree(root)

    def test_record_failure_sample_redacts_sensitive_metadata(self) -> None:
        material_path = self.paths.materials / "notes.txt"
        material_path.write_text("short safe fixture", encoding="utf-8")

        result = record_extraction_failure_sample(
            ExtractionFailureSampleRequest(
                project_id=self.project_id,
                prompt_purpose="formal_text_unit_extraction",
                provider="custom",
                backend="openai_compatible",
                model_name="model-a",
                media_type="text",
                content_form="novel",
                unit_id="unit_text_001",
                unit_kind="document_text",
                material_id="material_text_001",
                source_path="notes.txt",
                extraction_stage="full",
                extraction_run_id="run-001",
                season_id="season_001",
                episode_id="episode_001",
                failure_kind="model_call_failed",
                error_type="ModelCallError",
                error_summary="provider rejected request",
                metadata={"api_key": "secret-key", "retry_count": 2},
            ),
            max_material_copy_bytes=1024,
        )

        record = load_refusal_sample(self.project_id, result.sample_id)

        self.assertEqual(record.project_name, "Refusal Sample Test")
        self.assertEqual(record.prompt_purpose, "formal_text_unit_extraction")
        self.assertEqual(record.media_type, "text")
        self.assertEqual(record.content_form, "novel")
        self.assertEqual(record.source_refs[0].project_relative_path, "materials/notes.txt")
        self.assertEqual(record.source_refs[0].copy_policy, "copy_allowed")
        self.assertEqual(record.metadata["api_key"], "<redacted>")
        self.assertEqual(len(record.sample_hash), 16)

    def test_package_failure_sample_copies_small_materials_and_indexes_large_ones(self) -> None:
        (self.paths.materials / "small.txt").write_text("small", encoding="utf-8")
        (self.paths.materials / "large.txt").write_text("this file is intentionally large", encoding="utf-8")
        result = record_extraction_failure_sample(
            ExtractionFailureSampleRequest(
                project_id=self.project_id,
                prompt_purpose="formal_text_unit_extraction",
                media_type="text",
                content_form="script",
                source_path="small.txt",
                source_paths=["large.txt"],
                error_type="ModelCallError",
                error_summary="failure",
            ),
            max_material_copy_bytes=8,
        )

        package = package_refusal_sample(
            self.project_id,
            result.sample_id,
            include_materials=True,
            max_material_copy_bytes=8,
        )

        with zipfile.ZipFile(package.zip_path) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("package_manifest.json").decode("utf-8"))

        self.assertIn("refusal_sample.json", names)
        self.assertIn("package_manifest.json", names)
        self.assertIn("materials/small.txt", names)
        self.assertNotIn("materials/large.txt", names)
        self.assertEqual(manifest["indexed_materials"], ["materials/large.txt"])
        self.assertEqual(package.copied_materials, ["materials/small.txt"])

    def test_absolute_outside_project_path_is_redacted(self) -> None:
        outside = Path("C:/private/source.txt")

        result = record_extraction_failure_sample(
            ExtractionFailureSampleRequest(
                project_id=self.project_id,
                media_type="image",
                content_form="manga",
                source_path=str(outside),
                error_type="ModelCallError",
                error_summary="failure",
            )
        )

        record = load_refusal_sample(self.project_id, result.sample_id)

        self.assertEqual(record.source_path, "<outside_project>/source.txt")
        self.assertEqual(record.source_refs[0].source_path, "<outside_project>/source.txt")
        self.assertEqual(record.source_refs[0].copy_policy, "outside_project")


if __name__ == "__main__":
    unittest.main()
