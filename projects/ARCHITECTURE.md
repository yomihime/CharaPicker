# projects 架构说明

## 负责什么

- 保存本地用户工程数据。
- 按 `project_id` 隔离项目配置、原始素材、可处理素材、缓存、知识库和输出结果。
- 作为 Extract Once 流程的落盘位置。

## 不负责什么

- 不保存源码模块。
- 不保存应用依赖或外部二进制工具。
- 不保存本地大模型文件。
- 不把用户项目数据默认提交到 Git。

## 关键文件和目录

- `.gitkeep`：保留空目录。
- `{project_id}/config.json`：项目配置，包含目标角色、提取模式、素材路径、素材处理配置和已清理 raw 标记等。
- `{project_id}/raw/`：导入后的原始素材副本，用于后续重新处理。
- `{project_id}/materials/`：当前处理管线实际读取的素材。使用原素材方案时通常指向 `raw/` 中的同名素材。
- `{project_id}/cache/`：切片、预览和临时处理文件。
- `{project_id}/knowledge_base/facts.json`：早期/兼容用客观事实记录。
- `{project_id}/knowledge_base/targeted_insights.json`：早期/兼容用定向洞察记录。
- `{project_id}/knowledge_base/extraction_runs/{run_id}/plan.json`：正式提取 run plan，记录本次运行的素材引用、unit、媒体类型和派生成果索引入口。
- `{project_id}/knowledge_base/source_manifest.json`：旧结构兼容/调试用的素材根目录、季、集与稳定内部 ID 映射；正式提取初始化以 run plan 为主。
- `{project_id}/knowledge_base/seasons/{season_id}/episodes/{episode_id}/chunks/{chunk_id}.json`：当前分层知识库中的 chunk 结构化结果。
- `{project_id}/knowledge_base/seasons/{season_id}/episodes/{episode_id}/episode_transcript.json`：单集音频转写结果，保存可追溯对白/旁白文本、时间段、来源素材指纹和转写后端信息；run plan 以 text 型 `DerivedArtifact` 和 `transcript_text` 派生 unit 引用它，原始 audio/video 仍保留为 source refs。
- `{project_id}/knowledge_base/seasons/{season_id}/episodes/{episode_id}/episode_content.json`：单集完整结构化内容合并结果。
- `{project_id}/knowledge_base/seasons/{season_id}/episodes/{episode_id}/episode_summary.json`：单集压缩摘要。
- `{project_id}/knowledge_base/seasons/{season_id}/season_content.json`：单季完整结构化内容合并结果。
- `{project_id}/knowledge_base/seasons/{season_id}/season_summary.json`：单季压缩摘要。
- `{project_id}/knowledge_base/seasons/{season_id}/character_stage_states.json`：季内角色阶段状态。
- `{project_id}/knowledge_base/character_cards/{card_id}/card.json`：正式 CharaPicker 角色卡母本。
- `{project_id}/knowledge_base/character_cards/{card_id}/card.json` 中的 `source_context.source_runs` 与 `extensions["charapicker"]`：前者记录角色卡实际消费的 extraction run；后者保存 `compile_evidence_layers`、每条证据的来源 metadata、`alias_resolution`、`needs_review_reasons`、`conflict_groups`、`evidence_source_profile` 和 `parse_diagnostics`。这些字段用于解释证据来源、分层、别名校验、冲突复核和 AI JSON 修复情况，不替代顶层角色卡事实字段。
- `{project_id}/knowledge_base/character_cards/{card_id}/cover.png`：角色卡裁剪后的 9:16 封面。
- `{project_id}/knowledge_base/preview_character_cards/preview_card/card.json`：隔离的角色卡预览草稿，不进入正式海报墙扫描。
- `{project_id}/output/character_cards/`：角色卡派生导出结果，包括 Markdown、HTML、CharaPicker JSON、Character Card V2 JSON 和 AstrBot 手动复制清单。

## 与其他目录的关系

- `utils/paths.py` 定义本目录的标准项目结构。
- `utils/state_manager.py` 保存和读取 `config.json`。
- `utils/source_importer.py` 负责外部素材导入、`raw/` 到 `materials/` 的轻量链接、raw 清理和素材移除。
- `core` 读取素材并写入 `knowledge_base/`；当前分层结构以 `core/extractor.py` 和 `core/ARCHITECTURE.md` 为准。
- `gui` 通过项目页展示和编辑项目配置，通过角色卡页管理项目内角色卡。

## 维护注意事项

- 项目目录结构应由 `utils.paths.ensure_project_tree()` 统一创建。
- `raw/` 保存可重新处理的源副本；`materials/` 保存当前可被提取流程消费的素材入口。
- 清理 `raw/` 前必须确保 `materials/` 中已有可用素材，并在 `config.json` 中记录已清理路径。
- 用户素材、缓存、知识库和输出结果默认不应进入版本控制。
- 写入 JSON 时保持 UTF-8 和结构化格式。
- 正式角色卡、预览草稿和导出产物路径必须隔离：正式卡只在 `knowledge_base/character_cards/`，预览草稿只在 `knowledge_base/preview_character_cards/`，导出只在 `output/character_cards/`。
- `quality.warnings` 只保存用户可读 warning；结构化复核原因保留在 `extensions["charapicker"]["quality_checks"]["needs_review_reasons"]`。
- 后续新增项目子目录时，同步更新本说明和路径工具。
- 修改知识库结构时，同步核对 `docs/reference/extraction-workflow.zh_CN.md` 和 `docs/plans/extraction-development-roadmap.zh_CN.md`，避免把 roadmap 当成已实现事实。
