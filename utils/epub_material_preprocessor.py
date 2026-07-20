"""EPUB package parsing behind the safe ZIP preprocessing boundary."""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from utils.material_preprocessing import (
    DerivedMaterialRecord,
    PreprocessingCancelledError,
    PreprocessingEntrySummary,
    PreprocessingExtractionSummary,
    PreprocessingRequest,
    PreprocessingWarning,
    _raise_if_cancelled,
    ensure_path_within_root,
    validate_archive_entry_path,
)
from utils.media_types import IMAGE_SUFFIXES
from utils.zip_material_preprocessor import SafeZipEntry, validate_zip_container_entries


_EPUB_MIMETYPE = b"application/epub+zip"
_EPUB_CONTAINER_PATH = "META-INF/container.xml"
_EPUB_DRM_PATHS = {"meta-inf/encryption.xml", "meta-inf/rights.xml"}
_EPUB_DOCUMENT_SUFFIXES = {".xhtml", ".html", ".htm"}
_MAX_EPUB_DOCUMENT_BYTES = 16 * 1024 * 1024
_READ_CHUNK_SIZE = 1024 * 1024
_XML_ENCODING_PATTERN = re.compile(br"encoding\s*=\s*['\"]([A-Za-z0-9._-]+)['\"]", re.I)
_UNSAFE_XML_DECLARATION_PATTERN = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", re.I)
_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
}
_SKIPPED_TAGS = {"script", "style", "svg", "math"}
_RUBY_ANNOTATION_TAGS = {"rt", "rp"}


@dataclass(frozen=True)
class _EpubManifestItem:
    item_id: str
    entry_path: str
    media_type: str
    properties: str


@dataclass(frozen=True)
class _EpubChapter:
    entry: SafeZipEntry
    spine_index: int
    media_type: str


@dataclass(frozen=True)
class _ParsedXhtml:
    text: str
    title: str
    malformed: bool


def extract_epub_materials(
    request: PreprocessingRequest,
    staged_output: Path,
) -> PreprocessingExtractionSummary:
    warnings: list[PreprocessingWarning] = []
    failed_entries: list[str] = []
    entry_summaries: list[PreprocessingEntrySummary] = []

    try:
        with zipfile.ZipFile(request.source_path) as archive:
            safe_entries, entry_count, fatal = validate_zip_container_entries(
                archive.infolist(),
                request,
                warnings,
                failed_entries,
            )
            if fatal:
                return _summary(
                    warnings,
                    failed_entries,
                    entry_summaries,
                    entry_count=entry_count,
                    fatal=True,
                )
            if any(warning.code == "entry_encrypted" for warning in warnings):
                warnings.append(
                    PreprocessingWarning(
                        code="epub_encryption_unsupported",
                        message="Encrypted EPUB entries and DRM are not supported.",
                    )
                )
                return _summary(
                    warnings,
                    failed_entries,
                    entry_summaries,
                    entry_count=entry_count,
                    fatal=True,
                )

            entries = {entry.relative_path.as_posix(): entry for entry in safe_entries}
            if any(path.casefold() in _EPUB_DRM_PATHS for path in entries):
                warnings.append(
                    PreprocessingWarning(
                        code="epub_drm_unsupported",
                        message="This EPUB declares DRM or encrypted resources, which are unsupported.",
                    )
                )
                return _summary(
                    warnings,
                    failed_entries,
                    entry_summaries,
                    entry_count=entry_count,
                    fatal=True,
                )

            _validate_mimetype(archive, entries, request, warnings, failed_entries)
            chapters, package_summaries = _discover_epub_chapters(
                archive,
                entries,
                request,
                warnings,
                failed_entries,
            )
            entry_summaries.extend(package_summaries)
            derived, chapter_summaries, expanded_size = _extract_chapters(
                archive,
                chapters,
                request,
                staged_output,
                warnings,
                failed_entries,
            )
            entry_summaries.extend(chapter_summaries)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError) as exc:
        warnings.append(
            PreprocessingWarning(
                code="epub_container_invalid",
                message="The EPUB container is damaged or unreadable.",
                context={"error_type": type(exc).__name__},
            )
        )
        return _summary(
            warnings,
            failed_entries,
            entry_summaries,
            fatal=True,
        )

    if not derived:
        warnings.append(
            PreprocessingWarning(
                code="epub_no_readable_chapters",
                message="The EPUB did not contain readable chapter text.",
            )
        )
    return PreprocessingExtractionSummary(
        derived_materials=tuple(derived),
        entry_summaries=tuple(entry_summaries),
        warnings=tuple(warnings),
        failed_entries=tuple(failed_entries),
        entry_count=entry_count,
        expanded_size_bytes=expanded_size,
    )


