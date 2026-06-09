# 第一阶段：提取质量与可观测性执行计划（zh_CN）

> 本文档是第一阶段执行计划，不代表当前实现状态。
> 执行前仍需按本文复核当前代码、脚本、日志规范和真实试跑结果；若代码事实与本文冲突，以当前代码事实为准并先更新本计划。

最近整理日期：2026-06-09。

计划阶段：正式执行计划，待执行前复核。

适用阶段：路线 01，先稳住现有正式提取链路，再进入路线 02 多素材平级接入前重构解耦。

## 1. 目的与范围

第一阶段目标是把已经落地的正式提取主线变成可回归、可定位、可继续重构的稳定基线。

本阶段承接 `docs/plans/TODO.zh_CN.md` 中 P1「提取质量与可观测性」的三类事项：

- 增强正式提取回归验证。
- 持续维护 prompt 边界，尽量避免模型把虚构素材结构化提取误判为受限生成请求。
- 长期监测提取进度条和洞察事件是否真实反映工作流进度。

本阶段关注当前已经存在的视频正式提取链路、知识库聚合、日志、安全摘要、prompt 维护边界和 GUI 进度反馈。它是后续路线 02 与路线 03 的前置稳定性门槛。

## 2. 非目标

- 不接入文本、字幕、图片、漫画或混合媒体等新素材类型。
- 不做多素材平级抽象重构；相关工作留给路线 02。
- 不改变 `projects/{project_id}/knowledge_base/` 的长期目录语义。
- 不改变角色卡母本事实来源：正式角色卡仍以 `knowledge_base/character_cards/{card_id}/card.json` 中的 CharaPicker JSON 为唯一事实来源。
- 不绕过 `utils.ai_model_middleware` 直接调用模型后端。
- 不把 prompt 正文硬编码进 `core`、`gui` 或其他业务代码。
- 不把手动真实素材试跑作为自动化回归验证的替代品。
- 不为了完成 P1 引入新依赖或 GUI 自动化测试框架。

## 3. 已确认决策

- 后续路线按 `01 -> 02 -> 03` 推进：先稳住正式提取质量与可观测性，再做多素材前解耦，最后推进多素材覆盖。
- 第一阶段只处理稳定性、回归验证、prompt 边界和进度反馈，不承担新素材类型扩展。
- 第一阶段执行入口固定为本文档，文件名前缀 `01-` 用于标识路线顺序。
- prompt 调整优先维护 `res/default_prompts.json` 或用户 prompt override；业务代码不得长期拼接或复制 prompt 正文。
- GUI 页面层只负责触发、进度、反馈和洞察展示；正式提取、知识库写入、聚合和角色卡 stale 标记仍属于 `core`。
- 本阶段回归脚本优先保持单文件轻量入口；后续若仓库建立正式测试体系，再评估是否迁移到测试目录。
- 若执行中需要新增或改动 stale reason，应优先集中到常量或共享协议；只验证既有 reason 时不强制重构。
- 第一阶段完成记录固定写入 `docs/plans/TODO.zh_CN.md`；除非后续需要完整历史叙述，否则不另建 completed 归档文档。
- 预算设置必须区分输出、输入和上下文窗口：`输出 Token / 分钟` 只用于视频 chunk 信息提取的输出上限，不得泛化为输入预算、上下文预算、文本聚合预算、角色卡编译预算或其他素材类型的通用设置。模型页应把现有单个输出 token 控件改为“预算设置”按钮，打开独立弹窗维护各类预算。
- 执行时应记录真实 prompt 拒绝样例的脱敏摘要，让用户有机会主动打包回传；代码中应提供基于用户回传样例更新提示词的路径，优先落到用户 prompt override，确认通用后再维护默认 prompt。
- 拒绝样例不得自动上传。应用只生成本地样例记录和用户主动触发的 zip 包，后续更新流程从固定输出目录读取 zip 或由用户手动提供。
- 本阶段完成后才能进入路线 02。若 P1 回归脚本或进度反馈仍不能稳定说明当前正式提取状态，应继续收敛第一阶段。

## 4. 当前状态与缺口

### 4.1 当前状态

当前代码已具备以下基础能力：

