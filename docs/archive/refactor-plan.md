# Refactor Plan

This document is the execution plan for upcoming CharaPicker structure cleanup work.
It is based on the current repository state confirmed during the structure diagnosis.
Future Codex sessions should use this plan as guidance, but must still verify current
code before making changes.

Each implementation round should advance one milestone by default. Do not combine
multiple milestones unless the user explicitly asks for a larger batch.

## Execution status

All currently planned executable milestones were completed on 2026-05-13.

Final validation:

- `python -m compileall main.py core gui utils`: passed.
- `python -m ruff check .`: passed.

No tests, typecheck command, or build command were run because this repository does
not currently define a dedicated test suite or typecheck workflow, and the refactor
did not require packaging validation.

Post-review Major fixes on 2026-05-13:

- Preview-created chunk results are now merged into `episode_content.json` before
  the output page tries knowledge-base-backed compilation.
- Knowledge-base content loaders now reject non-object JSON instead of silently
  treating it as empty content.
- Preview output falls back to the placeholder compiler if knowledge-base-backed
  compilation raises.

Post-review validation:

- `python -m compileall core gui`: passed.
- `python -m ruff check core gui`: passed.
- `conda run -n CharaPicker python tmp_refactor_smoke.py`: passed with a temporary
  smoke script that was deleted after the run.

## 1. Background

CharaPicker is moving from a runnable PyQt6 UI skeleton and preview path toward the
next core product loop: Extract Once, reusable knowledge-base persistence, iterative
character-state compilation, conflict handling, and higher-quality output generation.

The current repository already has useful boundaries:

- `core/` contains domain models, extraction, compilation, and output rendering.
- `gui/` contains PyQt6/qfluentwidgets pages, workers, and widgets.
- `utils/` contains runtime middleware, project paths, material processing, model
  calls, preferences, logging, and startup warmup.
- `projects/{project_id}/knowledge_base/` is the intended Extract Once persistence
  target.

However, several central files have grown into mixed-responsibility modules. The
most important pressure point is that knowledge-base reads and writes, preview
orchestration, model calls, JSON parsing, and UI-facing event emission are still
too close together. If the next core features are added directly on top of that
shape, later changes to the knowledge-base format or extraction flow will likely
touch too many files at once.

This cleanup is therefore intended to make the next product work easier and safer,
not to redesign the application.

## 2. Goals

- Establish a clearer boundary around `projects/{project_id}/knowledge_base/`
  reads, writes, and path conventions.
- Keep `Extractor` as the UI-facing extraction entry point while reducing its
  internal responsibilities.
- Make preview, full extraction, and later character-card generation rely on the
  same structured knowledge-base outputs where practical.
- Reduce UI/page coupling to filesystem details, especially around raw/materials
  state.
- Preserve the existing `core / gui / utils` architecture and current user-facing
  behavior.
- Make each refactor step small enough to review, validate, and roll back.

## 3. Non-goals

- Do not rewrite the application from scratch.
- Do not replace PyQt6/qfluentwidgets or change the desktop UI architecture.
- Do not introduce non-essential new dependencies.
- Do not change user-visible behavior unless a later milestone explicitly calls out
  the behavior and the user approves it.
- Do not migrate existing project data formats without a separate migration plan.
- Do not redesign `projects/` layout beyond conservative helper boundaries.
- Do not turn roadmap or planning documents into claims about what the current code
  already implements.
- Do not do broad abstraction only for style or naming symmetry.
- Do not combine unrelated cleanup with feature work.

## 4. Current structural issues

The following issues were confirmed from current code and documentation. They are
the main targets for planned cleanup.

- `core/extractor.py` currently combines Qt signal ownership, source scanning,
  knowledge-base path construction, JSON read/write, chunk result formatting,
  video preview model calls, event emission, progress reporting, and preview
  orchestration.
- Knowledge-base access is spread across `core/extractor.py`, `core/compiler.py`,
  and path helpers. There is no narrow repository-style module for manifest,
  chunk, episode, season, and stage-state IO.