def _validate_mimetype(
    archive: zipfile.ZipFile,
    entries: dict[str, SafeZipEntry],
    request: PreprocessingRequest,
    warnings: list[PreprocessingWarning],
    failed_entries: list[str],
) -> None:
    entry = entries.get("mimetype")
    if entry is None:
        warnings.append(
            PreprocessingWarning(
                code="epub_mimetype_missing",
                message="The EPUB mimetype entry is missing; package discovery will continue.",
            )
        )
        return
    payload = _read_entry(
        archive,
        entry,
        request,
        warnings,
        failed_entries,
        max_bytes=1024,
    )
    if payload is not None and payload.strip() != _EPUB_MIMETYPE:
        warnings.append(
            PreprocessingWarning(
                code="epub_mimetype_invalid",
                message="The EPUB mimetype entry is invalid; package discovery will continue.",
                entry_path=entry.source_path,
            )
        )


def _discover_epub_chapters(
    archive: zipfile.ZipFile,
    entries: dict[str, SafeZipEntry],
    request: PreprocessingRequest,
    warnings: list[PreprocessingWarning],
    failed_entries: list[str],
) -> tuple[list[_EpubChapter], list[PreprocessingEntrySummary]]:
    opf_path = _discover_opf_path(
        archive,
        entries,
        request,
        warnings,
        failed_entries,
    )
    if not opf_path:
        return _fallback_chapters(entries, warnings), _image_entry_summaries(entries, {})

    opf_entry = entries.get(opf_path)
    if opf_entry is None:
        warnings.append(
            PreprocessingWarning(
                code="epub_opf_missing_fallback",
                message="The EPUB package document is missing; XHTML entry order is used.",
                entry_path=opf_path,
            )
        )
        return _fallback_chapters(entries, warnings), _image_entry_summaries(entries, {})

    opf_payload = _read_xml_entry(
        archive,
        opf_entry,
        request,
        warnings,
        failed_entries,
        invalid_code="epub_opf_invalid_fallback",
    )
    if opf_payload is None:
        return _fallback_chapters(entries, warnings), _image_entry_summaries(entries, {})
    try:
        root = ElementTree.fromstring(opf_payload)
    except ElementTree.ParseError:
        warnings.append(
            PreprocessingWarning(
                code="epub_opf_invalid_fallback",
                message="The EPUB package document is malformed; XHTML entry order is used.",
                entry_path=opf_path,
            )
        )
        failed_entries.append(opf_path)
        return _fallback_chapters(entries, warnings), _image_entry_summaries(entries, {})

    manifest_items = _parse_opf_manifest(root, PurePosixPath(opf_path).parent, warnings)
    manifest_by_id = {item.item_id: item for item in manifest_items}
    spine_ids = [
        str(element.attrib.get("idref", "")).strip()
        for element in root.iter()
        if _local_name(element.tag) == "itemref"
        and str(element.attrib.get("linear", "yes")).lower() != "no"
    ]
    ordered_items = [manifest_by_id[item_id] for item_id in spine_ids if item_id in manifest_by_id]
    if not ordered_items:
        warnings.append(
            PreprocessingWarning(
                code="epub_spine_missing_fallback",
                message="The EPUB spine is missing or empty; manifest document order is used.",
                entry_path=opf_path,
            )
        )
        ordered_items = [
            item for item in manifest_items if _is_document_item(item)
        ]

    chapters: list[_EpubChapter] = []
    seen_paths: set[str] = set()
    for item in ordered_items:
        if not _is_document_item(item) or item.entry_path in seen_paths:
            continue
        entry = entries.get(item.entry_path)
        if entry is None:
            warnings.append(
                PreprocessingWarning(
                    code="epub_spine_entry_missing",
                    message="An EPUB spine document is missing from the container.",
                    entry_path=item.entry_path,
                )
            )
            failed_entries.append(item.entry_path)
            continue
        seen_paths.add(item.entry_path)
        chapters.append(
            _EpubChapter(
                entry=entry,
                spine_index=len(chapters) + 1,
                media_type=item.media_type,
            )
        )

    summaries = [
        PreprocessingEntrySummary(
            source_entry_path=opf_path,
            role="package",
            media_type="text",
            media_subtype="application/oebps-package+xml",
            size_bytes=opf_entry.info.file_size,
        ),
        *_image_entry_summaries(entries, {item.entry_path: item for item in manifest_items}),
    ]
    return chapters, summaries


