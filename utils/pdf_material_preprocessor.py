"""Text-only PDF preprocessing behind the common material lifecycle."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath

from utils.material_preprocessing import (
    DerivedMaterialRecord,
    PreprocessingCancelledError,
    PreprocessingEntrySummary,
    PreprocessingExtractionSummary,
    PreprocessingRequest,
    PreprocessingWarning,
    _raise_if_cancelled,
    ensure_path_within_root,
)
from utils.pdf_backend import (
    PdfBackend,
    PdfBackendCancelledError,
    PdfBackendError,
    PdfPageLimitExceededError,
    default_pdf_backend,
)


def extract_pdf_materials(
    request: PreprocessingRequest,
    staged_output: Path,
    *,
    backend: PdfBackend | None = None,
) -> PreprocessingExtractionSummary:
    selected_backend = backend or default_pdf_backend()
    capability = selected_backend.probe()
    if not capability.available:
        return _fatal_summary(
            PreprocessingWarning(
                code="pdf_backend_unavailable",
                message="The configured PDF text backend is unavailable.",
                context={
                    "backend": capability.backend_name,
                    "version": capability.version,
                    "reason": capability.reason,
                },
            )
        )

    input_size = request.source_path.stat().st_size
    if input_size > request.limits.max_entry_size_bytes:
        return _fatal_summary(
            PreprocessingWarning(
                code="pdf_input_size_limit_exceeded",
                message="The PDF exceeds the preprocessing input size limit.",
                context={
                    "size_bytes": input_size,
                    "limit": request.limits.max_entry_size_bytes,
                },
            )
        )

    try:
        document = selected_backend.extract_document(
            request.source_path,
            max_pages=request.limits.max_entries,
            cancelled=request.cancelled,
        )
    except PdfBackendCancelledError as exc:
        raise PreprocessingCancelledError from exc
    except PdfPageLimitExceededError as exc:
        return _fatal_summary(
            PreprocessingWarning(
                code="pdf_page_limit_exceeded",
                message="The PDF contains more pages than the preprocessing limit.",
                context={"page_count": exc.page_count, "limit": exc.limit},
            ),
            entry_count=exc.page_count,
        )
    except PdfBackendError as exc:
        return _fatal_summary(
            PreprocessingWarning(
                code="pdf_document_invalid",
                message="The PDF is damaged, unsupported, or unreadable.",
                context={"error_type": exc.error_type},
            )
        )

    if document.encrypted:
        return _fatal_summary(
            PreprocessingWarning(
                code="pdf_encrypted_unsupported",
                message="Encrypted or password-protected PDF files are unsupported.",
            ),
            entry_count=document.page_count,
        )
    expected_page_numbers = list(range(1, document.page_count + 1))
    actual_page_numbers = [page.page_number for page in document.pages]
    if (
        document.page_count < 0
        or document.page_count > request.limits.max_entries
        or actual_page_numbers != expected_page_numbers
    ):
        return _fatal_summary(
            PreprocessingWarning(
                code="pdf_backend_contract_invalid",
                message="The PDF backend returned an invalid page sequence.",
                context={
                    "page_count": document.page_count,
                    "returned_page_count": len(document.pages),
                },
            ),
            entry_count=max(document.page_count, 0),
        )

    derived: list[DerivedMaterialRecord] = []
    summaries: list[PreprocessingEntrySummary] = []
    warnings: list[PreprocessingWarning] = []
    failed_entries: list[str] = []
    expanded_size = 0
    for page in document.pages:
        _raise_if_cancelled(request.cancelled)
        source_entry = f"page:{page.page_number}"
        if page.error_type:
            warnings.append(
                PreprocessingWarning(
                    code="pdf_page_extraction_failed",
                    message="Text extraction failed for one PDF page.",
                    entry_path=source_entry,
                    context={"error_type": page.error_type},
                )
            )
            failed_entries.append(source_entry)
            summaries.append(_page_summary(page.page_number, status="extraction_failed"))
            continue

        page_text = _normalize_pdf_text(page.text)
        if not page_text:
            warnings.append(
                PreprocessingWarning(
                    code="pdf_page_empty",
                    message="A PDF page contained no extractable text.",
                    entry_path=source_entry,
                )
            )
            summaries.append(_page_summary(page.page_number, status="empty"))
            continue

        output_bytes = (page_text.rstrip() + "\n").encode("utf-8")
        if len(output_bytes) > request.limits.max_entry_size_bytes:
            warnings.append(
                PreprocessingWarning(
                    code="pdf_page_size_limit_exceeded",
                    message="Extracted text for one PDF page exceeds the size limit.",
                    entry_path=source_entry,
                    context={
                        "size_bytes": len(output_bytes),
                        "limit": request.limits.max_entry_size_bytes,
                    },
                )
            )
            failed_entries.append(source_entry)
            summaries.append(_page_summary(page.page_number, status="size_limit_exceeded"))
            continue
        if expanded_size + len(output_bytes) > request.limits.max_expanded_size_bytes:
            warnings.append(
                PreprocessingWarning(
                    code="expanded_size_limit_exceeded",
                    message="Derived PDF text exceeds the expanded size limit.",
                    entry_path=source_entry,
                    context={
                        "expanded_size_bytes": expanded_size + len(output_bytes),
                        "limit": request.limits.max_expanded_size_bytes,
                    },
                )
            )
            failed_entries.append(source_entry)
            summaries.append(_page_summary(page.page_number, status="size_limit_exceeded"))
            continue

        output_relative = PurePosixPath(
            "text",
            "pages",
            f"page_{page.page_number:04d}.txt",
        )
        target = ensure_path_within_root(staged_output, output_relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(output_bytes)
        expanded_size += len(output_bytes)
        derived.append(
            DerivedMaterialRecord(
                material_relative_path=PurePosixPath(
                    request.output_root_reference,
                    *output_relative.parts,
                ).as_posix(),
                source_entry_path=source_entry,
                media_type="text",
                content_form_hint="setting_book",
                original_name=f"page_{page.page_number:04d}.txt",
                size_bytes=len(output_bytes),
                fingerprint=f"sha256:{hashlib.sha256(output_bytes).hexdigest()}",
                page_number=page.page_number,
            )
        )
        summaries.append(
            _page_summary(
                page.page_number,
                status="materialized",
                size_bytes=len(output_bytes),
            )
        )

    if not derived:
        warnings.append(
            PreprocessingWarning(
                code="pdf_no_extractable_text",
                message="The PDF contains no extractable text; OCR is not enabled.",
            )
        )
    return PreprocessingExtractionSummary(
        derived_materials=tuple(derived),
        entry_summaries=tuple(summaries),
        warnings=tuple(warnings),
        failed_entries=tuple(failed_entries),
        entry_count=document.page_count,
        expanded_size_bytes=expanded_size,
    )


def _page_summary(
    page_number: int,
    *,
    status: str,
    size_bytes: int = 0,
) -> PreprocessingEntrySummary:
    return PreprocessingEntrySummary(
        source_entry_path=f"page:{page_number}",
        role="page",
        media_type="text",
        media_subtype="application/pdf",
        page_number=page_number,
        size_bytes=size_bytes,
        status=status,
    )


def _normalize_pdf_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in value.split("\n")]
    normalized: list[str] = []
    for line in lines:
        if not line and (not normalized or not normalized[-1]):
            continue
        normalized.append(line)
    return "\n".join(normalized).strip()


def _fatal_summary(
    warning: PreprocessingWarning,
    *,
    entry_count: int = 0,
) -> PreprocessingExtractionSummary:
    return PreprocessingExtractionSummary(
        warnings=(warning,),
        entry_count=entry_count,
        fatal=True,
    )