- 正式提取入口位于 `core.extractor.Extractor.run_full_extraction_streaming()`。
- 正式提取已有完整提取、洁净提取、快速提取、线性上下文、AI episode/season 整理、run 隔离和 stale 标记等基础能力。
- 正式 JSON 调用封装位于 `core/extraction_ai.py`，已有 JSON 三次重试、输出截断判断和 attempt metadata。
- 知识库 run 匹配、正式 artifact 判定、可再生提取产物清理等 helper 位于 `core/knowledge_base.py`。
- 已有最小验证脚本 `scripts/validate_formal_extraction_workflow.py`。
- GUI 预览和正式提取 worker 位于 `gui/main_window.py`，通过 `emit_progress` 与 `emit_token_usage` 更新项目页。
- 项目页进度条和 token 用量显示位于 `gui/pages/project_page.py`。
- 日志等级和脱敏边界已沉淀到 `docs/reference/runtime-middleware.zh_CN.md`。
- 默认 prompt 由 `res/default_prompts.json` 管理，并通过 `utils.ai_model_middleware` 加载。

### 4.2 已有验证覆盖

`scripts/validate_formal_extraction_workflow.py` 当前至少覆盖：

- 快速提取并发数归一化。
- 正式 JSON 输出在第三次尝试成功时返回 payload 与 attempts。
- 正式 JSON 输出三次都不可解析时抛出 `FormalExtractionJsonError`。
- 快速提取在没有可用 chunk 输入时跳过 episode/season 聚合并返回零 token usage。

### 4.3 主要缺口

当前 P1 仍需补齐：

- run 过滤和旧 run artifact 不被当前正式聚合误读。
- 洁净提取只清理可再生提取产物，不误删用户素材、角色卡母本或导出结果。
- 完整提取、洁净提取、快速提取的分流边界可验证。
- JSON 三次重试、输出截断、token usage 和 attempt metadata 的回归覆盖更完整。
- 上下文预算降级和跳过片段聚合的可观察行为；若上下文预算逻辑尚未形成独立 helper，本阶段先记录现状和风险，不为测试强行拆分业务代码。
- 正式提取成功后角色卡 stale 标记条件明确且可验证。
- 进度条对开始、跳过、失败、完成、前置失败等状态的反馈不误导。
- prompt 拒绝样例维护流程仍停留在原则层，需要写清复现、归档、调整和验证边界。

### 4.4 当前预算规则

当前预算由三类规则共同决定：

- 视频 chunk 输出 token 预算来自云模型预设的 `max_output_tokens`，在 UI 语义上按“每分钟输出 Token”配置；默认值为 2048，输入值按 128 步进规整，并限制在 128 到 8192 之间。预览、完整提取和快速提取都会按 chunk 时长调用 `scale_cloud_max_output_tokens_for_video_duration()`，把每分钟预算换算为单次请求 `max_tokens`。
- 模型上下文窗口来自云模型预设的 `context_window_tokens`。用户手动填写的值优先；没有手动值时，`complete_context_window_tokens()` 会尝试按 provider 和 model name 推断内置上下文窗口；仍无法推断时，正式提取通过 `context_window_budget_tokens()` 使用 32768 token fallback。上下文窗口值会被限制在 4096 到 10,000,000 之间。
- episode/season 文本聚合输出预算集中在 `core/extraction_budget.py` 的 `TEXT_MERGE_OUTPUT_BUDGETS`。每个 purpose 有 `min_tokens`、`target_tokens`、`max_tokens`、按 source item 增量和按输入估算增量；`resolve_text_merge_output_tokens()` 会先按这些规则计算请求输出，再受 `context_window_tokens - reserved_input_tokens - 1024` 的安全余量约束。若可用输出低于该 purpose 最小值，当前代码仍返回最小值，并由 `text_merge_budget_warning()` 写入聚合 warning。

输入 token 估算由 `core.extraction_context.estimate_context_tokens()` 提供：CJK/Kana/Hangul 字符按 1 token 估算，ASCII 约按 4 字符 1 token，最后乘以 1.2 安全系数。

本阶段不要求为了测试强行拆分预算逻辑。执行时应优先为现有 helper 增加离线验证；若发现预算逻辑仍嵌在难以验证的业务流程中，只记录现状、风险和后续抽取建议。

### 4.5 预算设置边界

P1 对预算设置的目标是让用户知道自己在调什么，也让执行者能验证预算是否被正确传入提取链路。这里必须避免把视频输出预算误当成所有模型调用的通用预算。