def _discover_opf_path(
    archive: zipfile.ZipFile,
    entries: dict[str, SafeZipEntry],
    request: PreprocessingRequest,
    warnings: list[PreprocessingWarning],
    failed_entries: list[str],
) -> str:
    container_entry = entries.get(_EPUB_CONTAINER_PATH)
    if container_entry is None:
        warnings.append(
            PreprocessingWarning(
                code="epub_opf_missing_fallback",
                message="EPUB container metadata is missing; XHTML entry order is used.",
                entry_path=_EPUB_CONTAINER_PATH,
            )
        )
        return ""
    payload = _read_xml_entry(
        archive,
        container_entry,
        request,
        warnings,
        failed_entries,
        invalid_code="epub_container_metadata_invalid",
    )
    if payload is None:
        return ""
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        warnings.append(
            PreprocessingWarning(
                code="epub_container_metadata_invalid",
                message="EPUB container metadata is malformed; XHTML entry order is used.",
                entry_path=container_entry.source_path,
            )
        )
        failed_entries.append(container_entry.source_path)
        return ""
    for element in root.iter():
        if _local_name(element.tag) != "rootfile":
            continue
        full_path = str(element.attrib.get("full-path", "")).strip()
        resolved = _normalize_epub_reference(PurePosixPath("."), full_path)
        if resolved:
            return resolved
    warnings.append(
        PreprocessingWarning(
            code="epub_opf_missing_fallback",
            message="EPUB container metadata has no package path; XHTML entry order is used.",
            entry_path=container_entry.source_path,
        )
    )
    return ""


def _parse_opf_manifest(
    root: ElementTree.Element,
    opf_parent: PurePosixPath,
    warnings: list[PreprocessingWarning],
) -> list[_EpubManifestItem]:
    items: list[_EpubManifestItem] = []
    for element in root.iter():
        if _local_name(element.tag) != "item":
            continue
        item_id = str(element.attrib.get("id", "")).strip()
        href = str(element.attrib.get("href", "")).strip()
        entry_path = _normalize_epub_reference(opf_parent, href)
        if not item_id or not entry_path:
            warnings.append(
                PreprocessingWarning(
                    code="epub_manifest_item_invalid",
                    message="An EPUB manifest item has an unsafe or incomplete path and was skipped.",
                    entry_path=href or None,
                )
            )
            continue
        items.append(
            _EpubManifestItem(
                item_id=item_id,
                entry_path=entry_path,
                media_type=str(element.attrib.get("media-type", "")).strip().lower(),
                properties=str(element.attrib.get("properties", "")).strip().lower(),
            )
        )
    return items


