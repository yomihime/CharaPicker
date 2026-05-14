# 正式视频提取架构指南与任务计划（zh_CN）

本文面向后续 AI 开发者，用于指导 CharaPicker 正式视频提取流程的初步实现。它是实施计划与架构约束，不是当前功能已完成的证明。

最近核对日期：2026-05-14。

当前主线目标：先把“正式提取视频信息”做成可恢复、可检查、不会被预览产物污染的 Extract Once 闭环。

## 1. 使用方式

后续开发必须按本文的步进顺序推进。每个步进内可以包含多个里程碑，但完成该步进的全部里程碑后，必须暂停并向用户交付可检查状态，等待用户确认后才能进入下一步进。

可检查状态必须包含：

- 已勾选的里程碑。
- 本步进改动文件列表。
- 关键行为说明。
- 至少一个可检查的知识库路径、JSON 样例或 UI 行为。
- 已运行的验证命令和结果。
- 已知风险、未覆盖场景和后续建议。
- 用户确认记录。

不得在用户尚未检查当前步进状态时继续叠加下一步进的大范围改动。这个门禁用于避免带着严重 bug 进入后续实现。

每个步进完成后，在对应小节填写：

```md
完成记录：
- 完成日期：
- 开发分支/提交：
- 改动文件：
- 可检查状态：
- 验证命令：
- 已知风险：
- 用户确认：
```

## 2. 参考依据

开发前必须重新核对当前代码和文档，不得只凭本文推断实现事实。

主要依据：

- 主工作流说明：[提取工作流技术说明](extraction-workflow.zh_CN.md)
- 长期开发路线：[提取与角色成长编译开发路线](extraction-development-roadmap.zh_CN.md)
- 预览支线计划：[真实预览结果接入计划](preview-real-result-ingestion-plan.zh_CN.md)
- 文档维护规则：[文档维护规范](documentation-maintenance.zh_CN.md)

代码核对入口：

- `core/models.py`
- `core/source_scanner.py`
- `core/knowledge_base.py`
- `core/extractor.py`
- `core/compiler.py`
- `gui/main_window.py`
- `gui/pages/project_page.py`
- `utils/ai_model_middleware.py`
- `utils/source_importer.py`
- `utils/material_processing_middleware.py`

## 3. 目标与非目标

### 3.1 本轮目标

- 正式提取以 `projects/{project_id}/materials/` 为唯一素材消费入口。
- 正式提取支持视频素材，优先支持已经由素材处理链路准备好的视频文件和 FFmpeg 分段目录。
- 正式提取生成或更新 `source_manifest.json`。
- 正式提取按 season / episode / chunk 顺序处理视频。
- 正式提取写入正式 chunk JSON。
- 正式聚合生成 `episode_content.json`、`episode_summary.json`、`season_content.json`、`season_summary.json`。
- GUI 的 FULL 模式必须真正调用正式提取 worker，而不是继续走预览 worker。
- 预览提取作为支线并行推进，但不得污染正式提取产物。

### 3.2 本轮非目标

- 不实现文本、字幕、音频转写、图片、漫画的正式提取。
- 不实现完整角色成长迭代编译与冲突消解。
- 不实现最终角色卡质量打磨。
- 不引入新依赖。
- 不改变 `raw/` 与 `materials/` 的素材导入职责边界。
- 不让 GUI 页面层直接读取、复制、删除或解析素材文件。

## 4. 术语

- 步进：一个需要用户检查后才能进入下一阶段的开发阶段。
- 里程碑：步进内部可勾选的小任务。
- 正式产物：正式提取生成的知识库事实，允许后续 Extract Once、聚合、编译使用。
- 预览产物：预览试跑生成的临时或支线产物，只用于快速反馈、模型调参和 UI 预览。
- 未标记旧产物：当前历史代码可能已经生成的无 `extraction_stage` 字段、且无 `preview__` 文件名前缀的 JSON。正式提取不得把这类产物静默当成正式事实。

## 5. 核心架构原则

- 正式提取只消费 `materials/`，不直接重新分析外部 `source_paths`。
- 模型调用必须通过 `utils.ai_model_middleware`，不得绕过中间件直连后端。
- 知识库路径和 JSON 读写必须通过 `core.knowledge_base` 或其窄 helper。
- 长耗时提取必须放入 Qt worker/thread。
- UI 只负责触发、进度、取消、提示和展示，不承载 AI 推理或素材文件系统细节。
- 正式提取不接收用户目标角色列表作为 chunk 过滤条件；初步提取必须保留素材中出现的全部有效角色信息。
- 后续角色卡生成应优先读取正式结构化知识库，而不是重复分析原始视频。
- 预览产物必须有文件名和 JSON 字段双重标记。
- 正式提取扫描、聚合、编译默认忽略预览产物和未标记旧产物。