- `core/compiler.py` reads `episode_content.json` directly and writes
  `character_stage_states.json` directly. This is workable now, but it will become
  fragile if the knowledge-base schema changes.
- `gui/main_window.py` still uses the simplified placeholder
  `compile_character_state()` output after preview succeeds, so the output page is
  not yet tightly connected to the structured knowledge-base results.
- `gui/pages/project_page.py` contains UI construction, project CRUD, source list
  state, raw/materials status calculation, FFmpeg download flow, material processing
  worker wiring, raw cleanup, and source removal.
- Some page logic directly knows raw/materials mapping details that should remain
  reusable outside the page.
- `gui/pages/model_page.py` is large and contains model workers, request setup,
  preset persistence, stream rendering, and UI state. This is a maintenance issue,
  but it is not the first blocker for the next Extract Once work.
- `utils/ffmpeg_tool.py` is also large and mixes detection, device capability
  probing, command construction, execution, progress parsing, and rollback helpers.
  It is important but can be handled after the knowledge-base and extraction path.
- Some documentation is ahead of or behind code. For example,
  `docs/preview-real-result-ingestion-plan.zh_CN.md` contains a status note that
  says parts of the plan were superseded, while later text still describes preview
  as placeholder-based. Future implementation must re-check current code before
  treating that document as factual.

## 5. Target direction

The target direction is conservative: add narrow helpers around existing behavior,
then move responsibilities behind those helpers gradually.

Preferred direction:

- Keep `core.models` as the central place for structured business models.
- Add a small `core/knowledge_base.py` module or equivalent boundary for
  knowledge-base file paths and JSON IO.
- Keep `core.extractor.Extractor` as the public extraction facade used by the UI,
  but delegate storage, source scanning, preview input collection, and result
  formatting internally.
- Keep all model execution behind `utils.ai_model_middleware`.
- Keep material import and raw/materials operations behind `utils.source_importer`
  and `utils.material_processing_middleware`.
- Keep UI pages responsible for triggering actions, wiring signals, and displaying
  feedback.
- Prefer small function or module extraction over class-heavy architecture.

Potential target shape:

```text
core/
  models.py
  knowledge_base.py
  extractor.py
  compiler.py
  generator.py

gui/
  main_window.py
  pages/
  widgets/

utils/
  material_processing_middleware.py
  source_importer.py
  ffmpeg_tool.py
  ai_model_middleware.py
```

This is a direction, not a commitment to create every file immediately.

## 6. Milestones

### Milestone 1: Knowledge-Base Access Boundary

**Status**

Completed on 2026-05-13.

**Goal**

Create a single narrow boundary for reading, writing, and locating knowledge-base
artifacts.

**Scope**

- `core/extractor.py`
- `core/compiler.py`
- `core/models.py` if additional small structured models are needed
- New `core/knowledge_base.py` or an equivalently narrow module

**Key actions**

- Centralize paths for `source_manifest.json`, chunk files, `episode_content.json`,
  `episode_summary.json`, `season_content.json`, `season_summary.json`, and
  `character_stage_states.json`.
- Move JSON read/write helpers behind this boundary.
- Preserve existing file names and directory layout.
- Keep existing `Extractor` and compiler public functions available while they
  delegate storage work to the new boundary.

**Acceptance criteria**

- Existing knowledge-base files are read and written in the same locations as before.
- `Extractor` no longer manually constructs every knowledge-base path for common
  artifacts.
- `compiler` uses the same boundary for episode and stage-state IO.
- No user-visible UI behavior changes.
- Basic import/static checks pass if available.

**Risks**

- A path mismatch could make existing project data invisible.
- JSON validation differences could reject legacy or partially written files.
- Too much schema modeling at this stage could slow feature work.

**Rollback**

- Keep public call signatures stable.
- Revert calls back to the original inline path and JSON logic if the boundary
  causes compatibility issues.

**Implementation result**

- Added `core/knowledge_base.py` as the narrow access boundary for knowledge-base
  paths and JSON IO.