def _fallback_chapters(
    entries: dict[str, SafeZipEntry],
    warnings: list[PreprocessingWarning],
) -> list[_EpubChapter]:
    documents = sorted(
        (
            entry
            for entry in entries.values()
            if entry.relative_path.suffix.lower() in _EPUB_DOCUMENT_SUFFIXES
        ),
        key=lambda entry: entry.relative_path.as_posix().casefold(),
    )
    if documents:
        warnings.append(
            PreprocessingWarning(
                code="epub_document_order_fallback",
                message="EPUB chapter order was inferred from document paths.",
            )
        )
    return [
        _EpubChapter(
            entry=entry,
            spine_index=index,
            media_type="application/xhtml+xml",
        )
        for index, entry in enumerate(documents, start=1)
    ]


def _image_entry_summaries(
    entries: dict[str, SafeZipEntry],
    manifest_items: dict[str, _EpubManifestItem],
) -> list[PreprocessingEntrySummary]:
    summaries: list[PreprocessingEntrySummary] = []
    for path, entry in sorted(entries.items()):
        item = manifest_items.get(path)
        media_type = item.media_type if item is not None else ""
        if not media_type.startswith("image/") and entry.relative_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        summaries.append(
            PreprocessingEntrySummary(
                source_entry_path=path,
                role="image",
                media_type="image",
                media_subtype=media_type,
                size_bytes=entry.info.file_size,
                status="observed_not_materialized",
            )
        )
    return summaries


def _extract_chapters(
    archive: zipfile.ZipFile,
    chapters: list[_EpubChapter],
    request: PreprocessingRequest,
    staged_output: Path,
    warnings: list[PreprocessingWarning],
    failed_entries: list[str],
) -> tuple[list[DerivedMaterialRecord], list[PreprocessingEntrySummary], int]:
    derived: list[DerivedMaterialRecord] = []
    summaries: list[PreprocessingEntrySummary] = []
    expanded_size = 0
    for chapter in chapters:
        _raise_if_cancelled(request.cancelled)
        payload = _read_entry(
            archive,
            chapter.entry,
            request,
            warnings,
            failed_entries,
            max_bytes=_MAX_EPUB_DOCUMENT_BYTES,
        )
        if payload is None:
            summaries.append(_chapter_summary(chapter, status="read_failed"))
            continue
        if _UNSAFE_XML_DECLARATION_PATTERN.search(payload):
            warnings.append(
                PreprocessingWarning(
                    code="epub_xhtml_unsafe_declaration",
                    message="An XHTML chapter contains a DTD or entity declaration and was skipped.",
                    entry_path=chapter.entry.source_path,
                )
            )
            failed_entries.append(chapter.entry.source_path)
            summaries.append(_chapter_summary(chapter, status="unsafe_declaration"))
            continue
        parsed = _parse_xhtml(payload)
        if parsed.malformed:
            warnings.append(
                PreprocessingWarning(
                    code="epub_xhtml_malformed_fallback",
                    message="A malformed XHTML chapter was converted with the tolerant text parser.",
                    entry_path=chapter.entry.source_path,
                )
            )
        if not parsed.text:
            warnings.append(
                PreprocessingWarning(
                    code="epub_chapter_empty",
                    message="An EPUB chapter had no readable text and was skipped.",
                    entry_path=chapter.entry.source_path,
                )
            )
            failed_entries.append(chapter.entry.source_path)
            summaries.append(_chapter_summary(chapter, title=parsed.title, status="empty"))
            continue

        output_relative = PurePosixPath(
            "text",
            "chapters",
            f"chapter_{chapter.spine_index:04d}.txt",
        )
        target = ensure_path_within_root(staged_output, output_relative)
        output_bytes = (parsed.text.rstrip() + "\n").encode("utf-8")
        if expanded_size + len(output_bytes) > request.limits.max_expanded_size_bytes:
            warnings.append(
                PreprocessingWarning(
                    code="expanded_size_limit_exceeded",
                    message="Derived EPUB chapter text exceeds the expanded size limit.",
                    entry_path=chapter.entry.source_path,
                    context={
                        "expanded_size_bytes": expanded_size + len(output_bytes),
                        "limit": request.limits.max_expanded_size_bytes,
                    },
                )
            )
            failed_entries.append(chapter.entry.source_path)
            summaries.append(
                _chapter_summary(chapter, title=parsed.title, status="size_limit_exceeded")
            )
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(output_bytes)
        expanded_size += len(output_bytes)
        derived.append(
            DerivedMaterialRecord(
                material_relative_path=PurePosixPath(
                    request.output_root_reference,
                    *output_relative.parts,
                ).as_posix(),
                source_entry_path=chapter.entry.source_path,
                media_type="text",
                content_form_hint="novel",
                original_name=PurePosixPath(chapter.entry.source_path).name,
                size_bytes=len(output_bytes),
                fingerprint=f"sha256:{hashlib.sha256(output_bytes).hexdigest()}",
                chapter_index=chapter.spine_index,
            )
        )
        summaries.append(_chapter_summary(chapter, title=parsed.title, status="materialized"))
    return derived, summaries, expanded_size