- 模型页不应继续直接展示一个容易误读的 `输出 Token / 分钟` 行。建议替换为“预算设置”按钮，点击后打开预算设置弹窗。
- 预算设置弹窗至少包含：`输入/上下文窗口 Token`、`视频输出 Token / 分钟`、`图片输出 Token / 张`、`音频输出 Token / 分钟`、`角色卡编译输出 Token`。底部提供“恢复默认”“确认”“取消”。
- `输入/上下文窗口 Token`：作为云模型预设的一部分展示或设置，用于 episode/season 文本聚合预算、上下文选择和降级判断。UI 需要清楚区分手动填写、内置推断和 32768 fallback，避免用户误以为只调输出预算就能解决输入过长或上下文过长问题。
- `视频输出 Token / 分钟`：只作为视频 chunk 信息提取的输出预算入口。它控制预览、完整提取和快速提取的视频 chunk 单次请求输出上限；实际请求值按 chunk 时长换算。它不得用于输入 token 预算，不得用于上下文窗口预算，也不得作为文本、图片、音频、漫画或混合媒体的通用输出预算口径。
- `图片输出 Token / 张`：用于后续图片或漫画单张图像理解的输出上限。P1 只定义设置口径；路线 03 接入图片/漫画时再接入实际提取链路。
- `音频输出 Token / 分钟`：用于后续音频理解或音频转写后摘要类任务的输出上限。P1 只定义设置口径；路线 03 接入音频消费链路时再确认实际用法。
- `角色卡编译输出 Token`：用于角色卡 AI 复核与最终 JSON 生成。它是文本生成预算，不应使用视频、图片或音频预算；也不应使用“每分钟”语义。
- 输入 token 预算：当前不应由用户用输出预算直接设置。输入侧应通过上下文窗口、上下文选择、上下文降级、chunk 切分和素材处理策略控制。
- episode/season 各 purpose 的 `min/target/max` 输出预算属于内部策略，本阶段不设计用户逐项配置入口；如后续需要高级调参，应另起计划。
- 当视频 chunk 模型输出因 token 上限被截断时，错误反馈应继续建议提高“输出 Token / 分钟”；当问题来自输入过长、上下文窗口不足或文本聚合预算不足时，反馈应指向上下文窗口设置、上下文降级或模型能力，而不是误导用户只调输出预算。
- 当前代码中，角色卡别名校验使用 `min(cloud_preset.max_output_tokens, 1024)`，角色卡 AI 复核使用 `cloud_preset.max_output_tokens`。这属于历史复用口径；P1 应把角色卡编译改为使用独立的 `角色卡编译输出 Token` 或内部编译预算 helper。别名校验可继续保留 1024 以内的内部小预算。

## 5. 模块边界

### 5.1 core

`core` 负责：

- 正式提取流程、模式分流和 run 统计。
- 知识库路径 helper、JSON 读写、run 匹配和 artifact 判定。
- episode/season 聚合、上下文预算选择和跳过策略。
- 角色卡 stale 标记触发条件。
- 生成结构化洞察事件、token usage 和进度回调。

`core` 不负责：

- Qt 页面布局。
- UI 文案展示格式。
- 直接读取或写入 i18n 文件。
- 绕过模型中间件访问后端。

### 5.2 gui

`gui` 负责：

- 用户触发提取。
- 创建 worker/thread。
- 连接进度、token usage、洞察事件、成功和失败信号。
- 展示进度条、按钮状态、InfoBar 和洞察流。

`gui` 不负责：

- 拼接知识库路径。
- 判断正式知识库 artifact 是否属于当前 run。
- 编译角色卡或判断 stale 条件。
- 处理 AI 推理或素材解析细节。

### 5.3 utils 与 res

`utils.ai_model_middleware` 是模型调用统一入口。默认 prompt 正文放在 `res/default_prompts.json`，用户覆盖通过 `utils.prompt_preferences` 生效。

日志和网络脱敏继续遵循 `docs/reference/runtime-middleware.zh_CN.md`，不得在普通日志中输出 API Key、完整 prompt、完整模型响应、隐私文本或大型原始素材内容。

## 6. 里程碑

### M01：执行前代码与文档复核

交付：

- 复核并记录当前正式提取入口、验证脚本、日志规范、prompt 管理和 GUI 进度链路。
- 若发现本文与当前代码冲突，先更新本文，再执行代码改动。

必须复核：