## 6. 预览与正式产物隔离规则

### 6.1 文件命名

预览产物统一使用 `preview__` 前缀。

```text
knowledge_base/
└── seasons/
    └── season_001/
        ├── preview__season_content.json
        ├── preview__season_summary.json
        ├── season_content.json
        ├── season_summary.json
        └── episodes/
            └── episode_001/
                ├── preview__episode_content.json
                ├── preview__episode_summary.json
                ├── episode_content.json
                ├── episode_summary.json
                └── chunks/
                    ├── preview__chunk_0001.json
                    └── chunk_0001.json
```

正式产物不使用 `preview__` 前缀。

### 6.2 JSON 字段

所有新写入的 chunk、episode、season 产物必须包含来源字段。

预览产物：

```json
{
  "extraction_stage": "preview",
  "run_type": "preview_trial"
}
```

正式产物：

```json
{
  "extraction_stage": "full",
  "run_type": "formal_extraction"
}
```

建议同时记录：

```json
{
  "source_kind": "video",
  "source_path": "相对 materials/ 的路径",
  "created_by": "CharaPicker",
  "schema_version": 1
}
```

### 6.3 正式过滤规则

正式提取和正式聚合必须执行以下过滤：

- 文件名以 `preview__` 开头：跳过。
- JSON 中 `extraction_stage == "preview"`：跳过。
- JSON 中缺少 `extraction_stage`：默认视为 `legacy_unknown`，正式聚合跳过。
- JSON 中 `extraction_stage != "full"`：正式聚合跳过。
- 只有 `extraction_stage == "full"` 的产物可进入正式 episode / season 聚合。

### 6.4 旧预览产物处理

当前历史预览链路可能已经写入未加前缀的 chunk JSON 或 `episode_content.json`。本计划不要求自动迁移用户已有知识库，但正式提取实现时必须避免把这些旧产物误认为正式产物。

第一版策略：

- 新正式聚合只读取 `extraction_stage == "full"` 的产物。
- 未标记旧产物保留在磁盘上，不自动删除。
- 如需迁移或清理旧预览产物，必须另开任务并让用户确认。

## 7. 模块职责设计

### 7.1 `core.models`

负责结构化模型。建议新增或扩展：

- `ExtractionArtifactStage`：`preview`、`full`、`legacy_unknown`。
- `ChunkExtractionResult` 增加可选来源字段。
- 如实现扫描结果模型，应保持轻量，不强迫一次性替换所有 dict manifest。

注意：

- Pydantic 模型要兼容旧 JSON 读取。
- 缺失 `extraction_stage` 时不应崩溃，但正式消费层要跳过。

### 7.2 `core.source_scanner`

负责素材扫描，不负责模型调用和知识库写入。

建议职责：

- 扫描 `materials/` 中可消费的视频。
- 识别普通视频文件。
- 识别 FFmpeg 处理后的视频分段目录。
- 生成稳定排序的 season / episode / chunk 计划。
- 为正式提取提供 `source_manifest.json` 所需信息。

初版扫描规则：

- `materials/` 根目录下的视频文件可视为 `season_001` 的多个 episode，按文件名排序。
- `materials/` 根目录下一级目录优先视为 season 或导入源目录，需根据内部结构判断。
- 如果目录下直接存在 `segment_*.mp4`，该目录视为一个 episode，segment 文件视为 chunks。
- 如果目录下存在多个视频文件且不是 segment 命名，按视频文件排序视为 episodes。
- 规则冲突时先采用最保守可解释策略，并在 manifest 中记录原始相对路径。

### 7.3 `core.knowledge_base`

负责路径、读写和过滤 helper。

建议新增：

- `PREVIEW_ARTIFACT_PREFIX = "preview__"`
- `FULL_EXTRACTION_STAGE = "full"`
- `PREVIEW_EXTRACTION_STAGE = "preview"`
- `preview_artifact_name(name: str) -> str`
- `is_preview_artifact_path(path: Path) -> bool`
- `artifact_stage_from_payload(payload: dict) -> str`
- `is_full_artifact_payload(payload: dict) -> bool`
- `list_full_chunk_result_paths(...)`
- `list_preview_chunk_result_paths(...)`
- `preview_episode_content_path(...)`
- `preview_episode_summary_path(...)`

