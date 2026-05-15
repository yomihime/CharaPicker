# 真实预览结果接入计划（zh_CN）

归档状态：本文档保留真实视频预览接入、`preview__` 产物隔离和早期预览计划的详细完成记录。当前仍需执行的文本、字幕、音频、图片、漫画和角色编译相关任务，以主目录 `docs/preview-real-result-ingestion-plan.zh_CN.md` 为准。

本文记录“开始预览”从占位元数据改为读取真实素材结果的实施状态和后续里程碑。它是阶段性计划，不是当前功能的完整实现证明；执行前必须重新核对当前代码。

最近核对日期：2026-05-15。

当前状态：视频 chunk 预览主链路已接入，并已改为写入 `preview__` 预览专用产物；正式视频提取 MVP 已完成并归档；文本、字幕、音频转写、图片/漫画等素材类型仍未完整接入。

## 1. 当前代码事实

已核对的主要入口：

- `gui/main_window.py`：`PreviewWorker` 在线程中调用 `Extractor.run_preview_streaming()`；低输出 Token / 分钟会在开始前弹窗确认；预览成功后优先调用预览专用知识库编译入口，失败或无结构化状态时回退到占位编译。
- `core/extractor.py`：预览会从 `materials/` 收集最多 2 个视频 chunk，调用云端视频模型，解析结构化 JSON，保存带 `preview__` 前缀和 `extraction_stage = "preview"` 的 `ChunkExtractionResult`，并把成功 chunk 合并成 `preview__episode_content.json`。
- `core/source_scanner.py`：负责扫描素材目录、收集预览视频 chunk，并为预览 chunk 生成 `season_id`、`episode_id`、`chunk_id`。
- `core/knowledge_base.py`：负责知识库路径和 JSON 读写，包括 chunk、episode、season 和角色阶段状态产物。
- `core/compiler.py`：可分别从正式 `episode_content.json` 或预览 `preview__episode_content.json` 聚合简化角色状态，但完整迭代编译与冲突消解还没有完成。

当前预览行为：

- 预览读取 `projects/{project_id}/materials/` 中可消费的视频文件，而不是项目元数据占位内容。
- 预览最多处理前 2 个视频 chunk。
- 预览不会把用户填写的目标角色列表传入 chunk 提取请求；chunk JSON 的 `targets` 为空，以便保留素材中出现的全部有效角色信息。
- 每次预览都会重新从 `materials/` 发起视频提取，不把既有 chunk JSON 作为本轮预览输入。
- 模型输出因 `finish_reason=length` 或 `max_tokens` 截断而无法解析结构化 JSON 时，会在洞察流提示该 chunk 被跳过，并继续处理其他 chunk。
- 成功生成的 chunk 会写入 `knowledge_base/seasons/.../episodes/.../chunks/preview__*.json`。
- 预览 JSON 会写入 `extraction_stage = "preview"` 和 `run_type = "preview_trial"`，并记录相对 `materials/` 的 `source_path`。
- 预览成功后会合并对应 `preview__episode_content.json`；当前预览链路不会自动生成 `episode_summary.json`、`season_summary.json` 或预览 summary。
- 预览链路不会覆盖正式 `chunk_*.json` 或正式 `episode_content.json`。

## 2. 原实现步骤执行情况

| 原步骤 | 当前状态 | 说明 |
| --- | --- | --- |
| 1. 从 `materials/` 读取 `.txt`、`.md`、`.json` 文本素材 | 未执行 / 已推迟 | 当前真实预览优先走视频 chunk；文本素材读取仍可作为后续里程碑补齐。 |
| 2. 把文本素材合并并切成最多 2 个预览 chunk | 未执行 / 已推迟 | `utils/chunker.py` 有基础文本分块函数，但当前预览没有接入文本分块链路。 |
| 3. 在 `run_preview_streaming()` 中用真实 chunk 替换占位 chunk | 已完成（视频路径） | 已通过 `core/source_scanner.py` 从 `materials/` 收集视频 chunk，并在 `run_preview_streaming()` 中执行真实模型请求。 |
| 4. 无真实素材时给用户可见反馈 | 已完成（视频路径） | 无可用预览结果时会发出警告并中止，文案不再暗示缺少正式 chunk JSON。 |
| 5. 将真实洞察保存为 `ChunkExtractionResult` | 已完成（视频路径） | 每个成功的视频 chunk 会保存为结构化预览 chunk JSON，文件名带 `preview__`，且 `targets` 默认为空。 |
| 6. 预览完成后合并 `episode_content.json` 和 `episode_summary.json` | 已调整为预览专用产物 | 预览成功后合并 `preview__episode_content.json`；不生成正式 `episode_content.json`，也不自动生成 summary。 |
| 7. 接入视频字幕、音频转写、图片/漫画多模态解析 | 未执行 | 当前只有视频 chunk 直连云端视频模型；字幕、音频、图片/漫画仍待设计和接入。 |

## 3. 后续里程碑

### M1：视频 chunk 真实预览链路

状态：已完成。

已落地内容：

- 从 `materials/` 稳定收集最多 2 个视频 chunk。
- 使用云端视频模型提取结构化 JSON。
- 按视频时长换算单次请求的 `max_tokens`。
- 输出 Token / 分钟过低时，在开始前弹窗确认。
- 保存目标无关的 `ChunkExtractionResult`。
- 写入 `preview__` chunk 产物，并标记 `extraction_stage = "preview"`。
- 模型输出被长度上限截断时，跳过当前 chunk 并通过洞察流提示。
- 预览成功后把 chunk 合并进 `preview__episode_content.json`。