- `core/extractor.py`
- `core/extraction_ai.py`
- `core/knowledge_base.py`
- `core/character_card_store.py`
- `scripts/validate_formal_extraction_workflow.py`
- `gui/main_window.py`
- `gui/pages/project_page.py`
- `res/default_prompts.json`
- `docs/reference/runtime-middleware.zh_CN.md`

验收：

- 执行者能说明当前正式提取完整/洁净/快速三种模式的入口和主要分支。
- 执行者能列出现有验证脚本已覆盖和未覆盖的项目。
- 没有把 roadmap、框架文档或历史归档当作当前实现事实。

边界：

- 本里程碑只做复核和必要的计划修正，不改业务行为。

### M02：正式提取回归脚本补强

交付：

- 增强 `scripts/validate_formal_extraction_workflow.py`，优先保持轻量、离线、无真实模型调用、无 GUI 依赖。
- 新增或整理纯逻辑验证 helper，使脚本能覆盖正式提取关键 contract。
- 本里程碑优先覆盖不需要临时项目目录的纯函数或纯 helper contract；需要创建临时项目树的清理、run artifact 和 stale 验证放到 M03/M04。

建议覆盖：

- `core.extraction_ai.call_formal_json_model()` 的成功、失败、截断和 attempt metadata。
- `core.knowledge_base.is_matching_run_artifact_payload()` 与 `is_full_artifact_payload_for_run()` 的 run 过滤。
- 旧 run、空 run、缺字段 artifact、preview artifact 不应被正式当前 run 聚合消费。
- 快速提取无输入、部分输入、跳过 episode/season 时的 stats 和 token usage。
- 上下文预算降级相关 helper 的可预测选择结果；若当前代码没有可独立验证 helper，本阶段只记录现状、风险和后续抽取建议，不把 helper 抽取作为 M02 强制交付。

验收：

- 可运行：

```powershell
python scripts/validate_formal_extraction_workflow.py
```

- 若使用 Conda 环境，可运行：

```powershell
conda run -n CharaPicker python scripts/validate_formal_extraction_workflow.py
```

- 脚本失败时能明确指出 contract 破坏点，而不是只在真实素材试跑中暴露。

边界：

- 不调用真实云端模型。
- 不依赖用户本地 `projects/` 私有素材。
- 不写入长期项目数据。
- 不创建长期项目树；确需文件系统验证时使用临时目录，并归入 M03/M04。

### M03：洁净提取与模式分流验证

交付：

- 补齐完整提取、洁净提取、快速提取三种模式的分流验证。
- 验证洁净提取清理范围只包含可再生提取产物。
- 本里程碑允许使用临时项目树验证清理命中范围，但不得读取或改写用户真实 `projects/` 数据。

重点检查：

- `ExtractionMode.FULL` 进入线性正式提取主线。
- `ExtractionMode.CLEAN` 先调用可再生 artifact 清理，再进入正式提取主线。
- `ExtractionMode.FAST` 进入快速并发 chunk 提取和 episode/season 并发整理。
- `core.knowledge_base.clean_regenerable_extraction_artifacts()` 不清理 `raw/`、`materials/`、角色卡母本、导出产物和用户配置。

验收：

- 清理 dry run 或临时测试项目能证明仅命中预期知识库产物。
- 三种模式分流的最小验证不依赖真实模型响应。
- 现有正式提取 UI 入口仍能根据项目页模式选择进入正确 worker。

边界：

- 不重新设计提取模式。
- 不改变用户对洁净提取的确认流程；如需改 UI 文案，必须同步四个 `i18n` JSON。

### M04：知识库聚合、run 隔离与 stale 标记

交付：

- 验证正式聚合只消费当前 `extraction_run_id` 的合格产物。
- 验证 stale 标记只在正式提取产生有效更新后触发。
- 本里程碑允许使用临时项目树构造最小知识库和角色卡样例，用于验证 run artifact 与 stale contract。

重点检查：

- chunk、episode_content、episode_summary、season_content、season_summary 的 run ID 一致性。
- 旧 run 产物不会被当前 run 的 episode/season 聚合读取。
- preview 产物不会被正式聚合当作正式事实。
- 正式提取没有有效 chunk 或快速模式 season 整理失败时，不应错误标记角色卡 stale。
- 若执行中需要新增或改动 stale reason，应优先集中到常量或共享协议；若只验证既有 reason，可不强制重构。

验收：