- Routed `core/extractor.py` knowledge-base writes, reads, chunk listing, episode
  summaries, season summaries, and previous-season summary loading through that
  boundary.
- Routed `core/compiler.py` episode-content reads and character stage-state writes
  through the same boundary.
- Kept existing public function names in `Extractor` and `compiler` intact.
- Preserved current file names and directory layout.

**Validation**

- `python -m compileall core`: passed.
- `python -m ruff check core`: passed.

**Plan deviation**

- No intentional behavior or data-layout change.
- `core/extractor.py` still uses `utils.paths.ensure_project_tree()` for
  `materials/` access; this remains outside the M1 knowledge-base boundary and is
  expected to be handled later only if needed.

### Milestone 2: Extractor Responsibility Split

**Status**

Completed on 2026-05-13.

**Goal**

Keep `Extractor` as the extraction facade while reducing mixed responsibilities
inside `core/extractor.py`.

**Scope**

- `core/extractor.py`
- Knowledge-base boundary from Milestone 1
- Optional small helper module for preview input collection or source scanning

**Key actions**

- Separate source directory scanning from preview orchestration.
- Separate preview material/chunk collection from model-call execution.
- Route chunk save/merge/summary work through the knowledge-base boundary.
- Keep event emission and progress callbacks compatible with current UI wiring.
- Avoid changing model provider behavior in this milestone.

**Acceptance criteria**

- `run_preview_streaming()` still works as the UI-facing entry point.
- No-cloud-preset, no-readable-chunk, and successful-preview paths still emit
  equivalent events/progress.
- Chunk JSON output remains compatible with the existing structure.
- The code path is easier to extend for full extraction without adding another
  large block to `Extractor`.

**Risks**

- Signal/callback timing may change subtly.
- Preview error handling may lose current fallback behavior if split too
  aggressively.
- The split may expose unclear ownership between extraction and model preset
  selection.

**Rollback**

- Keep the old orchestration behavior available while extracting helpers.
- If a helper changes runtime behavior, inline only that helper back into
  `Extractor` and keep the rest of the milestone.

**Implementation result**

- Added `core/source_scanner.py` for source directory scanning, preview video chunk
  collection, and preview chunk identity calculation.
- Kept `Extractor.scan_source_directory()` and the preview helper methods as
  delegating entry points so existing callers remain compatible.
- Left model-call execution in `Extractor` for now; only collection and identity
  logic moved out in this milestone to keep behavior stable.

**Validation**

- `python -m compileall core`: passed.
- `python -m ruff check core`: passed.

**Plan deviation**

- The split intentionally avoided moving cloud preset selection or video model
  execution. That keeps provider behavior unchanged and leaves deeper extraction
  orchestration changes for a future feature milestone if needed.

### Milestone 3: Project Page Material-State Boundary

**Status**

Completed on 2026-05-13.

**Goal**

Move reusable raw/materials status logic out of `ProjectPage` while keeping the UI
flow intact.

**Scope**

- `gui/pages/project_page.py`
- `utils/source_importer.py`
- Optional new helper such as `utils/source_status.py`

**Key actions**

- Extract raw/materials mapping and source status calculation into a non-UI helper.
- Keep dialogs, button state, list rendering, and InfoBars in `ProjectPage`.
- Keep source import, removal, and raw cleanup through existing utilities.
- Preserve current status labels and i18n keys.

**Acceptance criteria**

- Adding sources, processing sources, refreshing project sources, cleaning raw, and
  removing sources keep the same visible behavior.
- `ProjectPage` no longer duplicates raw/materials path mapping rules that belong
  to utilities.
- Material status logic can be reasoned about without constructing the full page.

**Risks**

- Source list status may regress for cleaned raw files, symlinked materials, or
  stale external files.
- Moving logic may make UI updates miss a refresh point.

**Rollback**

- Keep the original page methods until the helper is proven equivalent.
- If a source-state edge case regresses, route that case back to the old method
  while preserving the rest of the extraction.

**Implementation result**

