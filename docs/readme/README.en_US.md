# CharaPicker (English)

[简体中文](../../README.md) | [繁體中文](README.zh_TW.md) | [日本語](README.ja_JP.md)

## Overview

CharaPicker is a desktop tool that extracts character-focused information from anime, manga, video, image, or text materials, then compiles structured character profiles and insights.

## Core Goals

- Extract Once: process source materials once and build a reusable knowledge base.
- Targeted Insight: generate focused insights for target characters or world settings.
- Visible Thinking: show key insight flow in UI, not just debug logs.

## Current Status

- Version: `v0.7.0-beta` (in development)
- Document updated: `2026-07-20`

## Implemented

- Startup and warmup flow: splash, theme apply, basic environment checks.
- Main UI skeleton: project, character cards, model, prompt, settings, and about pages.
- Project config management: save/load and recent project listing.
- Material processing flow: import into `raw/`, link/process into `materials/`, FFmpeg split/transcode options.
- Multi-material extraction: video, image, audio, and text share the run-plan, preview/formal dispatch, knowledge-base aggregation, and source-trace foundations.
- Input preprocessing: ZIP, CBZ, EPUB, text-based PDF, 7z, RAR, and CBR are converted into existing text or image material flows.
- Insight UI: InsightStreamPanel card timeline with streaming updates.
- Cloud model integration: unified OpenAI-compatible middleware with token usage logging.
- Preview pipeline connected: `project -> extractor -> insight stream -> preview knowledge base`.
- Character card page: project-scoped card gallery, search, create, edit, cover crop, preview, compile, import, and export.

## Progress

- Done: runnable UI, four-media extraction foundations, character-card lifecycle, and controlled preprocessing for seven complex input formats.
- In progress: generating higher-quality reusable structured insights from real materials.
- Next focus: improve real-material extraction quality, knowledge-base quality, character-card conflict resolution, and quality evaluation.

## Not Yet Implemented

- Multi-material content now enters the common preview and formal-extraction foundations, while real-material quality, cross-content association, and failure feedback still need continued validation.
- Character card compilation can generate CharaPicker JSON from the formal knowledge base, with layered evidence, alias reclassification, quality diagnostics, and protection against compiling characters with no direct evidence.
- Stable automatic write-back loop to `facts.json` and `targeted_insights.json` is not complete.

## Requirements

- Python `>=3.10`
- `pypdf>=6.14.2,<7` for text-based PDF preprocessing

## Supported Inputs

- Direct materials: common video, static image, audio, TXT/Markdown/JSON, SRT/ASS, and related formats.
- Controlled preprocessing: `.zip`, `.cbz`, `.epub`, `.pdf`, `.7z`, `.rar`, and `.cbr`.
- The first PDF implementation extracts existing text only and does not run OCR. Encrypted PDFs, DRM EPUB files, and password-protected archives are rejected explicitly.
- 7z/RAR/CBR require a local 7-Zip installation. CharaPicker checks project-local `bin/` locations, `PATH`, standard Windows install locations, and `CHARAPICKER_7ZIP_PATH`; it does not download 7-Zip.
- Nested containers are not expanded recursively. Original containers remain in `raw/`; derived materials and source mappings are stored under `materials/derived_inputs/` and preprocessing manifests.

## Install

```powershell
python -m pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

## Feature Overview

- Project-scoped material management (`projects/{project_id}`)
- Character card management with CharaPicker JSON as the source of truth
- Insight event stream during extraction (Insight Stream)
- Character card Markdown, HTML, Character Card V2 JSON, and AstrBot copy-list export (iterating)

## Screenshots

- Screenshot docs are pending.

## Documentation

- [简体中文 README](../../README.md)
- [繁體中文 README](README.zh_TW.md)
- [日本語 README](README.ja_JP.md)
- [Changelog](../../CHANGELOG.md)
- [docs Architecture](../ARCHITECTURE.md)
- [Root Architecture](../../ARCHITECTURE.md)

## Development Notes

- Keep clear boundaries across `core` / `gui` / `utils`.
- Route user-visible UI strings through `i18n/` instead of long-term hardcoding.
- Keep runtime resources under `res/`.

## License

- CharaPicker's own source code is licensed under [Mozilla Public License 2.0](../../LICENSE) (`MPL-2.0`).
- Third-party dependencies and bundled components remain under their own licenses. See [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
- Current open-source builds use GPL-licensed PyQt6 / PyQt6-Fluent-Widgets components; binary distribution must also comply with those third-party license obligations.
