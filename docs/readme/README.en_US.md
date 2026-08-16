# CharaPicker (English)

[简体中文](../../README.md) | [繁體中文](README.zh_TW.md) | [日本語](README.ja_JP.md)

## What This Is

CharaPicker is a personal experimental desktop tool. It tries to pull character-related information out of anime, manga, video, image, audio, and text materials, then turn that information into a traceable knowledge base and character profiles.

It is not mature commercial software, and it is not something I would treat as a production-grade tool for important data. The project is largely pure vibe coding: trying ideas, writing the thing, reshaping it, and using AI to move quickly from an idea to working code. The docs try to be explicit about what works, what is still shaky, and where you should use your own judgment.

## What I Am Trying to Solve

- Materials should not be analyzed from scratch every time. Once processed, useful results should land in a reusable knowledge base.
- Character cards should not depend on a single free-form model response. Later generation should prefer structured results and evidence.
- Long-running jobs should not be a black box. Extraction, skips, failures, and aggregation should be visible in the UI.

## Current Status

- Currently in the 1.0 RC (release candidate) stage and validating the first stable baseline. This is not the final stable release; extraction quality and a small number of data contracts may still change.
- Official binaries are currently Windows x64 only. Running from source supports Python `>=3.10`; release packages use a locked Windows build environment.
- For the latest build and version notes, see [GitHub Releases](https://github.com/yomihime/CharaPicker/releases) and the [Changelog](../../CHANGELOG.md).

## What Works Now

- Create projects, import materials, keep original files under `raw/`, and process working entries into `materials/`.
- Scan video, image, audio, and text materials into preview or formal extraction run plans.
- Preprocess ZIP, CBZ, EPUB, text-based PDF, 7z, RAR, and CBR into existing text or image flows.
- Call OpenAI-compatible or DashScope cloud backends through shared middleware and record token usage.
- Show important extraction events in the insight stream instead of leaving everything in logs.
- Manage project-scoped character cards: create, edit, crop covers, preview, compile, import, and export.
- Compile CharaPicker JSON from the formal knowledge base and export Markdown, HTML, Character Card V2 JSON, and AstrBot copy lists.

## Still Shaky

- Real-material extraction quality still needs work, especially across episodes, media types, and long text context.
- Character-card conflict resolution, quality evaluation, and evidence selection need more sample coverage.
- Early knowledge-base files such as `facts.json` and `targeted_insights.json` do not yet have a stable automatic write-back loop.
- Cloud model calls cost money and can fail, refuse a request, or hallucinate. Important character facts need human review.
- Local model execution is not wired up yet. Downloaders, runtime detection, or UI placeholders do not mean local inference is supported.

## Data, Privacy, and Updates

- `projects/` is the user-data root. CharaPicker keeps one recent valid backup for critical configuration and character cards and offers recovery when corruption is detected, but this is not a complete backup system. Copy `projects/` and `config.yaml` before an important upgrade.
- The updater is designed to preserve `projects/`, `config.yaml`, `log/`, `bin/`, and `models`, and to roll back when startup confirmation fails. Power loss, disk failure, or manually moved files can still fall outside automatic recovery.
- `config.yaml` may contain API keys. It is currently stored in the local application directory and is not encrypted with the operating system credential vault. Do not share it or commit it to version control.
- Materials sent to a cloud model leave your computer and are subject to the selected provider's billing, privacy, and content policies. Process only materials you are authorized to use.
- The only official download location is this project's [GitHub Releases](https://github.com/yomihime/CharaPicker/releases). Current Windows binaries are not Authenticode-signed, so Windows may show an unknown-publisher or SmartScreen warning.
- The matching `.sha256` checks downloaded bytes; GitHub artifact attestation checks the GitHub Actions build origin. Neither is a Windows publisher signature. See the [release packaging guide](../reference/release-packaging.zh_CN.md) for verification commands.

## Requirements

- Python `>=3.10`
- Official Windows x64 packages do not require a separate Python installation.
- Main dependencies:
  - `PyQt6>=6.6`
  - `PyQt6-Fluent-Widgets>=1.5`
  - `pydantic>=2.6`
  - `pypdf>=6.14.2,<7`

## Supported Inputs

- Direct materials: common video, static image, audio, TXT/Markdown/JSON, SRT/ASS, and related formats.
- Controlled preprocessing: `.zip`, `.cbz`, `.epub`, `.pdf`, `.7z`, `.rar`, and `.cbr`.
- The first PDF implementation extracts existing text only and does not run OCR. Encrypted PDFs, DRM EPUB files, and password-protected archives are rejected explicitly.
- 7z/RAR/CBR require a local 7-Zip installation. CharaPicker checks project-local `bin/` locations, `PATH`, standard Windows install locations, and `CHARAPICKER_7ZIP_PATH`; it does not download 7-Zip.
- Nested containers are not expanded recursively. Original containers remain in `raw/`; derived materials and source mappings are stored under `materials/derived_inputs/` and preprocessing manifests.
- Videos inside generic ZIP/7z/RAR archives are not expanded. Import videos as direct materials. CBZ/CBR continue to accept comic image pages only.
- Direct-video preprocessing requires FFmpeg. If it is unavailable, cancel, skip all videos and continue with other materials, or download the controlled FFmpeg runtime and retry.
- Dialogue facts for audio and video should come from subtitles or a Whisper transcript. Native audio/video understanding only adds audiovisual clues, and availability depends on the provider, API schema, and specific model.

## Install

```powershell
python -m pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

## Build

```powershell
build.bat
```

- Outputs are written to `release/`.
- Common examples:
  - `build.bat --tag=vX.Y.Z-beta`
  - `build.bat --version=X.Y.Z --stage=beta`
  - `build.bat --local`

## Main Features

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
- [GitHub Releases](https://github.com/yomihime/CharaPicker/releases)
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
