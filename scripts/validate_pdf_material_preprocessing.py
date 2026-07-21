from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.extraction_plan import FormalExtractionRunPlan  # noqa: E402
from core.models import ProjectConfig  # noqa: E402
from core.source_scanner import scan_formal_materials  # noqa: E402
from utils.material_preprocessing import (  # noqa: E402
    PreprocessingLimits,
    PreprocessingRequest,
    build_project_preprocessing_request,
    preprocess_material,
    preprocess_project_source,
)
from utils.material_processing_middleware import process_source_request  # noqa: E402
from utils.pdf_backend import (  # noqa: E402
    PdfBackendCancelledError,
    PdfBackendCapability,
    PdfDocumentText,
    PdfPageLimitExceededError,
    PdfPageText,
    probe_pdf_backend,
)
from utils.source_importer import clean_raw_sources, remove_project_sources  # noqa: E402
import utils.paths as path_utils  # noqa: E402


def _request(
    root: Path,
    source: Path,
    *,
    limits: PreprocessingLimits | None = None,
) -> PreprocessingRequest:
    return PreprocessingRequest(
        source_path=source,
        source_raw_path=f"raw/{source.name}",
        output_root=root / "materials" / "derived_inputs" / "pdf_fixture",
        output_root_reference="materials/derived_inputs/pdf_fixture",
        manifest_path=root / "cache" / "material_preprocessing" / "pdf_fixture.json",
        preprocessor_key="pdf",
        limits=limits or PreprocessingLimits(),
        staging_root=root / "cache" / "material_preprocessing" / "tmp",
    )


def _project_request(project_root: Path, raw_source: Path) -> PreprocessingRequest:
    return build_project_preprocessing_request(
        raw_root=project_root / "raw",
        materials_root=project_root / "materials",
        cache_root=project_root / "cache",
        raw_source=raw_source,
        preprocessor_key="pdf",
    )


def _warning_codes(result) -> set[str]:
    return {warning.code for warning in result.warnings}


def _write_text_pdf(path: Path, page_texts: list[str]) -> None:
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
    }
    page_ids = [3 + index * 2 for index in range(len(page_texts))]
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    for index, (page_id, text) in enumerate(zip(page_ids, page_texts, strict=True)):
        content_id = page_id + 1
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET\n".encode("ascii")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R /Resources << /Font << /F1 << /Type /Font "
            "/Subtype /Type1 /BaseFont /Helvetica >> >> >> >>"
        ).encode()
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream"
        )

    payload = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (max(objects) + 1)
    for object_id in range(1, len(offsets)):
        offsets[object_id] = len(payload)
        payload.extend(f"{object_id} 0 obj\n".encode())
        payload.extend(objects[object_id])
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(offsets)}\n".encode())
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _write_blank_pdf(path: Path, *, encrypted: bool = False) -> None:
    from pypdf import PdfWriter

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    if encrypted:
        writer.encrypt("validation-password", algorithm="RC4-40")
    with path.open("wb") as stream:
        writer.write(stream)


@dataclass
class _FakePdfBackend:
    capability: PdfBackendCapability
    document: PdfDocumentText | None = None
    failure: Exception | None = None
    extract_calls: int = 0
    max_pages: int = 0

    def probe(self) -> PdfBackendCapability:
        return self.capability

    def extract_document(self, source_path, *, max_pages, cancelled=None) -> PdfDocumentText:
        self.extract_calls += 1
        self.max_pages = max_pages
        if self.failure is not None:
            raise self.failure
        assert self.document is not None
        return self.document


def _available_capability() -> PdfBackendCapability:
    return PdfBackendCapability(
        available=True,
        backend_name="fake-pdf",
        version="1.0",
    )


