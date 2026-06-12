# core 架构说明

## 负责什么

- 承载核心业务模型和处理流程。
- 定义项目配置、洞察事件、角色状态和项目路径等结构化数据。
- 产出提取阶段的知识库 JSON、洞察事件、进度和 token 用量。
- 承载角色状态编译、季/集聚合、角色卡母本、导入导出映射和输出渲染的核心接口。

## 不负责什么

- 不负责创建 Qt 页面、控件布局或导航。
- 不负责保存用户偏好和界面状态。
- 不直接读取或写入 i18n 文案文件。
- 不直接管理运行时颜色、图标或图片资源。

## 关键文件

- `models.py`：定义 `ProjectConfig`、`SourceProcessingConfig`、`InsightEvent`、`CharacterState`、`ChunkExtractionResult`、`EpisodeTranscript`、`ExtractionRunPlan`、`ProjectPaths` 等 Pydantic 模型。
- `extraction_plan.py`：定义新正式提取 run plan 词汇与 Pydantic 模型，包括 `MediaType`、`ContentForm`、`MaterialRef`、`ExtractionUnit`、`EpisodePlan`、`FormalExtractionRunPlan`、`DerivedArtifact`、`EvidenceRef` 和 `SourceTrace`；不依赖 GUI，也不复用旧 `ExtractionRunPlan` 语义。
- `character_card_constants.py`：集中保存角色卡固定文件名、预览卡保留 ID 和 stale warning reason 等跨模块共享常量。
- `knowledge_base.py`：集中管理 `projects/{project_id}/knowledge_base/` 下常用产物的路径、JSON 读写和结构校验。
- `source_scanner.py`：提供素材目录扫描、正式素材到 run plan unit 的扫描、预览视频 chunk 收集和预览 chunk 标识生成。
- `extractor.py`：定义 `Extractor`，作为 UI-facing 提取入口，负责知识库分层初始化、预览提取、完整/洁净/快速正式提取、chunk/episode/season 内容合并、episode transcript 入口，并委托知识库读写与素材扫描 helper。
- `transcript_provider.py`：把 transcript 表达为 run plan 中的 text 型 `DerivedArtifact`，收集每集可转写素材并调用既有音频转写实现；不把 transcript 作为新的 `MediaType`。
- `video_unit_handler.py`：封装正式视频 unit 的时长探测、按时长缩放输出 token 和 `ModelCallRequest` 构造；模型调用仍由 `utils.ai_model_middleware` 执行。
- `compiler.py`：定义 `build_character_compile_request()`、`compile_character_state()`、`compile_character_state_by_season_episode()`、`write_character_stage_states()` 和 `final_polish_character_state()`，负责从知识库聚合角色阶段状态。
- `character_card_store.py`：管理 `knowledge_base/character_cards/` 与 `preview_character_cards/` 下角色卡的创建、读取、保存、列表、删除和封面路径登记。
- `character_card_compiler.py`：从正式或预览知识库生成 CharaPicker 角色卡 JSON；正式编译会构建 direct、mention、causal 和 season_context 分层证据包，处理 AI 别名校验、AI 复核、冲突分组、`needs_review_reasons` 和 JSON parse diagnostics；不读取原始素材，也不读取 `ProjectConfig.target_characters`。
- `character_card_renderers.py`：从 CharaPicker JSON 生成 Markdown、HTML 和人类友好 JSON 分组；HTML 渲染负责转义用户文本且不依赖外部资源。
- `character_card_formats.py`：把 CharaPicker JSON 映射到 Character Card V2 JSON 和 AstrBot 手动复制内容，无法映射的信息返回 warnings 或进入扩展字段。
- `character_card_exporter.py`：把角色卡派生产物写入 `projects/{project_id}/output/character_cards/`。
- `character_card_importer.py`：导入 CharaPicker JSON，校验格式并生成当前项目内的新 `card_id`。
- `generator.py`：保留旧 `render_profile_markdown()` 兼容函数；主角色卡页面不再依赖它作为最终角色卡渲染入口。
- `__init__.py`：标记 `core` 为 Python 包。

## 与其他目录的关系

- 从 `utils.i18n` 读取本地化文案，用于提取流程、编译流程、摘要和洞察描述。
- 通过 `utils.ai_model_middleware` 构造和执行模型请求；不直接访问具体模型后端。
- 模型 prompt 正文不得硬编码在 `core` 业务代码中；新增或修改 prompt 时应维护 `res/default_prompts.json`，并通过 `utils.ai_model_middleware` 按 purpose 与变量渲染。
- 向 `gui` 通过 Qt Signal 传递可序列化的洞察事件 `dict`。
- 向 `gui` 通过回调传递预览进度和 token 用量。
- 被 `utils.state_manager` 引用，用于项目配置的序列化和反序列化。
- 被 `utils.paths` 引用，用于描述包含 `raw/`、`materials/`、`cache/`、`knowledge_base/` 和 `output/` 的项目路径。
- 向 `projects/{project_id}/knowledge_base/` 写入 `extraction_runs/{run_id}/plan.json`、兼容用 `source_manifest.json`、`seasons/*/episodes/*/chunks/*.json`、`episode_content.json`、`episode_summary.json`、`episode_transcript.json`、`season_content.json`、阶段性角色状态和 `character_cards/{card_id}/card.json`；正式提取产物带 `extraction_run_id`，聚合时只消费当前 run 的合格产物。
- 正式角色卡的 CharaPicker 扩展字段使用 `extensions["charapicker"]` 保存编译证据和质量评估，包括 `compile_evidence_layers`、`alias_resolution`、`needs_review_reasons`、`conflict_groups` 和 `parse_diagnostics`；这些字段属于 core 生成的结构化诊断，不应由 GUI 拼装。
- 向 `projects/{project_id}/output/character_cards/` 写入 Markdown、HTML、CharaPicker JSON、Character Card V2 JSON 和 AstrBot 手动复制清单。

## 维护注意事项

- 新增业务数据结构时优先放在 `models.py`，保持 Type Hints。
- 素材处理配置只描述用户选择和项目状态；文件复制、链接、清理等副作用放在 `utils/source_importer.py`。
- `extractor` 只做素材解析、事实提取和洞察产出。
- 完整提取和洁净提取保持线性上下文流程；快速提取允许 chunk 并发且不带上下文，随后用 AI 并发重整理集和季。
- `compiler` 只做角色状态迭代、长文本阅读和冲突处理；角色卡证据分层和质量规则由 `character_card_compiler` 负责。
- 角色卡编译、存储、渲染、导入和导出分别放在 `character_card_*` 模块；页面层不直接拼接知识库路径或导出字段。
- 角色卡固定协议值优先放在 `character_card_constants.py`，避免在 store、compiler、renderer 和 GUI 层重复硬编码。
- `generator` 只保留旧输出兼容，不新增角色卡业务逻辑。
- 不要在 `core` 中引入界面布局逻辑。
- 写入知识库时保持 UTF-8 和结构化 JSON，路径结构要与 `projects/ARCHITECTURE.md` 保持一致。
- 允许 `core` 装配模型请求中的业务变量、metadata 和多模态素材 part；不允许复制或拼接大段 prompt 指令文本。