- 有最小自动化验证覆盖 run 过滤和 stale 触发条件。
- 角色卡母本文件不会被 P1 的验证或清理流程误写。
- run_stats 中 stale 计数和 stale_card_ids 与实际标记结果一致。

边界：

- 不改变角色卡编译证据层规则。
- 不把预览产物升级为正式知识库事实。

### M05：进度、token usage、预算设置与洞察事件一致性

交付：

- 明确预览和正式提取的进度 contract。
- 对正式提取的关键路径建立最小进度序列验证或手动验收清单。
- 检查 token usage 在 chunk、episode、season 和失败/跳过场景中的展示是否可理解。
- 将模型页现有单行输出 token 控件规划为“预算设置”弹窗，并验证各预算字段只进入对应链路。
- 明确角色卡编译使用独立编译输出预算，不再复用视频每分钟预算。

建议覆盖场景：

- 正式提取开始。
- 洁净提取清理开始、清理失败、清理完成。
- 无正式视频 chunk 时停止。
- chunk 成功。
- chunk JSON 不可解析后失败或跳过。
- 输出截断导致当前 chunk 停止。
- episode/season 聚合成功、跳过、失败。
- 快速提取部分成功。
- stale 标记完成。
- 前置失败。
- 正常完成。

验收：

- 前置失败不显示为 100%。
- 跳过和失败不会导致进度条卡死或假完成。
- 进度值始终限制在 0 到 100。
- 洞察流只展示用户关心的结构化事件，不展示普通 DEBUG 日志。
- token usage 没有数据时显示 pending 或 empty，不伪造总量。
- 预算设置弹窗能保存、恢复默认、确认和取消；取消不应改写预设。
- 视频、图片、音频、角色卡编译和上下文窗口预算在 UI 文案和代码字段上不互相冒名。
- 角色卡编译请求不再使用视频每分钟预算；别名校验如保留内部 1024 以内小预算，需要在代码中有清晰注释或 helper 名称。

边界：

- 本阶段不引入 GUI 自动化测试框架。
- 可先用 `emit_progress` 捕获序列和手动 UI 验收清单完成 P1 验收。

### M06：Prompt 拒绝样例维护流程

交付：

- 在计划或参考文档中写清 prompt 拒绝样例的处理流程。
- 有真实拒绝样例时，再修改 `res/default_prompts.json` 或指导用户使用 prompt override。
- 执行时记录真实拒绝样例的脱敏摘要，并提供用户主动打包样例的路径。
- 代码中应存在基于用户回传样例更新提示词的方法；项目特定样例优先更新用户 prompt override，确认具备通用价值后再维护 `res/default_prompts.json`。
- 设计拒绝样例本地记录目录和 zip 打包目录。建议记录目录为 `projects/{project_id}/cache/refusal_samples/{sample_id}/`，固定 zip 输出目录为 `projects/{project_id}/output/refusal_samples/`。
- 在设置页或关于页提供“打包拒绝样例”入口；优先放设置页，关于页可只放说明或跳转入口。

处理流程：

1. 提取流程遇到模型拒绝或供应商策略拒绝时，写入一份本地 `refusal_sample.json` 描述文件。
2. `refusal_sample.json` 至少记录 sample_id、created_at、project_id、prompt purpose、模型供应商、模型名、backend、素材类型、阶段、extraction_run_id、season/episode/chunk 标识、项目内素材相对路径、finish reason 或错误摘要、是否有用户 prompt override、应用版本和脱敏说明。
3. 默认不复制素材，不写入完整 API Key、完整 prompt、完整模型响应或隐私文本。素材路径优先保存项目内相对路径；确需外部路径时必须脱敏或要求用户确认。
4. 用户在设置页或关于页点击“打包拒绝样例”后，应用读取 `refusal_sample.json`，把描述文件和被引用的素材副本一起打进 zip。素材缺失时仍生成 zip，并在 JSON 或打包结果中写入缺失 warning。
5. zip 包输出到固定目录 `projects/{project_id}/output/refusal_samples/`。应用只打开或提示该本地目录，不自动上传。
6. 用户必须显式选择是否回传 zip；应用不得自动上传素材、prompt 或模型响应。
7. 更新流程从用户提供的 zip 开始：读取 `refusal_sample.json`，判断问题属于 prompt 语气、输出结构约束、模型后端策略、输出 token 不足，还是素材内容本身。
8. 若属于用户项目特定需求，优先通过用户 prompt override 更新。
9. 若确认具备通用价值，再维护 `res/default_prompts.json` 并保持 JSON 输出约束。
10. 修改后用相同脱敏样例或用户允许的打包素材复跑，并确认正式提取 JSON 可解析。