- Added `utils/source_status.py` for source kind/status constants, raw/materials
  target mapping, source display text, project source listing, selected raw source
  lookup, and external-source freshness checks.
- Updated `gui/pages/project_page.py` to call the new helper instead of duplicating
  raw/materials path and status rules in the page.
- Kept UI responsibilities in `ProjectPage`: list row rendering, buttons, dialogs,
  InfoBars, selection, and refresh timing.

**Validation**

- `python -m compileall gui utils`: passed.
- `python -m ruff check gui utils`: passed.

**Plan deviation**

- No visible source-list behavior was intentionally changed.
- GUI add/process/clean/remove flows were validated statically; a full visual/manual
  UI smoke was not run in this environment.

### Milestone 4: Compile/Output Path Uses Structured Knowledge

**Status**

Completed on 2026-05-13.

**Goal**

Connect preview/output behavior more directly to structured knowledge-base results,
without claiming full iterative compilation is complete.

**Scope**

- `gui/main_window.py`
- `core/compiler.py`
- `core/generator.py`
- Knowledge-base boundary from Milestone 1

**Key actions**

- Prefer knowledge-base-backed compilation when usable episode content exists.
- Keep a clear fallback for empty or incomplete knowledge bases.
- Make output-page preview semantics match the data source more honestly.
- Avoid implementing full conflict resolution unless that is a separate approved
  feature task.

**Acceptance criteria**

- After preview produces usable structured chunk/episode data, output generation can
  read from the knowledge-base path instead of only using placeholder state.
- Empty or partial projects still produce a clear fallback or user-visible warning.
- Existing simplified output behavior is not removed unless replaced by an equal or
  clearer fallback.

**Risks**

- The current preview may not always produce episode-level merged content, so the
  compiler path could have no input.
- Users may interpret the output as more complete than it is unless labels and
  fallback behavior remain clear.

**Rollback**

- Keep `compile_character_state()` as a fallback.
- If knowledge-base-backed output is unreliable, switch only the output selection
  back while preserving lower-level compiler helpers.

**Implementation result**

- Added `compile_character_state_from_knowledge_base()` to prefer structured
  episode-content compilation when the project has usable timeline input.
- Updated preview success handling in `gui/main_window.py` to use the
  knowledge-base-backed state when available and fall back to
  `compile_character_state()` when the knowledge base is empty or incomplete.
- Post-review fix: preview-created chunk JSON is merged into `episode_content.json`
  before the output page compiles from the knowledge base.
- Post-review fix: malformed non-object content JSON now raises a structure error,
  and preview output catches knowledge-base compilation failures before falling
  back to the placeholder compiler.
- Kept the current InfoBar and output-page flow unchanged.
- Added a missing `Any` import in `gui/pages/model_page.py` after `ruff` exposed an
  existing static error during validation.

**Validation**

- `python -m compileall core gui`: passed.
- `python -m ruff check core gui`: initially found the pre-existing missing `Any`
  import in `gui/pages/model_page.py`; passed after the import fix.
- Post-review: `python -m compileall core gui`: passed.
- Post-review: `python -m ruff check core gui`: passed.
- Post-review: temporary knowledge-base smoke in the `CharaPicker` conda
  environment passed.

**Plan deviation**

- No user-visible behavior was intentionally changed for empty or partial projects.
- Preview-created chunk JSON is now merged into episode-level content before
  output compilation. If the merge or later compilation fails, the existing
  placeholder fallback is preserved.

### Milestone 5: Secondary Maintenance Splits

**Status**

Completed on 2026-05-13 with small reversible slices.

**Goal**

Reduce long-file maintenance risk in model and FFmpeg areas after the core Extract
Once boundaries are stable.

**Scope**

- `gui/pages/model_page.py`
- `utils/ffmpeg_tool.py`
- Optional small worker/helper modules
- Related documentation if responsibilities change

**Key actions**

- Move model-page worker classes or model-test request builders into focused helper
  modules.
- Split FFmpeg detection, command construction, execution, and progress parsing
  only where it reduces real maintenance cost.
