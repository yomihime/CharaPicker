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

- `models.py`：定义 `ProjectConfig`、`SourceProcessingConfig`、`InsightEvent`、`CharacterState`、`ChunkExtractionResult`、`EpisodeTranscript`、`ProjectPaths` 等 Pydantic 模型。
- `extraction_plan.py`：定义新正式提取 run plan 词汇与 Pydantic 模型，包括 `MediaType`、`ContentForm`、`MaterialRef`、`ExtractionUnit`、`EpisodePlan`、`FormalExtractionRunPlan`、`DerivedArtifact`、`EvidenceRef` 和 `SourceTrace`；不依赖 GUI，也不复用旧 `ExtractionRunPlan` 语义。
- `character_card_constants.py`：集中保存角色卡固定文件名、预览卡保留 ID 和 stale warning reason 等跨模块共享常量。
- `knowledge_base.py`：集中管理 `projects/{project_id}/knowledge_base/` 下常用产物的路径、JSON 读写和结构校验。
- `source_scanner.py`：保留旧视频目录扫描、正式扫描入口、预览视频 chunk 收集和预览 chunk 标识生成，并把非视频 unit 扩展委托给 `material_unit_scanner.py`。
- `material_unit_scanner.py`：把文本、字幕、音频、图片和 GIF 映射为正式 run plan unit，负责唯一字幕关联、漫画/图集页组自然排序、稳定 ID、页码/章节 metadata 和不支持状态；不执行解析或模型提取。
- `preview_sampling.py`：从 `FormalExtractionRunPlan` 构建通用预览候选，按字幕/现成 transcript、普通文本、图片、需转写音频、视频的成本顺序稳定排序；负责生成单 unit 的隔离执行计划，不执行模型调用或知识库写入。
- `formal_dispatch.py`：从 `FormalExtractionRunPlan` 构建正式提取分发表，首批覆盖 `video`、`text`、`image` 和 `audio -> transcript`，并把 VTT/LRC、BMP/GIF、模型不支持图片等情况整理为可解释 unsupported unit；不执行模型调用或聚合。
- `timed_text_parser.py`：使用标准库解析首批支持的 `.srt` 和 `.ass`，保留开始/结束时间、源行号、原始文本和 ASS 显式 speaker；不推断未知说话人，不把字幕当成 transcript 派生成果。
- `text_unit_handler.py`：负责普通 `.txt`、`.md`、受控 `.json`、首批 `.srt` / `.ass` 以及派生 `episode_transcript.json` 文本 unit 的解码、结构校验、预算分块、文本/时间范围 evidence、文本模型请求和 `ChunkExtractionResult` 构建；字幕与 transcript evidence 保留 segment 定位，speaker 只接受素材中的显式字段。
- `image_unit_handler.py`：负责 `.png`、`.jpg` / `.jpeg`、`.webp` 静态图片的文件上限与签名校验、图片模型请求、每张图片内部输出预算、页码/可选区域 evidence 和 `ChunkExtractionResult` 构建；不接管 BMP/GIF，也不复用视频每分钟输出口径。
- `extractor.py`：定义 `Extractor`，作为 UI-facing 提取入口，负责知识库分层初始化、通用 unit 采样预览、完整/洁净/快速正式提取、chunk/episode/season 内容合并、episode transcript 入口，并委托知识库读写与素材扫描 helper；预览逐个执行低成本候选，正式提取先经 `formal_dispatch.py` 选中 handler，单个失败或 unsupported unit 会进入 warning 而不阻断其它可提取素材。
- `transcript_provider.py`：把 transcript 表达为 run plan 中的 text 型 `DerivedArtifact`，收集每集 video/audio 可转写素材并调用既有音频转写实现；READY artifact 会物化为短稳定 ID 的 `transcript_text` 派生 unit，引用知识库内 `episode_transcript.json`，不把 transcript 作为新的 `MediaType`。
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
- 向 `projects/{project_id}/knowledge_base/` 写入 `extraction_runs/{run_id}/plan.json`、调试/旧观察索引用 `source_manifest.json`、`seasons/*/episodes/*/chunks/*.json`、`episode_content.json`、`episode_summary.json`、`episode_transcript.json`、`season_content.json`、阶段性角色状态和 `character_cards/{card_id}/card.json`；正式提取产物带 `extraction_run_id`，聚合时只消费当前 run 的合格产物。
- 正式角色卡的 CharaPicker 扩展字段使用 `extensions["charapicker"]` 保存编译证据和质量评估，包括 `compile_evidence_layers`、`alias_resolution`、`needs_review_reasons`、`conflict_groups` 和 `parse_diagnostics`；这些字段属于 core 生成的结构化诊断，不应由 GUI 拼装。
- 向 `projects/{project_id}/output/character_cards/` 写入 Markdown、HTML、CharaPicker JSON、Character Card V2 JSON 和 AstrBot 手动复制清单。

