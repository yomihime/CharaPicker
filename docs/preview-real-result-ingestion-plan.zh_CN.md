# 真实预览结果后续计划（zh_CN）

最近核对日期：2026-05-15。

本文只保留真实预览链路仍未完成的后续计划。视频 chunk 预览、`preview__` 产物隔离和正式视频提取 MVP 的详细完成记录已归档到 [真实预览结果接入计划完成记录](archive/preview-real-result-ingestion-plan.completed.zh_CN.md) 与 [正式视频提取架构指南与任务计划](archive/formal-video-extraction-architecture-plan.zh_CN.md)。

当前事实：

- 预览会从 `projects/{project_id}/materials/` 收集最多 2 个视频 chunk，并通过云端视频模型生成结构化结果。
- 预览产物写入 `preview__*.json` 和 `preview__episode_content.json`，并带 `extraction_stage = "preview"`。
- 正式提取产物使用 `extraction_stage = "full"`；正式聚合和正式编译不消费 preview 或 legacy 产物。
- 文本、字幕、音频转写、图片、漫画和完整角色状态迭代编译仍未完整接入。

## 1. 后续里程碑

### M1：文本、字幕与音频转写接入

目标：

- 从 `materials/` 稳定读取 `.txt`、`.md`、`.json` 等文本入口。
- 明确字幕文件和音频转写结果的标准落点。
- 复用或扩展 `utils/chunker.py`，把文本类素材切成最多 2 个预览 chunk。
- 让文本预览和视频预览共享 `ChunkExtractionResult` 与知识库写入规则。

验收标准：

- 没有视频 chunk 但存在可读文本素材时，预览能从文本素材生成真实 chunk JSON。
- 文本 chunk 的上下文、证据和来源路径可追溯。
- UI 无真实素材反馈能区分“未处理素材”“无可读视频”“无可读文本”等原因。

### M2：图片、漫画与混合媒体接入

目标：

- 明确图片/漫画素材在 `materials/` 下的可消费结构。
- 决定单图、图片序列、漫画页组如何映射到 season/episode/chunk。
- 保持模型请求仍通过 `utils.ai_model_middleware`。
- 不让页面层直接读取或解析素材文件。

验收标准：

- 图片/漫画预览能生成与视频/text 一致结构的 `ChunkExtractionResult`。
- 证据引用能定位到页、帧、文件或片段。
- 失败反馈能说明是素材不可读、模型不支持还是输出结构不合法。

### M3：角色状态迭代编译与冲突消解

目标：

- 基于正式 `episode_content.json` 按季、集逐步更新角色状态。
- 写入 `character_stage_states.json`。
- 加入冲突识别、证据优先级和最终整理策略。
- 让角色卡生成优先读取结构化知识库，而不是重新分析原始素材。

验收标准：

- 单个角色能得到按集推进的阶段状态。
- 冲突事实不会被静默覆盖，必须保留证据来源或处理说明。
- 输出页能明确区分占位预览、知识库简化预览和完整编译结果。

## 2. 模块边界

- `core.extractor`：负责任务编排、模型请求构造、洞察事件、chunk 保存和预览 episode 合并。
- `core.source_scanner`：负责素材扫描、预览 chunk 收集和 chunk 标识生成。
- `core.knowledge_base`：负责知识库路径、JSON 读写、preview/full 产物隔离和结构初始化。
- `core.compiler`：负责从结构化知识库聚合角色状态；后续完整迭代编译应继续放在这里或其窄 helper 中。
- `utils.source_importer` 与 `utils.material_processing_middleware`：负责素材导入和处理，不承载 AI 推理。
- `utils.chunker`：后续文本类 chunk 构造优先复用或最小扩展这里。
- `gui`：只负责触发预览、展示进度、确认高风险设置和接收洞察事件，不直接读取素材文件。

## 3. 通用约束

- 不绕过 `utils.ai_model_middleware` 直接调用模型。
- 不新增依赖，除非用户另行同意并同步说明影响范围。
- 不改变 `projects/{project_id}/knowledge_base/` 现有文件名和目录层级，除非另有迁移计划。
- 长耗时任务继续放在 Qt worker/thread 中执行。
- 用户可见文案必须同步维护四个 i18n JSON。
- 预览最多处理前 2 个 chunk，不扫描或写入超出预览范围的素材内容。
- 无可用真实素材时，UI 必须明确提示原因，不回退到项目元数据伪装真实预览。
