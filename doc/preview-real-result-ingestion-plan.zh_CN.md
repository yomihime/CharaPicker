# 真实预览结果接入计划（zh_CN）

本文用于拆分“开始预览”从占位元数据改为读取真实素材结果的后续实现任务。开发时继续遵守现有架构：不引入新技术栈，不重新设计项目，每次只实现一个小功能。

## 1. 当前问题

当前 `Extractor.run_preview_streaming()` 仍使用项目元数据构造占位 `chunk_text`，模型看到的是项目名、模式、目标角色和素材路径，而不是 `materials/` 中的真实素材内容。

因此，“开始预览”可以得到模型响应，但它不是基于真实素材分析得到的结果。

## 2. 接入目标

- 预览阶段优先读取 `projects/{project_id}/materials/` 中已经处理好的素材入口。
- 第一阶段只接入文本类素材，支持 `.txt`、`.md`、`.json`。
- 正式运行前只处理前 2 个 chunk，符合 Preview 试算要求。
- 真实 chunk 内容进入 `build_targeted_insight_request()` 的 `CURRENT_CHUNK`。
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

- 用户处理文本素材后点击“开始预览”，模型请求中的 `CURRENT_CHUNK` 来自真实文件内容。
- 没有可读取文本素材时，UI 能明确提示原因，而不是静默使用项目元数据伪装真实预览。
- 预览最多处理前 2 个 chunk，不扫描或写入超过预览范围的内容。
- 洞察事件仍通过现有 signal 流进入 `InsightStreamPanel`。
- 不绕过 `utils/ai_model_middleware.py` 直接调用模型。
- 不新增依赖，不改变 UI 架构，不影响现有素材处理流程。