注意：

- 现有 `list_chunk_result_paths()` 如继续存在，必须明确它是否包含 legacy 和 preview。
- 新正式流程不得调用会混读 preview 的旧列表函数。

### 7.4 `core.extractor`

负责正式提取编排和预览提取编排，但两条链路必须显式分开。

建议入口：

- `run_preview_streaming(...)`
- `run_full_extraction_streaming(...)`

正式提取入口职责：

- 加载或生成正式 manifest。
- 初始化知识库目录。
- 按 manifest 顺序处理全部视频 chunk。
- 每个 chunk 调用视频模型。
- 每个成功 chunk 写入正式 JSON。
- 每集完成后生成正式 episode 内容与摘要。
- 每季完成后生成正式 season 内容与摘要。
- 发送洞察流事件、进度、token 用量。

预览入口职责：

- 只处理前 2 个预览 chunk。
- 写入 `preview__` 产物。
- 只更新预览相关聚合。
- 不覆盖正式文件。

### 7.5 `core.compiler`

本轮不做完整重构，但必须遵守：

- 默认只读取正式 `episode_content.json`。
- 不读取 `preview__episode_content.json`。
- 如缺少正式 episode 内容，应返回空状态或明确 warning，不得偷偷回退到预览产物。

### 7.6 `gui.main_window`

负责 worker 调度。

建议新增：

- `FullExtractionWorker`
- `_full_extraction_thread`
- `_full_extraction_worker`
- `run_full_extraction(config)`
- `_on_full_extraction_succeeded(config)`
- `_on_full_extraction_failed(error)`

要求：

- PREVIEW 模式调用 `PreviewWorker`。
- FULL 模式调用 `FullExtractionWorker`。
- 正式提取期间禁用重复启动。
- 正式提取完成后提示用户可检查知识库产物。

### 7.7 `gui.pages.project_page`

本轮尽量少改页面结构。

要求：

- 当前模式为 PREVIEW 时按钮文案为“开始预览”。
- 当前模式为 FULL 时按钮文案为“开始提取”。
- 触发信号可保持一个，但 `main_window` 必须按 `config.extraction_mode` 分发。
- 用户可见新增文案必须同步四个 i18n JSON。

## 8. 正式提取数据流

```text
用户处理素材
-> utils.material_processing_middleware
-> projects/{project_id}/materials/
-> core.source_scanner 扫描正式视频计划
-> core.knowledge_base 写入 source_manifest.json
-> core.extractor 按 chunk 调用 call_video_model()
-> chunks/chunk_xxxx.json
-> episode_content.json
-> episode_summary.json
-> season_content.json
-> season_summary.json
-> 后续 compiler / generator 读取正式知识库
```

## 9. 预览提取支线

预览提取是正式提取计划的并行支线。详细计划见：[真实预览结果接入计划](preview-real-result-ingestion-plan.zh_CN.md)。

本计划只规定两条强约束：

- 预览产物必须写成 `preview__` 文件，并写入 `extraction_stage = "preview"`。
- 正式提取全过程必须忽略预览产物。

支线任务在本文第 18 节单独列出，完成时也要勾选并记录。

## 10. 步进门禁

每个步进完成后，AI 必须停下，不得主动进入下一步进，除非用户明确表示继续。

门禁检查清单：

- [ ] 本步进所有里程碑都已完成或明确标记为推迟。
- [ ] 文档 checklist 已更新。
- [ ] 完成记录已填写。
- [ ] 代码 diff 可供用户查看。
- [ ] 验证结果可复现。
- [ ] 没有已知的严重数据污染、覆盖、误删或 UI 阻塞风险。
- [ ] 用户已检查并确认进入下一步。

如果发现严重 bug，必须先修复当前步进，不能绕过门禁继续开发下一步。

## 11. 步进 S0：文档与分支准备

目标：建立本计划文档和索引入口，为后续 AI 开发提供稳定任务源。

里程碑：

- [x] S0.1 创建开发分支。
- [x] S0.2 新增本文档。
- [x] S0.3 在 `docs/README.md` 增加本文档入口。
- [x] S0.4 在 `docs/ARCHITECTURE.md` 增加本文档说明。
- [x] S0.5 明确每个步进完成后必须让用户检查。

验收：

- 文档能说明正式提取和预览提取的边界。
- 文档能说明预览产物如何被正式提取忽略。
- 文档包含可勾选里程碑和用户检查门禁。

