# CharaPicker (English)

[简体中文](../README.md) | [繁體中文](README.zh_TW.md) | [日本語](README.ja_JP.md)

## Overview

CharaPicker is a desktop tool that extracts character-focused information from anime, manga, video, image, or text materials, then compiles structured character profiles and insights.

## Core Goals

- Extract Once: process source materials once and build a reusable knowledge base.
- Targeted Insight: generate focused insights for target characters or world settings.
- Visible Thinking: show key insight flow in UI, not just debug logs.

## Current Status

- Version: `v0.1.0` (in development)
- Document updated: `2026-04-30`

## Implemented

- Startup and warmup flow: splash, theme apply, basic environment checks.
- Main UI skeleton: project, output, model, prompt, settings, and about pages.
- Project config management: save/load and recent project listing.
- Material processing flow: import into `raw/`, link/process into `materials/`, FFmpeg split/transcode options.
- Insight UI: InsightStreamPanel card timeline with streaming updates.
- Cloud model integration: unified OpenAI-compatible middleware with token usage logging.
- Preview pipeline connected: `project -> extractor -> insight stream -> compiler -> output`.

## Progress

- Done: runnable UI skeleton and preview main path.
- In progress: generating higher-quality reusable structured insights from real materials.
- Next focus: knowledge-base persistence, iterative compilation state updates, conflict handling, output quality.

## Not Yet Implemented

- Extraction still relies mainly on preview placeholder text, not full real-material chunk insight ingestion.
- Compilation is still placeholder-level, without full iterative compile and conflict resolution.
- Stable automatic write-back loop to `facts.json` and `targeted_insights.json` is not complete.

## Requirements

- Python `>=3.10`

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
- Target character and processing mode configuration
- Insight event stream during extraction (Insight Stream)
- Character-state compilation and structured output (iterating)

## Screenshots

- Screenshot docs are pending.

## Documentation

- [简体中文 README](../README.md)
- [繁體中文 README](README.zh_TW.md)
- [日本語 README](README.ja_JP.md)
- [doc Architecture](ARCHITECTURE.md)
- [Root Architecture](../ARCHITECTURE.md)

## Development Notes

- Keep clear boundaries across `core` / `gui` / `utils`.
- Route user-visible UI strings through `i18n/` instead of long-term hardcoding.
- Keep runtime resources under `res/`.

## License

- License TBD.