验收：

- prompt 修改不绕过 `utils.ai_model_middleware`。
- prompt 修改后仍要求输出原始 JSON object。
- 没有在业务代码中新增长期 prompt 正文。
- 用户回传样例路径不会自动导出隐私素材，且给用户明确的选择权。
- zip 包内至少包含 `refusal_sample.json`；素材可用且用户确认后才随包复制。
- 打包按钮写入固定输出目录，并能清楚提示 zip 路径和缺失素材 warning。

边界：

- 没有真实拒绝样例时，不主动做大幅 prompt 重写。
- 不把安全拒绝问题全部归因于 prompt；输出 token、模型能力和素材内容都需要区分。
- 不建立自动联网回传；样例回传必须由用户主动触发。
- 不把拒绝样例 zip 放入仓库，不提交用户素材、真实样例 zip 或本地 sample cache。

### M07：第一阶段验收与进入路线 02 门槛

交付：

- 在 `docs/plans/TODO.zh_CN.md` 标记第一阶段完成状态，并记录验证命令、通过结果、未解决风险和是否允许进入路线 02。
- 如需更长历史说明，可在后续单独归档；默认不另建 completed 文档。

进入路线 02 前必须满足：

- `scripts/validate_formal_extraction_workflow.py` 已覆盖 P1 的核心 contract，且在当前环境可通过。
- 正式提取三种模式的分流边界已复核。
- 洁净提取清理范围已验证。
- run 隔离和旧产物过滤已验证。
- stale 标记触发条件已验证。
- 进度条和洞察事件有清晰验收记录。
- prompt 维护边界已经写清，且没有硬编码 prompt 正文。

边界：

- 若发现需要架构重构才能完成的事项，应记录为路线 02 输入，不在第一阶段临时大改。

## 7. 验证命令

基础验证：

```powershell
python scripts/validate_formal_extraction_workflow.py
```

Conda 环境验证：

```powershell
conda run -n CharaPicker python scripts/validate_formal_extraction_workflow.py
```

可选 lint：

```powershell
python -m ruff check .
```

说明：

- 仓库当前未固定 pytest 配置或独立 typecheck 命令。
- `requirements.txt` 未声明 Ruff；只有当前环境已安装 Ruff 时才运行 lint。
- 本阶段如需真实素材手动验收，必须使用用户明确允许的本地素材，并避免把素材内容、完整外部路径或隐私文本写入日志和文档。

## 8. 手动验收清单

完成代码改动后，至少手动检查：

- 项目页可选择预览、完整提取、洁净提取和快速提取。
- 洁净提取仍有用户确认，不会静默清理可再生产物。
- 无可用正式视频 chunk 时，进度和错误反馈不显示成功完成。
- 正式提取失败时按钮状态恢复可用。
- token usage 在 pending、empty 和有用量三种状态下显示合理。
- 预算设置弹窗中的输入/上下文窗口、视频、图片、音频和角色卡编译预算能恢复默认、确认保存和取消放弃。
- 洞察流不展示普通 DEBUG 日志。
- 角色卡页面现有角色卡不会因为失败提取被错误标记为 stale。

## 9. 代码自审查要求

每个提交分组前检查：

- 是否保持 `core`、`gui`、`utils` 边界。
- 是否新增了业务代码中的 prompt 正文；如有，改到 `res/default_prompts.json`。
- 是否绕过 `utils.ai_model_middleware`；如有，必须回退。
- 是否在普通日志中输出完整素材路径、prompt、模型响应、API Key 或隐私文本。
- 是否误碰 `projects/`、`config.yaml`、`log/`、`bin/` 或 `models/` 中的本地用户数据。
- 是否让 GUI 直接拼接知识库路径或判断 run artifact。
- 是否让验证脚本依赖真实模型、真实用户素材或 GUI。
- 是否新增 UI 可见文案；如有，同步四个 `i18n` JSON。
- 是否改变长期数据结构；如有，先更新对应 `ARCHITECTURE.md` 或普通项目文档。
- 是否误把拒绝样例 cache、zip 包或用户素材加入源码提交；如有，必须移出并更新忽略规则或输出目录说明。