仍需注意：

- 预览会重新分析 `materials/`，不会复用旧 chunk JSON。
- 这是当前预览阶段的预期行为，不等于正式 Extract Once 复用策略已经定案。

### M2：预览产物与知识库摘要补齐

状态：已完成预览隔离；预览 summary 仍未生成。

目标：

- 保持 chunk 到 `preview__episode_content.json` 的稳定合并。
- 决定预览阶段是否需要自动生成 `episode_summary.json`。
- 如果生成摘要，明确它是预览摘要、正式摘要，还是带标记的临时摘要。
- 明确 `season_content.json` 和 `season_summary.json` 是否应由预览触发，默认不应让预览扩大写入范围。

验收标准：

- 预览成功后，输出页能稳定从 `preview__episode_content.json` 生成简化预览。
- 预览链路不会默默写入超出前 2 个 chunk 范围的内容。
- 如果生成 `episode_summary.json`，文档和代码都明确它与正式提取产物的关系。

### M3：正式提取与预览产物隔离策略

状态：部分完成。

目标：

- 明确 full extraction 是否复用预览生成的 chunk/episode 内容。
- 如果不复用，正式提取应显式忽略或覆盖预览产物。
- 如果复用，应增加可追溯标记，区分预览试算、正式提取和可能的重跑结果。
- 避免预览试算污染正式知识库事实。

当前进展：

- 已落地预览产物隔离；正式提取入口和正式聚合过滤仍按正式提取主计划后续步进推进。

验收标准：

- 知识库产物能看出来源阶段，例如 preview/full/retry，或有等价机制。
- 正式提取重跑时不会因为旧预览结果产生不可见的混合状态。
- 用户能理解当前结果来自预览还是正式提取。

### M4：文本、字幕与音频转写接入

状态：未开始。

目标：

- 从 `materials/` 稳定读取 `.txt`、`.md`、`.json` 等文本入口。
- 明确字幕文件和音频转写结果的标准落点。
- 复用或扩展 `utils/chunker.py`，把文本类素材切成最多 2 个预览 chunk。
- 让文本预览和视频预览共享 `ChunkExtractionResult` 与知识库写入规则。

验收标准：

- 没有视频 chunk 但存在可读文本素材时，预览能从文本素材生成真实 chunk JSON。
- 文本 chunk 的上下文、证据和来源路径可追溯。
- UI 无真实素材反馈能区分“未处理素材”“无可读视频”“无可读文本”等原因。

### M5：图片、漫画与混合媒体接入

状态：未开始。

目标：

- 明确图片/漫画素材在 `materials/` 下的可消费结构。
- 决定单图、图片序列、漫画页组如何映射到 season/episode/chunk。
- 保持模型请求仍通过 `utils.ai_model_middleware`。
- 不让页面层直接读取或解析素材文件。

验收标准：

- 图片/漫画预览能生成与视频/text 一致结构的 `ChunkExtractionResult`。
- 证据引用能定位到页、帧、文件或片段。
- 失败反馈能说明是素材不可读、模型不支持还是输出结构不合法。

### M6：角色状态迭代编译与冲突消解

状态：未开始 / 部分基础能力存在。

目标：

- 基于 `episode_content.json` 按季、集逐步更新角色状态。
- 写入 `character_stage_states.json`。
- 加入冲突识别、证据优先级和最终整理策略。
- 让角色卡生成优先读取结构化知识库，而不是重新分析原始素材。

验收标准：

- 单个角色能得到按集推进的阶段状态。
- 冲突事实不会被静默覆盖，必须保留证据来源或处理说明。
- 输出页能明确区分占位预览、知识库简化预览和完整编译结果。

## 4. 模块边界

- `core/extractor.py`：作为 UI-facing 提取入口，负责任务编排、模型请求构造、洞察事件发出、chunk 保存和预览 episode 合并。
- `core/source_scanner.py`：负责素材扫描、预览 chunk 收集和 chunk 标识生成。
- `core/knowledge_base.py`：负责知识库路径、JSON 读写和结构初始化。
- `core/compiler.py`：负责从结构化知识库聚合角色状态；后续完整迭代编译应继续放在这里或其窄 helper 中。
- `utils/source_importer.py`：负责素材导入、`raw/` 与 `materials/` 对应关系，不承载 AI 推理。
- `utils/material_processing_middleware.py`：负责素材处理请求和工具校验，不直接生成洞察。
- `utils/chunker.py`：后续文本类 chunk 构造优先复用或最小扩展这里。
- `gui`：只负责触发预览、展示进度、确认高风险设置和接收洞察事件，不直接读取素材文件。

## 5. 通用验收标准

- 不绕过 `utils.ai_model_middleware.py` 直接调用模型。
- 不新增依赖，除非用户另行同意并同步说明影响范围。
- 不改变 `projects/{project_id}/knowledge_base/` 现有文件名和目录层级，除非另有迁移计划。
- 长耗时任务继续放在 Qt worker/thread 中执行。
- 用户可见文案必须同步维护四个 i18n JSON。
- 预览最多处理前 2 个 chunk，不扫描或写入超出预览范围的素材内容。
- 无可用真实素材时，UI 必须明确提示原因，不回退到项目元数据伪装真实预览。