完成记录：

- 完成日期：2026-05-14
- 开发分支/提交：`formal-video-extraction-plan` / 待提交
- 改动文件：`docs/formal-video-extraction-architecture-plan.zh_CN.md`、`docs/README.md`、`docs/ARCHITECTURE.md`
- 可检查状态：本文档已新增；文档索引和 docs 架构说明已加入入口；后续每个步进都包含里程碑、验收、完成记录和用户确认字段。
- 验证命令：`git status --short --branch`；`rg -n "formal-video-extraction-architecture-plan|步进门禁|用户确认：待用户审核|preview__" docs\README.md docs\ARCHITECTURE.md docs\formal-video-extraction-architecture-plan.zh_CN.md`；`git diff --check`。
- 已知风险：本文只完成架构计划与任务拆分，尚未改动运行时代码。
- 用户确认：待用户审核。

## 12. 步进 S1：知识库产物隔离 helper

目标：先建立 preview/full 产物隔离的底层能力，避免后续正式聚合误读预览结果。

建议改动范围：

- `core/models.py`
- `core/knowledge_base.py`
- 必要时增加窄单元测试或轻量脚本验证。

里程碑：

- [ ] S1.1 定义 `preview__` 前缀常量。
- [ ] S1.2 定义 preview/full stage 常量或枚举。
- [ ] S1.3 扩展 `ChunkExtractionResult`，兼容 `extraction_stage`、`run_type`、`source_path`、`source_kind`、`schema_version`。
- [ ] S1.4 增加 `is_preview_artifact_path(path)`。
- [ ] S1.5 增加 `artifact_stage_from_payload(payload)`。
- [ ] S1.6 增加 `is_full_artifact_payload(payload)`。
- [ ] S1.7 增加只返回正式 chunk 的列表 helper。
- [ ] S1.8 增加只返回预览 chunk 的列表 helper。
- [ ] S1.9 检查现有调用点，标记哪些仍在混读 legacy 产物。

验收：

- 正式列表不会返回 `preview__*.json`。
- JSON 缺少 `extraction_stage` 时不会崩溃，但正式 helper 不把它当正式产物。
- 旧 JSON 仍可被模型兼容读取，但正式聚合默认跳过。

可检查状态建议：

- 构造一个 preview payload、full payload、legacy payload，展示 helper 判断结果。
- 展示 `core/knowledge_base.py` 中新增函数名。

完成记录：

- 完成日期：
- 开发分支/提交：
- 改动文件：
- 可检查状态：
- 验证命令：
- 已知风险：
- 用户确认：

## 13. 步进 S2：预览产物改为专用标记

目标：让预览链路不再写入或覆盖正式产物。

建议改动范围：

- `core/extractor.py`
- `core/knowledge_base.py`
- `core/compiler.py`
- `gui/main_window.py`
- `i18n/*.json`
- `docs/preview-real-result-ingestion-plan.zh_CN.md`

里程碑：

- [ ] S2.1 预览 chunk 保存为 `chunks/preview__{chunk_id}.json`。
- [ ] S2.2 预览 chunk JSON 写入 `extraction_stage = "preview"`。
- [ ] S2.3 预览 chunk JSON 写入 `run_type = "preview_trial"`。
- [ ] S2.4 预览 episode 聚合写入 `preview__episode_content.json`。
- [ ] S2.5 预览链路不再覆盖正式 `episode_content.json`。
- [ ] S2.6 输出页预览成功后读取预览专用产物。
- [ ] S2.7 无预览产物时显示准确反馈，不再提示“正式 chunk JSON 不存在”。
- [ ] S2.8 更新预览计划文档，说明最新行为。

验收：

- 点击预览后不会生成或覆盖正式 `chunk_*.json`、`episode_content.json`。
- 预览仍能在洞察流和输出页显示结果。
- 正式 helper 忽略预览产物。

可检查状态建议：

- 展示一个预览 chunk 文件路径。
- 展示一个预览 JSON 中的 `extraction_stage` 字段。
- 展示正式 `episode_content.json` 未被预览覆盖。

完成记录：

- 完成日期：
- 开发分支/提交：
- 改动文件：
- 可检查状态：
- 验证命令：
- 已知风险：
- 用户确认：

## 14. 步进 S3：正式视频素材扫描与 manifest

目标：建立正式提取的输入计划，不调用模型。

建议改动范围：

