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
- `{project_id}/knowledge_base/source_manifest.json`：素材根目录、季、集与稳定内部 ID 的映射。
- `{project_id}/knowledge_base/seasons/{season_id}/episodes/{episode_id}/chunks/{chunk_id}.json`：当前分层知识库中的 chunk 结构化结果。
- `{project_id}/knowledge_base/seasons/{season_id}/episodes/{episode_id}/episode_content.json`：单集完整结构化内容合并结果。
- `{project_id}/knowledge_base/seasons/{season_id}/episodes/{episode_id}/episode_summary.json`：单集压缩摘要。
- `{project_id}/knowledge_base/seasons/{season_id}/season_content.json`：单季完整结构化内容合并结果。
- `{project_id}/knowledge_base/seasons/{season_id}/season_summary.json`：单季压缩摘要。
- `{project_id}/knowledge_base/seasons/{season_id}/character_stage_states.json`：季内角色阶段状态。
- `{project_id}/output/`：导出的角色卡和资料。

## 与其他目录的关系

- `utils/paths.py` 定义本目录的标准项目结构。
- `utils/state_manager.py` 保存和读取 `config.json`。
- `utils/source_importer.py` 负责外部素材导入、`raw/` 到 `materials/` 的轻量链接、raw 清理和素材移除。
- `core` 读取素材并写入 `knowledge_base/`；当前分层结构以 `core/extractor.py` 和 `core/ARCHITECTURE.md` 为准。
- `gui` 通过项目页展示和编辑项目配置。

## 维护注意事项

- 项目目录结构应由 `utils.paths.ensure_project_tree()` 统一创建。
- `raw/` 保存可重新处理的源副本；`materials/` 保存当前可被提取流程消费的素材入口。
- 清理 `raw/` 前必须确保 `materials/` 中已有可用素材，并在 `config.json` 中记录已清理路径。
- 用户素材、缓存、知识库和输出结果默认不应进入版本控制。
- 写入 JSON 时保持 UTF-8 和结构化格式。
- 后续新增项目子目录时，同步更新本说明和路径工具。
- 修改知识库结构时，同步核对 `docs/extraction-workflow.zh_CN.md` 和 `docs/extraction-development-roadmap.zh_CN.md`，避免把 roadmap 当成已实现事实。
