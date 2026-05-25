# Extraction Workflow Technical Overview (en_US)

This document is for users, researchers, and anyone who wants to understand the design of CharaPicker. It explains how long-form video material is extracted, compressed, organized, and eventually used to generate character cards.

## 1. Design Goals

CharaPicker follows the `Extract Once` principle: raw video, subtitle, or image material should be analyzed once, then preserved as reusable structured knowledge.

The workflow solves three problems:

- Long anime series or video collections are too large to send to a model in one pass.
- Character growth depends on chronology, so isolated clip summaries are not enough.
- Later character card generation should read structured results instead of re-analyzing the original video.

The system therefore organizes material into three levels: season, episode, and chunk.

- `chunk` is the extraction unit used to control model context length.
- `episode` is the smallest natural unit for plot understanding and character growth.
- `season` is the unit for stage-level growth, relationship changes, and long-running conflicts.

## 2. Input Material Convention

The first stage uses a simple and explainable directory recognition rule:

- The user selects a source root folder.
- Each first-level folder under the root represents one season.
- Video files inside a season folder represent episodes in that season.
- Season folders and episode files are sorted by name by default.

Recommended naming:

- Season folders: `01 To LOVEる`, `02 Motto To LOVEる`, `03 Darkness`
- Episode files: `01 xxx.mp4`, `02 xxx.mp4`, `10 xxx.mp4`
- Names like `xxx S01` and `xxx S02` can also work, as long as text sorting matches the real order.

Zero-padded numbering such as `01`, `02`, and `10` is recommended. This keeps simple text sorting reliable.

After import, the system generates `source_manifest.json`, which records the mapping from original folders and filenames to internal identifiers. Later steps use stable identifiers such as `season_001`, `episode_001`, and `chunk_0001`, instead of repeatedly inferring meaning from filenames.

## 3. Overall Flow

Recommended flow:

```text
raw material
-> detect seasons from folders
-> detect episodes by filename order
-> split each episode into chunks
-> extract structured results from each chunk
-> merge into episode-level full content
-> generate episode-level compressed summary
-> merge into season-level full content
-> generate season-level compressed summary
-> compile character state step by step by season and episode
-> generate final character card
```

One important design decision: character card generation does not start from chunks.

Chunks exist so the model can process long material. To simulate character growth, the compiler should start from full episode content and move episode by episode. Episodes match plot structure better than chunks and are a more natural unit for observing character change.

## 4. Extraction Context

When extracting the current chunk, context is organized with this priority:

1. Current chunk content.
2. Full structured extraction results from completed chunks in the current episode.
3. Episode-level summaries from completed episodes in the current season.
4. Season-level summary from the previous season.

The current chunk is always the highest-priority evidence.

Episodes are usually not too long, so completed chunks in the same episode can be included as full structured results instead of short summaries. Here, “full” means full structured extraction results, not original subtitle text or raw transcript. This preserves detail without repeatedly spending context on already processed source text.

If an episode is unusually long, the system can keep full structured results for the most recent chunks and merge older chunks into a rolling episode summary.

## 5. Cross-Episode And Cross-Season Context

Within one season, later episodes include compressed summaries from earlier completed episodes. This helps the model preserve continuity in relationships, conflicts, and character states.

Across seasons, the previous season summary can be included, but only as low-priority background. It explains a character’s state, relationships, and unresolved conflicts before entering the current season. It must not override new facts found in current-season material.

The previous season summary should be labeled semantically as:

```text
PREVIOUS_SEASON_BACKGROUND
```

In other words, previous-season information is background, not current evidence.

## 6. Knowledge Base Structure

Extraction results are written to the project `knowledge_base` and stored by season, episode, and chunk.

Recommended structure:

```text
knowledge_base/
├── source_manifest.json
├── seasons/
│   ├── season_001/
│   │   ├── season_content.json
│   │   ├── season_summary.json
│   │   ├── character_stage_states.json
│   │   └── episodes/
│   │       ├── episode_001/
│   │       │   ├── episode_content.json
│   │       │   ├── episode_summary.json
│   │       │   └── chunks/
│   │       │       ├── chunk_0001.json
│   │       │       └── chunk_0002.json
│   │       └── episode_002/
│   │           ├── episode_content.json
│   │           ├── episode_summary.json
│   │           └── chunks/
│   │               └── chunk_0001.json
│   └── season_002/
│       ├── season_content.json
│       ├── season_summary.json
│       ├── character_stage_states.json
│       └── episodes/
└── character_cards/
    └── {character_id}.json
```

This structure makes it possible to:

- Trace each character insight back to a season, episode, and chunk.
- Resume from completed chunks, episodes, or seasons after interruption.
- Read episode-level content in chronological order during character card generation.
- Show clear evidence sources in the UI later.

## 7. Character Card Generation

Character card generation uses step-by-step compilation:

```text
previous season character state (optional)
-> current season episode 1 full content
-> update character state
-> current season episode 2 full content
-> update character state
-> ...
-> finish current season and generate stage summary
-> continue with next season
-> final polish
-> output character card
```

This better represents a character growth path. The character is not treated as a static profile; personality, relationships, conflicts, and changes are accumulated over time.

If information conflicts over time, the system should preserve it as dynamic change, such as disguise, misunderstanding, corruption, growth, or relationship shift, rather than simply overwriting old information.

## 8. Current Limitations

The first stage does not perform complex episode recognition or online matching against anime databases.

Users need to provide reasonably named folders and files. The system first uses simple sorting to determine season and episode order. Manual order adjustment can be added to the UI later.

This design intentionally stays transparent: users can understand why the system sorted material a certain way, and the implementation remains easier to resume and audit.