def _read_xml_entry(
    archive: zipfile.ZipFile,
    entry: SafeZipEntry,
    request: PreprocessingRequest,
    warnings: list[PreprocessingWarning],
    failed_entries: list[str],
    *,
    invalid_code: str,
) -> bytes | None:
    payload = _read_entry(
        archive,
        entry,
        request,
        warnings,
        failed_entries,
        max_bytes=_MAX_EPUB_DOCUMENT_BYTES,
    )
    if payload is not None and _UNSAFE_XML_DECLARATION_PATTERN.search(payload):
        warnings.append(
            PreprocessingWarning(
                code=invalid_code,
                message="EPUB XML metadata contains an unsafe DTD or entity declaration.",
                entry_path=entry.source_path,
            )
        )
        failed_entries.append(entry.source_path)
        return None
    return payload


def _read_entry(
    archive: zipfile.ZipFile,
    entry: SafeZipEntry,
    request: PreprocessingRequest,
    warnings: list[PreprocessingWarning],
    failed_entries: list[str],
    *,
    max_bytes: int,
) -> bytes | None:
    if entry.info.file_size > max_bytes:
        warnings.append(
            PreprocessingWarning(
                code="epub_document_size_limit_exceeded",
                message="An EPUB metadata or chapter document exceeds the parser size limit.",
                entry_path=entry.source_path,
                context={"size_bytes": entry.info.file_size, "limit": max_bytes},
            )
        )
        failed_entries.append(entry.source_path)
        return None
    payload = bytearray()
    try:
        with archive.open(entry.info, "r") as source:
            while chunk := source.read(_READ_CHUNK_SIZE):
                _raise_if_cancelled(request.cancelled)
                payload.extend(chunk)
                if len(payload) > max_bytes:
                    raise ValueError("EPUB document exceeded its parser size limit")
    except PreprocessingCancelledError:
        raise
    except (
        EOFError,
        NotImplementedError,
        OSError,
        RuntimeError,
        ValueError,
        zipfile.BadZipFile,
    ) as exc:
        warnings.append(
            PreprocessingWarning(
                code="epub_entry_read_failed",
                message="An EPUB entry could not be read safely.",
                entry_path=entry.source_path,
                context={"error_type": type(exc).__name__},
            )
        )
        failed_entries.append(entry.source_path)
        return None
    return bytes(payload)


def _parse_xhtml(payload: bytes) -> _ParsedXhtml:
    text = _decode_xhtml(payload)
    malformed = False
    try:
        ElementTree.fromstring(text)
    except ElementTree.ParseError:
        malformed = True
    parser = _XhtmlTextParser()
    parser.feed(text)
    parser.close()
    return _ParsedXhtml(
        text=_normalize_extracted_text("".join(parser.parts)),
        title=_normalize_extracted_text("".join(parser.title_parts)).replace("\n", " "),
        malformed=malformed,
    )