## 维护注意事项

- 新增业务数据结构时优先放在 `models.py`，保持 Type Hints。
- 素材处理配置只描述用户选择和项目状态；文件复制、链接、清理等副作用放在 `utils/source_importer.py`。
- `extractor` 只做素材解析、事实提取和洞察产出。
- 完整提取和洁净提取保持线性上下文流程；快速提取允许 chunk 并发且不带上下文，随后用 AI 并发重整理集和季。
- 快速提取当前只对视频 chunk 启用并发；文本、图片和 audio transcript 仍通过正式串行 handler 写入 chunk，并按 `source_trace` 重建 episode/season，运行时会发出 warning 说明回退。
- 文本 unit 使用独立输入字符预算和固定内部输出 token 上限，不复用视频“每分钟输出 token”语义；文本 chunk 必须保留原文 offset、素材引用和结构化 evidence。
- `.srt` / `.ass` 通过普通 `text` handler 进入预览与正式提取；`.vtt` / `.lrc` 当前只允许导入和扫描，必须保留 unsupported warning，不能静默当普通文档处理。
- 音频素材通过 `audio -> DerivedArtifactKind.TRANSCRIPT -> transcript_text` 进入文本提取；转写失败只标记对应 artifact 并发出 warning，不得阻断同次运行中不依赖 transcript 的文本、图片或视频流程。
- 预览最多生成 2 个 chunk，并优先选择低成本 unit；每个候选首轮只取 1 个 chunk，以避免单个长文本占满全部预览名额。候选失败后允许继续尝试后续素材，但总尝试数限制为 4；不支持的 unit 必须携带媒体类型、内容形态、unit 和素材引用进入 warning 事件。
- 预览可生成或复用 `episode_transcript.json` 这类派生中间体，但不得写入正式 chunk、正式 episode 内容或 `extraction_runs/{run_id}/plan.json`；正式角色卡编译不得消费 `preview__` 产物。
- 正式提取入口只调用 `formal_dispatch.py` 选中的 handler；模型能力不足的图片、暂未支持的时间文本格式和暂无正式 handler 的 unit 只发出 warning，不再让下游 handler 自行碰运气。视频仍使用旧视频 chunk 输入和既有 `_extract_full_video_units()` / `_extract_fast_video_units()` 路径。
- PNG/JPEG/WEBP 静态图片通过 `image` handler 进入预览与正式提取；漫画/图集目录会按文件夹生成独立 image episode，不跨文件夹自动合并，并在 metadata 中记录章节、页序、页数和 `manga` 候选语义。图片证据至少保留项目内相对路径，并按可用信息附带页码、像素尺寸和 region。BMP/GIF 当前只允许导入和扫描，必须保留 unsupported warning。
- 图片输出预算当前使用 handler 内部“每张”默认值并记录 `output_budget_basis=per_image`；在独立用户设置接线前，不得复用视频 `max_output_tokens` 的每分钟语义。
- `source_kind` 是旧兼容摘要字段；聚合产物必须优先根据 `source_trace` 中的 `media_types` 推导单一来源或 `mixed`，不得把文本、图片或音频产物硬编码为 `video`。
- `compiler` 只做角色状态迭代、长文本阅读和冲突处理；角色卡证据分层和质量规则由 `character_card_compiler` 负责。
- 角色卡编译、存储、渲染、导入和导出分别放在 `character_card_*` 模块；页面层不直接拼接知识库路径或导出字段。
- 角色卡固定协议值优先放在 `character_card_constants.py`，避免在 store、compiler、renderer 和 GUI 层重复硬编码。
- `generator` 只保留旧输出兼容，不新增角色卡业务逻辑。
- 不要在 `core` 中引入界面布局逻辑。
- 写入知识库时保持 UTF-8 和结构化 JSON，路径结构要与 `projects/ARCHITECTURE.md` 保持一致。
- 允许 `core` 装配模型请求中的业务变量、metadata 和多模态素材 part；不允许复制或拼接大段 prompt 指令文本。