- `core/source_scanner.py`
- `core/extractor.py`
- `core/knowledge_base.py`
- 必要时更新 `docs/extraction-development-roadmap.zh_CN.md`

里程碑：

- [ ] S3.1 新增正式视频扫描入口，不复用预览 limit=2 的扫描函数。
- [ ] S3.2 支持 `materials/` 根目录单视频列表。
- [ ] S3.3 支持一级目录内多集视频。
- [ ] S3.4 支持 FFmpeg 分段目录 `segment_*.mp4` 作为同一 episode 的多个 chunk。
- [ ] S3.5 为每个 chunk 生成稳定 `season_id`、`episode_id`、`chunk_id`。
- [ ] S3.6 生成或更新 `source_manifest.json`。
- [ ] S3.7 manifest 记录原始 `materials/` 相对路径。
- [ ] S3.8 初始化对应 knowledge_base 目录结构。

验收：

- 不调用模型也能得到完整正式提取计划。
- 多次扫描同一 `materials/` 结构生成稳定 ID。
- manifest 足以让用户追溯 chunk 来源。

可检查状态建议：

- 展示一份 `source_manifest.json` 样例。
- 展示 season / episode / chunk 的路径映射。

完成记录：

- 完成日期：
- 开发分支/提交：
- 改动文件：
- 可检查状态：
- 验证命令：
- 已知风险：
- 用户确认：

## 15. 步进 S4：正式视频 chunk 提取

目标：实现正式提取的最小模型调用闭环。

建议改动范围：

- `core/extractor.py`
- `core/models.py`
- `utils.ai_model_middleware.py` 只允许在必要时最小调整。
- `i18n/*.json`

里程碑：

- [ ] S4.1 新增 `run_full_extraction_streaming(...)`。
- [ ] S4.2 正式提取使用当前云端视频模型预设。
- [ ] S4.3 正式提取不限制前 2 个 chunk。
- [ ] S4.4 正式 chunk prompt 不使用用户目标角色列表过滤素材。
- [ ] S4.5 正式 chunk 请求包含当前 chunk 视频输入。
- [ ] S4.6 正式 chunk 写入 `chunks/{chunk_id}.json`。
- [ ] S4.7 正式 chunk JSON 写入 `extraction_stage = "full"`。
- [ ] S4.8 正式 chunk JSON 写入 `run_type = "formal_extraction"`。
- [ ] S4.9 模型输出截断时跳过当前 chunk，发出 warning，并继续后续 chunk。
- [ ] S4.10 全局配置错误时停止任务，并给出明确错误。

验收：

- 至少一个视频 chunk 能生成正式 JSON。
- 正式 chunk 不带 `preview__` 前缀。
- 正式 chunk 能被正式 helper 列出。
- 预览 helper 不会列出正式 chunk。

可检查状态建议：

- 展示正式 chunk 文件路径。
- 展示正式 chunk JSON 关键字段。
- 展示洞察流事件顺序。

完成记录：

- 完成日期：
- 开发分支/提交：
- 改动文件：
- 可检查状态：
- 验证命令：
- 已知风险：
- 用户确认：

## 16. 步进 S5：正式 episode 与 season 聚合

目标：把正式 chunk 聚合为正式 episode / season 产物。

建议改动范围：

- `core/extractor.py`
- `core/knowledge_base.py`
- `core/compiler.py`

里程碑：

- [ ] S5.1 `merge_episode_content` 只读取正式 chunk。
- [ ] S5.2 `episode_content.json` 写入 `extraction_stage = "full"`。
- [ ] S5.3 `generate_episode_summary` 只读取正式 episode content。
- [ ] S5.4 `episode_summary.json` 写入 `extraction_stage = "full"`。
- [ ] S5.5 `merge_season_content` 只读取正式 episode content。
- [ ] S5.6 `season_content.json` 写入 `extraction_stage = "full"`。
- [ ] S5.7 `generate_season_summary` 只读取正式 season content。
- [ ] S5.8 `season_summary.json` 写入 `extraction_stage = "full"`。
- [ ] S5.9 同目录存在 preview 产物时，正式聚合结果不包含 preview 内容。
- [ ] S5.10 缺失或损坏 episode 时，聚合发出 warning，不静默伪装完整。

验收：

- 正式 `episode_content.json` 的 `chunk_results` 全部来自 `full` chunk。
- 正式 `season_content.json` 全部来自正式 episode。
- 预览文件存在时不影响正式聚合。

可检查状态建议：

