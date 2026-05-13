# 真实预览结果接入计划（zh_CN）

本文用于拆分“开始预览”从占位元数据改为读取真实素材结果的后续实现任务。开发时继续遵守现有架构：不引入新技术栈，不重新设计项目，每次只实现一个小功能。

> 状态提醒：本文是阶段性接入计划，部分描述已被当前代码推进或替代。当前 `core/extractor.py` 已开始从 `materials/` 中收集视频 chunk，并通过云端模型生成/保存目标无关的 chunk JSON；本文中“第一阶段只接入文本类素材”的描述不可直接当作当前事实。实施相关任务前必须重新核对 `core/extractor.py`、`gui/main_window.py` 和 `AGENTS.md` 的来源优先级。

## 1. 当前问题

当前 `Extractor.run_preview_streaming()` 已开始读取 `materials/` 中的预览视频 chunk，并把模型返回的结构化结果写入 `knowledge_base/seasons/.../episodes/.../chunks/`。预览提取阶段不向模型传入用户填写的目标角色列表，chunk 结果的 `targets` 默认为空，以便后续角色卡生成复用同一份 Extract Once 产物。

云端视频预览的“输出 Token / 分钟”会按视频 chunk 时长换算为单次请求的 `max_tokens`。低于建议值时，UI 先弹窗让用户确认；确认后继续运行，不在洞察流重复展示低预算提示。只有模型实际因为 `finish_reason=length` 或 `max_tokens` 截断结构化 JSON 时，才在洞察流提示该 chunk 被跳过并继续处理其他结果。

仍需持续完善的是：更多素材类型接入、完整提取流程、episode/season 摘要质量、角色状态迭代编译和冲突消解。

## 2. 接入目标

- 预览阶段优先读取 `projects/{project_id}/materials/` 中已经处理好的素材入口。
- 预览接入应保持素材类型可扩展；当前代码已优先推进视频 chunk，文本、图片等素材仍可按阶段补齐。
- 正式运行前只处理前 2 个 chunk，符合 Preview 试算要求。
- 真实 chunk 内容进入模型提取请求；初步提取不使用用户预设目标角色列表。
- 模型返回的洞察继续通过 `InsightStreamPanel` 展示。
- 预览结果后续可复用已有知识库结构，逐步写入 `knowledge_base`。

## 3. 实现顺序

1. 增加文本素材读取能力：从 `materials/` 按稳定顺序读取 `.txt`、`.md`、`.json` 文件内容。
2. 增加预览 chunk 构造能力：把读取到的文本合并并切成最多 2 个预览 chunk。
3. 接入 `run_preview_streaming()`：用第一个真实 chunk 替换当前元数据占位 chunk。
4. 增加无真实文本素材时的用户可见反馈：通过现有洞察事件说明当前预览仍缺少可读取素材。
5. 将首段真实洞察保存为 `ChunkExtractionResult`，落盘到 `knowledge_base/seasons/.../chunks/`。
6. 预览完成后合并 `episode_content.json` 和 `episode_summary.json`，为后续完整提取复用。
7. 后续再接入视频字幕、音频转写、图片/漫画多模态解析。

## 4. 模块边界

- `core/extractor.py`：负责任务编排、真实 chunk 读取调用、模型请求构造和洞察事件发出。
- `utils/source_importer.py`：继续负责素材导入、raw/materials 对应关系，不承载 AI 推理。
- `utils/material_processing_middleware.py`：继续负责素材处理请求和工具校验，不直接生成洞察。
- `utils/chunker.py`：如果已有合适文本分块能力，预览 chunk 构造应优先复用；不足时再做最小补充。
- `gui`：只负责触发预览、展示进度和洞察事件，不直接读取素材文件。

## 5. 验收标准

- 用户处理素材后点击“开始预览”，模型请求来自 `materials/` 中可消费的真实素材 chunk。
- 没有可读取真实素材 chunk 时，UI 能明确提示原因，而不是静默使用项目元数据伪装真实预览。
- 预览最多处理前 2 个 chunk，不扫描或写入超过预览范围的内容。
- 初步提取生成的 chunk JSON 不绑定用户预设目标角色，后续角色卡生成再基于目标角色读取和过滤结构化结果。
- 输出 Token / 分钟过低时只在开始前弹窗确认；用户确认后继续运行，洞察流不重复展示低预算提示。
- 模型输出被长度上限截断时，洞察流提示原因并跳过当前 chunk，继续使用其他可用结果。
- 洞察事件仍通过现有 signal 流进入 `InsightStreamPanel`。
- 不绕过 `utils/ai_model_middleware.py` 直接调用模型。
- 不新增依赖，不改变 UI 架构，不影响现有素材处理流程。