def _assert_backend_probe_and_fake_contract(root: Path) -> None:
    capability = probe_pdf_backend()
    assert capability.available
    assert capability.backend_name == "pypdf"
    assert capability.version.startswith("6.")

    source = root / "fake.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-fake")
    missing = _FakePdfBackend(
        PdfBackendCapability(
            available=False,
            backend_name="missing-pdf",
            reason="ImportError",
        )
    )
    missing_result = preprocess_material(_request(root / "missing", source), pdf_backend=missing)
    assert missing_result.status == "failed"
    assert _warning_codes(missing_result) == {"pdf_backend_unavailable"}
    assert missing.extract_calls == 0

    partial = _FakePdfBackend(
        _available_capability(),
        document=PdfDocumentText(
            page_count=3,
            encrypted=False,
            pages=(
                PdfPageText(page_number=1, text="First fake page"),
                PdfPageText(page_number=2, error_type="FakePageError"),
                PdfPageText(page_number=3, text="  \n"),
            ),
        ),
    )
    partial_result = preprocess_material(
        _request(root / "partial", source),
        pdf_backend=partial,
    )
    assert partial_result.succeeded
    assert len(partial_result.derived_materials) == 1
    assert partial.max_pages == PreprocessingLimits().max_entries
    assert _warning_codes(partial_result) == {
        "pdf_page_extraction_failed",
        "pdf_page_empty",
    }
    assert partial_result.failed_entries == ("page:2",)
    assert [summary.status for summary in partial_result.entry_summaries] == [
        "materialized",
        "extraction_failed",
        "empty",
    ]

    invalid_contract = _FakePdfBackend(
        _available_capability(),
        document=PdfDocumentText(
            page_count=2,
            encrypted=False,
            pages=(
                PdfPageText(page_number=2, text="out of order"),
                PdfPageText(page_number=1, text="out of order"),
            ),
        ),
    )
    invalid_result = preprocess_material(
        _request(root / "invalid-contract", source),
        pdf_backend=invalid_contract,
    )
    assert invalid_result.status == "failed"
    assert _warning_codes(invalid_result) == {"pdf_backend_contract_invalid"}

    page_limit = _FakePdfBackend(
        _available_capability(),
        failure=PdfPageLimitExceededError(4, 2),
    )
    limit_result = preprocess_material(
        _request(
            root / "page-limit",
            source,
            limits=PreprocessingLimits(max_entries=2),
        ),
        pdf_backend=page_limit,
    )
    assert limit_result.status == "failed"
    assert _warning_codes(limit_result) == {"pdf_page_limit_exceeded"}

    cancelled = _FakePdfBackend(
        _available_capability(),
        failure=PdfBackendCancelledError("cancelled"),
    )
    cancelled_result = preprocess_material(
        _request(root / "cancelled", source),
        pdf_backend=cancelled,
    )
    assert cancelled_result.status == "cancelled"
    assert not cancelled_result.manifest_path.exists()

    oversized_page = _FakePdfBackend(
        _available_capability(),
        document=PdfDocumentText(
            page_count=1,
            encrypted=False,
            pages=(PdfPageText(page_number=1, text="x" * 128),),
        ),
    )
    oversized_result = preprocess_material(
        _request(
            root / "oversized-page",
            source,
            limits=PreprocessingLimits(max_entry_size_bytes=32),
        ),
        pdf_backend=oversized_page,
    )
    assert oversized_result.succeeded
    assert _warning_codes(oversized_result) == {
        "pdf_page_size_limit_exceeded",
        "pdf_no_extractable_text",
    }


def _assert_missing_backend_workflow(root: Path) -> None:
    import utils.pdf_material_preprocessor as pdf_preprocessor

    projects_root = root / "projects"
    external_source = root / "external" / "missing-backend.pdf"
    external_source.parent.mkdir(parents=True)
    external_source.write_bytes(b"%PDF-fake")
    project_id = "pdf-missing-backend"
    config = ProjectConfig(
        project_id=project_id,
        name="Missing PDF backend validation",
        source_paths=[str(external_source)],
    )
    missing = _FakePdfBackend(
        PdfBackendCapability(
            available=False,
            backend_name="missing-pdf",
            reason="ImportError",
        )
    )

    previous_projects_root = path_utils.PROJECTS_ROOT
    original_default_backend = pdf_preprocessor.default_pdf_backend
    path_utils.PROJECTS_ROOT = projects_root
    pdf_preprocessor.default_pdf_backend = lambda: missing
    try:
        result = process_source_request(config)
        project_root = projects_root / project_id
        raw_source = project_root / "raw" / external_source.name
        assert result.preprocessed_source_count == 0
        assert result.derived_material_count == 0
        assert result.preprocessing_warning_codes == ["pdf_backend_unavailable"]
        assert raw_source.is_file()
        assert not (project_root / "materials" / external_source.name).exists()
        assert not list(
            (project_root / "cache" / "material_preprocessing").rglob("*.json")
        )
        assert remove_project_sources(project_id, [str(external_source)]) == 1
        assert not raw_source.exists()
    finally:
        pdf_preprocessor.default_pdf_backend = original_default_backend
        path_utils.PROJECTS_ROOT = previous_projects_root