进入用户验收前再做一次整体自审查，确认没有把临时调试入口、测试项目数据或一次性日志留在源码结构中。

## 10. 提交分组

### G01：第一阶段计划定稿与后续修订

覆盖：

- 本文档从框架扩写为正式执行计划，并承载后续审核打磨修订。
- 如有必要，同步 `docs/plans/README.md`、`docs/README.md` 或 `docs/plans/TODO.zh_CN.md` 中的状态描述。

建议提交信息：

```text
docs: finalize extraction quality observability plan
```

提交前检查：

- 链接指向 `01-extraction-quality-observability-plan.zh_CN.md`。
- 文档没有把未实现内容写成已实现事实。

### G02：回归脚本与离线验证

覆盖：

- M02。
- M03 中不依赖真实项目数据的离线验证。
- M04 中 run 隔离和 stale 条件的最小离线验证。

建议提交信息：

```text
test: expand formal extraction workflow validation
```

提交前检查：

- `python scripts/validate_formal_extraction_workflow.py` 通过。
- 脚本不调用真实模型，不读取用户私有素材。

### G03：必要的正式提取行为修正

覆盖：

- 回归脚本暴露出的 `core` 行为缺口。
- 洁净提取、run 隔离、聚合跳过、stale 标记等必要修复。

建议提交信息：

```text
fix: stabilize formal extraction workflow contracts
```

提交前检查：

- 回归脚本通过。
- 没有改变新素材路线或知识库长期结构。

### G04：进度反馈与文案修正

覆盖：

- M05 中需要代码修正的进度、token usage、失败反馈或洞察事件问题。
- 如有 UI 文案变化，同步 `i18n/*.json`。

建议提交信息：

```text
fix: align extraction progress feedback with workflow state
```

提交前检查：

- 前置失败不显示 100%。
- 按钮状态能在成功和失败后恢复。
- 洞察流没有普通 DEBUG 日志。

### G05：Prompt 样例维护与阶段收尾

覆盖：

- M06 中因真实拒绝样例产生的 prompt 修改。
- M07 第一阶段完成小结或 TODO 状态同步。

建议提交信息：

```text
docs: record extraction observability completion
```

或在确实修改默认 prompt 时：

```text
fix: tune formal extraction prompt safety boundaries
```

提交前检查：

- prompt 修改仍保持 JSON 输出约束。
- 没有把样例中的隐私素材内容写入文档或日志。

## 11. 用户验收流程

建议验收顺序：

1. 执行自动验证脚本。
2. 用一个可公开或用户明确允许的本地测试项目检查完整提取。
3. 检查洁净提取确认、清理范围和后续正式提取。
4. 检查快速提取在部分成功或跳过时的进度与洞察事件。
5. 检查预算设置弹窗保存、恢复默认和取消行为，并确认视频输出预算不会影响角色卡编译预算。
6. 若近期有安全拒绝样例，复跑对应样例并确认 JSON 输出约束。
7. 检查角色卡页面现有卡片 stale 状态是否符合正式提取结果。

用户验收通过后，更新 `TODO.zh_CN.md` 标记第一阶段状态，再判断是否进入路线 02。

## 12. 验收后收尾

只有满足以下条件后才进入收尾：

- M01 到 M07 已完成。
- 用户已经试用检查。
- 已知 bug 已修复。
- 必要 UI 布局和文案调整已完成。

收尾可包含：

- 删除临时测试项目、调试开关和一次性日志。
- 移除重复 helper 或保留说明不足的桥接代码。
- 在 `docs/plans/TODO.zh_CN.md` 整理阶段完成记录并更新 P1 状态。
- 准备进入 `02-multi-material-refactor-plan.framework.zh_CN.md`。

若收尾时发现行为 bug，应回到对应里程碑修复，不把 bug 修复塞进收尾项。

## 13. 执行时复核点

当前没有阻塞第一阶段执行的开放决策。执行时仍需复核：

- 当前上下文预算规则是否仍与本文 4.4 一致；若代码已变化，以代码事实更新本文。
- 用户回传拒绝样例的脱敏摘要字段、保存位置和 UI 文案；如果新增用户可见文本，必须同步四个 `i18n` JSON。
- 第一阶段完成记录在 `docs/plans/TODO.zh_CN.md` 中的标记形式，避免把短期执行日志写成长期噪音。