- Keep public utility function names stable where current pages depend on them.

**Acceptance criteria**

- Model page behavior is unchanged.
- FFmpeg processing behavior is unchanged.
- Large-file responsibilities become easier to locate.
- No new dependency is introduced.

**Risks**

- This has wider surface area and less immediate product payoff.
- Moving workers can disturb Qt object lifetime or signal wiring.
- FFmpeg behavior has many edge cases, especially progress and rollback.

**Rollback**

- Perform this milestone in small slices.
- Revert only the helper split that regresses behavior, not unrelated completed
  milestones.

**Implementation result**

- Added `gui/pages/model_test_helpers.py` for model-page pure helpers: token usage
  extraction/formatting, data URL construction, response language hints, and failed
  item joining.
- Updated `gui/pages/model_page.py` to import those helpers while keeping worker
  classes and UI state in place.
- Added `utils/ffmpeg_detection.py` for FFmpeg-related device/CPU detection helpers.
- Updated `utils/ffmpeg_tool.py` to import those detection helpers while keeping
  FFmpeg command construction, execution, progress parsing, and rollback logic in
  the existing module.

**Validation**

- `python -m compileall gui utils`: passed.
- `python -m ruff check gui utils`: passed.

**Plan deviation**

- This milestone intentionally avoided moving Qt worker classes or FFmpeg execution
  internals. Those would be higher-risk behavior-preserving moves and should only
  happen later when there is a concrete maintenance need or a dedicated UI/FFmpeg
  task.

## 7. Recommended order

Recommended order:

1. Milestone 1: Knowledge-Base Access Boundary
2. Milestone 2: Extractor Responsibility Split
3. Milestone 4: Compile/Output Path Uses Structured Knowledge
4. Milestone 3: Project Page Material-State Boundary
5. Milestone 5: Secondary Maintenance Splits

Milestone 1 should come first because every next core feature depends on stable
knowledge-base reads and writes. Milestone 2 should follow because full extraction
will otherwise keep expanding `core/extractor.py`. Milestone 4 becomes valuable
once the storage and extraction boundaries are clearer, because it connects the
user-visible output path to structured project data.

Milestone 3 can be done before or after Milestone 4 if source management work is
the active focus. Milestone 5 should wait until the Extract Once path is less
fragile.

Before implementing any milestone, re-check the current code and relevant
architecture documents. If documentation and code disagree, use current code as
the source of truth and call out the discrepancy.

## 8. Checklist

General rules for every milestone:

- [x] Confirm current `git status` before editing.
- [x] Re-read the files in that milestone scope.
- [x] Do not modify unrelated user changes.
- [x] Keep each implementation round limited to one milestone by default.
- [x] Preserve current public functions unless removal is explicitly approved.
- [x] Preserve current project data paths and JSON filenames.
- [x] Keep all model execution behind `utils.ai_model_middleware`.
- [x] Keep UI-visible text in `i18n/` when new text is introduced.
- [x] Avoid new dependencies unless separately approved.
- [x] Run the most relevant available validation.
- [x] Report changed files, validation, risks, and rollback notes.

Milestone checklist:

- [x] M1: Add knowledge-base access boundary.
- [x] M1: Route extractor knowledge-base writes through the boundary.
- [x] M1: Route compiler knowledge-base reads/writes through the boundary.
- [x] M1: Verify existing knowledge-base paths remain unchanged.
- [x] M2: Split source scanning from preview orchestration.
- [x] M2: Split preview chunk/material collection from model execution.
- [x] M2: Preserve preview event/progress behavior.
- [x] M4: Prefer knowledge-base-backed compile/output when structured data exists.
- [x] M4: Keep placeholder fallback for incomplete projects.
- [x] M3: Move raw/materials status calculation out of `ProjectPage`.
- [x] M3: Statically review add/process/clean/remove source flows; full UI smoke remains deferred.
- [x] M5: Split model-page helpers only when behavior can be checked.
- [x] M5: Split FFmpeg helpers only in small reversible slices.