def _assert_pdf_profile_end_to_end(root: Path) -> None:
    projects_root = root / "projects"
    external_source = root / "external" / "setting-book.pdf"
    _write_text_pdf(external_source, ["First PDF page", "Second PDF page"])
    project_id = "pdf-profile-e2e"
    config = ProjectConfig(
        project_id=project_id,
        name="PDF profile validation",
        source_paths=[str(external_source)],
    )

    previous_projects_root = path_utils.PROJECTS_ROOT
    path_utils.PROJECTS_ROOT = projects_root
    try:
        result = process_source_request(config)
        project_root = projects_root / project_id
        raw_source = project_root / "raw" / external_source.name
        assert result.preprocessed_source_count == 1
        assert result.derived_material_count == 2
        assert result.preprocessing_warning_codes == []
        assert raw_source.is_file()
        assert not (project_root / "materials" / external_source.name).exists()

        request = _project_request(project_root, raw_source)
        manifest = json.loads(request.manifest_path.read_text(encoding="utf-8"))
        assert manifest["source_suffix"] == ".pdf"
        assert manifest["preprocessor"] == "pdf"
        assert [record["source_entry_path"] for record in manifest["derived_materials"]] == [
            "page:1",
            "page:2",
        ]
        assert [record["page_number"] for record in manifest["derived_materials"]] == [1, 2]
        assert all(
            record["content_form_hint"] == "setting_book"
            for record in manifest["derived_materials"]
        )
        assert [summary["page_number"] for summary in manifest["entry_summaries"]] == [1, 2]
        assert (request.output_root / "text" / "pages" / "page_0001.txt").read_text(
            encoding="utf-8"
        ).strip() == "First PDF page"

        episodes = scan_formal_materials(project_id)
        units = [unit for episode in episodes for unit in episode.units]
        assert len(units) == 2
        assert {unit.media_type.value for unit in units} == {"text"}
        assert {unit.content_form.value for unit in units} == {"setting_book"}
        assert [unit.material_ref.metadata["source_entry_path"] for unit in units] == [
            "page:1",
            "page:2",
        ]
        assert [unit.material_ref.page_range.start_page for unit in units] == [1, 2]
        run_plan = FormalExtractionRunPlan(project_id=project_id, episodes=episodes)
        assert [unit.material_ref.metadata["page_number"] for unit in run_plan.all_units] == [
            1,
            2,
        ]

        reused = preprocess_project_source(
            _project_request(project_root, raw_source),
            raw_root=project_root / "raw",
            materials_root=project_root / "materials",
            cache_root=project_root / "cache",
        )
        assert reused.succeeded and reused.reused

        assert clean_raw_sources(project_id, [raw_source]) == [external_source.name]
        assert not raw_source.exists()
        assert request.output_root.exists()
        external_source.unlink()
        assert remove_project_sources(project_id, [str(external_source)]) == 0
        assert not request.output_root.exists()
        assert not request.manifest_path.exists()
    finally:
        path_utils.PROJECTS_ROOT = previous_projects_root


def _assert_pdf_failure_boundaries(root: Path) -> None:
    blank_source = root / "blank" / "scanned.pdf"
    _write_blank_pdf(blank_source)
    blank_result = preprocess_material(_request(root / "blank", blank_source))
    assert blank_result.succeeded
    assert blank_result.derived_materials == ()
    assert _warning_codes(blank_result) == {
        "pdf_page_empty",
        "pdf_no_extractable_text",
    }
    assert blank_result.manifest_path.is_file()

    encrypted_source = root / "encrypted" / "encrypted.pdf"
    _write_blank_pdf(encrypted_source, encrypted=True)
    encrypted_result = preprocess_material(_request(root / "encrypted", encrypted_source))
    assert encrypted_result.status == "failed"
    assert _warning_codes(encrypted_result) == {"pdf_encrypted_unsupported"}
    assert not encrypted_result.manifest_path.exists()

    corrupt_source = root / "corrupt" / "corrupt.pdf"
    corrupt_source.parent.mkdir(parents=True)
    corrupt_source.write_bytes(b"not a PDF")
    corrupt_result = preprocess_material(_request(root / "corrupt", corrupt_source))
    assert corrupt_result.status == "failed"
    assert _warning_codes(corrupt_result) == {"pdf_document_invalid"}
    assert not corrupt_result.manifest_path.exists()

    large_source = root / "large" / "large.pdf"
    large_source.parent.mkdir(parents=True)
    large_source.write_bytes(b"%PDF" + b"x" * 64)
    large_result = preprocess_material(
        _request(
            root / "large",
            large_source,
            limits=PreprocessingLimits(max_entry_size_bytes=32),
        )
    )
    assert large_result.status == "failed"
    assert _warning_codes(large_result) == {"pdf_input_size_limit_exceeded"}


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _assert_backend_probe_and_fake_contract(root / "backend")
        _assert_missing_backend_workflow(root / "missing-workflow")
        _assert_pdf_profile_end_to_end(root / "profile")
        _assert_pdf_failure_boundaries(root / "boundaries")
    print("PDF material preprocessing validation passed")


if __name__ == "__main__":
    main()