- 同一 episode 下同时放置 preview 和 full chunk，展示正式聚合只包含 full。
- 展示 `episode_content.json` 和 `season_content.json` 的来源字段。

完成记录：

- 完成日期：
- 开发分支/提交：
- 改动文件：
- 可检查状态：
- 验证命令：
- 已知风险：
- 用户确认：

## 17. 步进 S6：GUI 正式提取入口

目标：让 UI 的 FULL 模式真正进入正式提取流程。

建议改动范围：

- `gui/main_window.py`
- `gui/pages/project_page.py`
- `i18n/*.json`

里程碑：

- [ ] S6.1 新增 `FullExtractionWorker`。
- [ ] S6.2 `ProjectConfig.extraction_mode == FULL` 时调用正式 worker。
- [ ] S6.3 `ProjectConfig.extraction_mode == PREVIEW` 时调用预览 worker。
- [ ] S6.4 正式提取期间禁用重复启动。
- [ ] S6.5 正式提取向洞察流发送阶段事件。
- [ ] S6.6 正式提取完成后 InfoBar 提示可检查知识库结果。
- [ ] S6.7 正式提取失败时显示清晰错误。
- [ ] S6.8 四个 i18n JSON 同步新增或调整文案。

验收：

- 选择“开始提取”不会进入预览链路。
- 选择“开始预览”不会写正式产物。
- 正式提取长耗时运行不阻塞 UI 主线程。

可检查状态建议：

- 展示 FULL 模式触发的 worker 类。
- 展示 PREVIEW 和 FULL 模式分别写入的文件路径差异。

完成记录：

- 完成日期：
- 开发分支/提交：
- 改动文件：
- 可检查状态：
- 验证命令：
- 已知风险：
- 用户确认：

## 18. 支线步进 P：预览提取同步任务

详细计划见：[真实预览结果接入计划](preview-real-result-ingestion-plan.zh_CN.md)。

这些任务可以与主线并行规划，但实现时仍要遵守步进门禁。

里程碑：

- [ ] P1 预览 chunk 文件添加 `preview__` 前缀。
- [ ] P2 预览 JSON 添加 `extraction_stage = "preview"`。
- [ ] P3 预览 JSON 添加 `run_type = "preview_trial"`。
- [ ] P4 预览 episode 聚合写入 `preview__episode_content.json`。
- [ ] P5 输出页能读取预览专用 episode 产物。
- [ ] P6 预览文档同步更新当前行为。
- [ ] P7 正式提取文档持续链接预览支线计划。

验收：

- 支线产物不会覆盖正式产物。
- 预览功能仍可用于快速检查模型与素材。
- 正式提取 helper 明确忽略支线产物。

完成记录：

- 完成日期：
- 开发分支/提交：
- 改动文件：
- 可检查状态：
- 验证命令：
- 已知风险：
- 用户确认：

## 19. 步进 S7：验证与回归检查

目标：在进入更复杂的角色编译前，确认正式视频提取链路没有明显数据污染或入口错误。

里程碑：

- [ ] S7.1 空 `materials/` 时给出明确反馈。
- [ ] S7.2 无云端视频模型预设时给出明确反馈。
- [ ] S7.3 单个视频文件可生成正式知识库。
- [ ] S7.4 多 episode 视频可按顺序生成正式知识库。
- [ ] S7.5 FFmpeg 分段目录可作为 chunks 处理。
- [ ] S7.6 preview 和 full 产物并存时，正式聚合只消费 full。
- [ ] S7.7 重跑正式提取时覆盖或跳过策略清晰可见。
- [ ] S7.8 失败 chunk 不导致已完成正式产物不可读。
- [ ] S7.9 GUI PREVIEW 和 FULL 两个入口行为不同且清晰。
- [ ] S7.10 文档 checklist 和完成记录已同步。

验收：

- 用户可以通过知识库文件直接检查正式提取结果。
- 用户可以确认没有预览产物进入正式聚合。
- 未解决风险被明确写出。

完成记录：

- 完成日期：
- 开发分支/提交：
- 改动文件：
- 可检查状态：
- 验证命令：
- 已知风险：
- 用户确认：

## 20. 后续扩展预留

本计划完成后，再考虑以下任务：

- 文本、字幕、音频转写正式提取。
- 图片、漫画、混合媒体正式提取。
- 高质量 episode / season 模型摘要。
- 角色状态迭代编译与冲突消解。
- 正式提取断点续跑与运行历史管理。
- 知识库 schema 版本迁移工具。

这些扩展不应挤入本轮正式视频提取 MVP。