def _decode_xhtml(payload: bytes) -> str:
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        return payload.decode("utf-16", errors="replace")
    if payload.startswith(b"\xef\xbb\xbf"):
        return payload.decode("utf-8-sig", errors="replace")
    encoding_match = _XML_ENCODING_PATTERN.search(payload[:512])
    encoding = encoding_match.group(1).decode("ascii", errors="ignore") if encoding_match else "utf-8"
    try:
        return payload.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def _normalize_extracted_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in value.split("\n")]
    normalized: list[str] = []
    for line in lines:
        if not line and (not normalized or not normalized[-1]):
            continue
        normalized.append(line)
    return "\n".join(normalized).strip()


def _normalize_epub_reference(parent: PurePosixPath, href: str) -> str:
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        return ""
    decoded = unquote(parsed.path).replace("\\", "/")
    if not decoded or decoded.startswith("/"):
        return ""
    parts: list[str] = []
    for part in (*parent.parts, *PurePosixPath(decoded).parts):
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return ""
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        return ""
    validation = validate_archive_entry_path(PurePosixPath(*parts).as_posix())
    return validation.relative_path.as_posix() if validation.relative_path is not None else ""


def _is_document_item(item: _EpubManifestItem) -> bool:
    return (
        item.media_type in {"application/xhtml+xml", "text/html"}
        or PurePosixPath(item.entry_path).suffix.lower() in _EPUB_DOCUMENT_SUFFIXES
    )


def _local_name(tag: object) -> str:
    value = str(tag)
    return value.rsplit("}", maxsplit=1)[-1].lower()


def _chapter_summary(
    chapter: _EpubChapter,
    *,
    title: str = "",
    status: str,
) -> PreprocessingEntrySummary:
    return PreprocessingEntrySummary(
        source_entry_path=chapter.entry.source_path,
        role="chapter",
        media_type="text",
        media_subtype=chapter.media_type,
        spine_index=chapter.spine_index,
        title=title,
        size_bytes=chapter.entry.info.file_size,
        status=status,
    )


def _summary(
    warnings: list[PreprocessingWarning],
    failed_entries: list[str],
    entry_summaries: list[PreprocessingEntrySummary],
    *,
    entry_count: int = 0,
    fatal: bool,
) -> PreprocessingExtractionSummary:
    return PreprocessingExtractionSummary(
        entry_summaries=tuple(entry_summaries),
        warnings=tuple(warnings),
        failed_entries=tuple(failed_entries),
        entry_count=entry_count,
        fatal=fatal,
    )


class _XhtmlTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._head_depth = 0
        self._title_depth = 0
        self._skip_depth = 0
        self._ruby_annotation_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized == "head":
            self._head_depth += 1
        if normalized == "title":
            self._title_depth += 1
        if normalized in _SKIPPED_TAGS:
            self._skip_depth += 1
        if normalized in _RUBY_ANNOTATION_TAGS:
            self._ruby_annotation_depth += 1
        if normalized == "br" or normalized in _BLOCK_TAGS:
            self.parts.append("\n")
        if normalized == "img" and not self._head_depth and not self._skip_depth:
            attributes = {key.lower(): value or "" for key, value in attrs}
            alt = attributes.get("alt", "").strip()
            if alt:
                self.parts.extend(("\n", f"[Image: {alt}]", "\n"))

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in _BLOCK_TAGS:
            self.parts.append("\n")
        if normalized in _RUBY_ANNOTATION_TAGS and self._ruby_annotation_depth:
            self._ruby_annotation_depth -= 1
        if normalized in _SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if normalized == "title" and self._title_depth:
            self._title_depth -= 1
        if normalized == "head" and self._head_depth:
            self._head_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self.title_parts.append(data)
        if self._head_depth or self._skip_depth or self._ruby_annotation_depth:
            return
        self.parts.append(data)
