"""Narrow PDF backend contract and the production pypdf adapter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


try:
    import pypdf as _pypdf
except (ImportError, OSError) as exc:
    _pypdf = None
    _pypdf_import_error_type = type(exc).__name__
else:
    _pypdf_import_error_type = ""


CancelledCallback = Callable[[], bool]
_SUPPORTED_PYPDF_MAJOR = 6


@dataclass(frozen=True)
class PdfBackendCapability:
    available: bool
    backend_name: str
    version: str = ""
    reason: str = ""


@dataclass(frozen=True)
class PdfPageText:
    page_number: int
    text: str = ""
    error_type: str = ""


@dataclass(frozen=True)
class PdfDocumentText:
    page_count: int
    encrypted: bool
    pages: tuple[PdfPageText, ...] = ()


class PdfBackend(Protocol):
    def probe(self) -> PdfBackendCapability: ...

    def extract_document(
        self,
        source_path: Path,
        *,
        max_pages: int,
        cancelled: CancelledCallback | None = None,
    ) -> PdfDocumentText: ...


class PdfBackendError(RuntimeError):
    """Sanitized backend failure that does not retain source content."""

    def __init__(self, error_type: str) -> None:
        super().__init__(error_type)
        self.error_type = error_type


class PdfBackendCancelledError(PdfBackendError):
    pass


class PdfPageLimitExceededError(PdfBackendError):
    def __init__(self, page_count: int, limit: int) -> None:
        super().__init__("PdfPageLimitExceeded")
        self.page_count = page_count
        self.limit = limit


class PypdfBackend:
    backend_name = "pypdf"

    def probe(self) -> PdfBackendCapability:
        if _pypdf is None:
            return PdfBackendCapability(
                available=False,
                backend_name=self.backend_name,
                reason=_pypdf_import_error_type or "ImportError",
            )
        version = str(getattr(_pypdf, "__version__", ""))
        major = _version_major(version)
        if major != _SUPPORTED_PYPDF_MAJOR:
            return PdfBackendCapability(
                available=False,
                backend_name=self.backend_name,
                version=version,
                reason="unsupported_version",
            )
        return PdfBackendCapability(
            available=True,
            backend_name=self.backend_name,
            version=version,
        )

    def extract_document(
        self,
        source_path: Path,
        *,
        max_pages: int,
        cancelled: CancelledCallback | None = None,
    ) -> PdfDocumentText:
        capability = self.probe()
        if not capability.available:
            raise PdfBackendError(capability.reason or "PdfBackendUnavailable")
        self._raise_if_cancelled(cancelled)
        try:
            assert _pypdf is not None
            reader = _pypdf.PdfReader(str(source_path), strict=False)
            encrypted = bool(reader.is_encrypted)
            if encrypted:
                return PdfDocumentText(page_count=0, encrypted=True)
            page_count = len(reader.pages)
        except PdfBackendCancelledError:
            raise
        except Exception as exc:
            raise PdfBackendError(type(exc).__name__) from exc

        if page_count > max_pages:
            raise PdfPageLimitExceededError(page_count, max_pages)

        pages: list[PdfPageText] = []
        for index in range(page_count):
            self._raise_if_cancelled(cancelled)
            try:
                text = reader.pages[index].extract_text() or ""
                pages.append(PdfPageText(page_number=index + 1, text=text))
            except Exception as exc:
                pages.append(
                    PdfPageText(
                        page_number=index + 1,
                        error_type=type(exc).__name__,
                    )
                )
        self._raise_if_cancelled(cancelled)
        return PdfDocumentText(
            page_count=page_count,
            encrypted=False,
            pages=tuple(pages),
        )

    @staticmethod
    def _raise_if_cancelled(cancelled: CancelledCallback | None) -> None:
        if cancelled is not None and cancelled():
            raise PdfBackendCancelledError("PdfBackendCancelled")


def default_pdf_backend() -> PdfBackend:
    return PypdfBackend()


def probe_pdf_backend(backend: PdfBackend | None = None) -> PdfBackendCapability:
    return (backend or default_pdf_backend()).probe()


def _version_major(version: str) -> int | None:
    match = re.match(r"\s*(\d+)", version)
    return int(match.group(1)) if match else None
