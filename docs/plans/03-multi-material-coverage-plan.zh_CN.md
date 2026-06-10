# 第三阶段：多素材种类支持执行计划（zh_CN）

最近整理日期：2026-06-10

计划状态：正式执行计划，依赖路线 02 的架构图审核与多素材接入准备完成。

适用阶段：路线 03，在路线 01 稳住提取质量与可观测性、路线 02 完成多素材平级接入前重构解耦之后执行。若路线 02 尚未完成，只允许补充本计划、补充 02 的结构图和新媒体准备矩阵，不得直接实现路线 03 的素材提取功能。

执行闸门：开始路线 03 代码实现前，必须确认路线 02 已经由用户审核通过当前结构图、目标结构图和多素材接入准备矩阵。该矩阵至少覆盖文本、字幕、音频转写、原生音频理解、图片、漫画和混合媒体的素材类型、提取单元、预算口径、模型能力、证据引用、预览入口、正式入口、知识库落点和失败反馈。

## 1. 目的

CharaPicker 的长期方向是 Extract Once：不同来源的素材先被整理成可追溯的结构化知识库，后续角色卡、洞察和质量评估优先消费知识库，而不是反复分析原始素材。

当前稳定实现主要围绕视频素材。视频预览、正式视频提取、视频 chunk 聚合、音频转写辅助和角色卡编译已经形成基础链路，但文本、字幕、音频、图片、漫画和混合媒体仍没有作为平级素材完整进入预览、正式提取和知识库消费路径。

第三阶段的目标是补齐这些素材种类覆盖，让用户可以把番剧、漫画、图片、字幕、音频和文本资料作为同一项目的素材来源，并让它们最终沉淀为同一套角色知识库事实。

## 2. 范围

本计划覆盖多素材种类的真实接入，包括：

- 文本素材：`.txt`、`.md`、可控结构的 `.json` 等文本入口。
- 字幕素材：`.srt`、`.ass`、`.vtt` 等带时间轴或台词结构的入口。
- 音频转写：通过 ASR/STT 把音频或视频音轨转成可追溯 transcript。
- 原生音频理解：模型直接理解音频中的语气、环境声、音乐、画外声音等非逐字转写线索。
- 图片素材：单图、图片序列、插画、截图等视觉入口。
- 漫画素材：漫画页、页组、章节目录、图片序列形式的漫画素材。
- 混合媒体：同一 episode 中同时存在视频、字幕、音频、图片、漫画或文本补充材料。

本计划还覆盖：

- 这些素材在 `raw/`、`materials/`、`knowledge_base/` 中的路径和引用规则。
- 预览与正式提取如何共用素材单元、结构化产物和证据引用。
- 模型能力、预算口径、prompt、失败反馈、洞察流事件和 UI 状态。
- 真实素材验收、离线结构验证和用户数据安全规则。

## 3. 不做范围

- 不重新做路线 02 的架构重构。若路线 02 没有准备好通用扫描、素材单元、运行计划和模型能力分派，本阶段应先回补 02，而不是在 03 中绕过架构直接接素材。
- 不引入大而全的插件系统、动态第三方扩展市场或复杂 registry。素材处理器仍以项目内稳定边界为主。
- 不实现实时语音对话、语音生成、麦克风流式输入或语音角色扮演。
- 不把音频理解模型的自由回答当作逐字 transcript。正式对白事实优先来自 ASR/STT 转写。
- 不承诺所有模型供应商都支持图片、音频、视频音频联合理解或混合输入；能力必须逐 provider/schema/model 标记和验证。
- 不把抽帧图片模式描述成完整视频理解能力；抽帧默认没有音频信息。
- 不把预览产物默认作为正式知识库事实。
- 不让 GUI 层直接解析素材、拼接知识库路径或构建模型请求。
- 不绕过 `utils.ai_model_middleware` 直连模型后端。
- 不新增依赖，除非执行时证明没有标准库、现有工具或轻量实现可替代，并经用户确认。

## 4. 02 必须提前准备的事项

路线 02 不实现新媒体提取，但必须为路线 03 做足结构准备。否则 03 会被迫在素材接入阶段再次做大规模架构移动。

02 的目标结构图和交接说明必须包含下列准备项：

| 准备项 | 02 要交付的最低要求 | 03 如何使用 |
| --- | --- | --- |
| 素材类型 | `MaterialKind` 能表达 `text`、`subtitle`、`transcript`、`audio`、`image`、`manga`、`mixed` | 03 不再新增平行类型体系 |
| 提取单元 | `ExtractionUnit` 或等价结构不硬编码 `video_path`，能表达文本段、字幕段、音频片段、单图、漫画页组 | 03 为每种素材填充 unit handler |
| 来源引用 | `MaterialRef` 使用相对 `materials/` 的路径和必要时间/页码/区域信息 | 03 生成可追溯 evidence |
| 证据引用 | `EvidenceRef` 至少能表达路径、时间范围、页码、区域、文本范围 | 角色卡编译和质量评估可追溯 |
| 预算入口 | 运行计划能区分输入硬预算与各素材输出期望 | 03 接入视频/图片/音频/文本时不复用错误口径 |
| 模型能力 | 能按素材类型选择 text/image/audio/video 后端或返回可解释不支持 | 03 不在 UI 或处理器中硬编码 provider |
| 预览入口 | 预览能从通用素材单元采样，不只能收集视频 chunk | 文本、图片、漫画等可进入真实预览 |
| 正式入口 | full/clean/fast 能从通用运行计划读取素材单元 | 03 接入非视频正式提取 |
| 知识库落点 | chunk/episode/season/transcript 写入接口不绑定视频命名 | 03 写入统一知识库 |
| 失败反馈 | handler 能返回素材类型、来源路径、失败原因和是否可跳过 | UI/洞察流能解释某类素材不可用 |

执行路线 03 前必须检查这张矩阵。如果任意准备项缺失，应先开 02 补充阶段，不能直接在 03 里绕开通用边界。

## 5. 当前事实与差距

### 5.1 已有事实

- `utils.media_types` 已有 `VIDEO_SUFFIXES`、`IMAGE_SUFFIXES`、`TEXT_SUFFIXES`，`SUPPORTED_SOURCE_SUFFIXES` 当前覆盖视频、图片和文本。
- 音频后缀目前主要在 `utils.audio_transcription.AUDIO_SUFFIXES` 中定义，还没有进入通用素材导入后缀集合。
- `utils.source_importer` 和 `utils.source_status` 已围绕 `SUPPORTED_SOURCE_SUFFIXES` 处理 raw/materials 的导入、展示和状态。
- `utils.cloud_model_presets` 已有 text/image/video/audio backend 概念，以及 `audio_transcription`、`audio_understanding`、`video_audio_understanding` 等能力标记。
- `utils.ai_model_middleware` 是统一模型调用入口，现有视频和模型页测试能力不得被 GUI 绕过。
- `utils.audio_transcription` 可以从视频或音频素材生成 `EpisodeTranscript` 并保存 `episode_transcript.json`。
- `core.source_scanner` 的正式扫描和预览扫描仍以视频为核心。
- `core.extractor` 的预览和正式提取主入口仍以视频 chunk、视频输入模式和视频预算为主。
- `core.models.ExtractionStructuredArtifact`、`ChunkExtractionResult` 已有 `source_kind`、`source_counts`、`context_policy`、`token_usage`、`requested_output_tokens` 等可复用字段。
- `docs/plans/preview-real-result-ingestion-plan.zh_CN.md` 已保留文本、字幕、音频转写、图片、漫画进入预览和统一知识库消费路径的后续方向。

### 5.2 主要差距

- 文本、字幕、图片、漫画没有稳定的正式提取单元映射。
- 音频素材导入、音频转写、原生音频理解和视频内音频理解容易混在一起，需要明确能力层次。
- 预览入口当前最多处理前 2 个视频 chunk，不能从文本、字幕、图片或漫画生成 preview chunk。
- 正式提取入口仍从正式视频扫描计划开始。
- 知识库证据引用还不足以表达页码、图像区域、字幕时间轴、音频时间段和混合素材来源。
- 预算与模型能力分派仍容易受视频每分钟语义影响。
- UI 尚未清楚区分“素材已导入”“素材已处理”“素材可提取”“模型不支持该素材类型”等状态。

## 6. 素材类型定义

### 6.1 文本

文本素材包括 `.txt`、`.md` 和被明确声明为文本资料的 `.json`。

处理目标：

- 按章节、段落或固定 token/字符预算切分为文本单元。
- 保留源文件路径、标题、段落范围、字符范围和可选章节名。
- 通过文本模型生成与视频 chunk 一致语义的角色事实、关系、事件、冲突和不确定项。

注意：

- `.json` 不能无条件当作可信结构化知识库事实；默认先作为文本资料或受控导入格式处理。
- 文本原文可能很长，必须受输入预算硬约束。
- 输出 token 不得使用视频每分钟、图片每张或音频每分钟口径。

### 6.2 字幕

字幕素材包括 `.srt`、`.ass`、`.vtt`。

处理目标：

- 解析为带时间戳的字幕段。
- 与视频 episode 或独立 episode 对齐。
- 可作为 transcript 类文本证据进入知识库。
- 在存在视频时，可作为视频素材的补充上下文；在无视频时，也可独立形成文本提取单元。

注意：

- 字幕不是普通纯文本。证据引用应保留时间范围和原始字幕行号。
- 字幕不保证说话人准确；不得凭格式猜测角色身份。
- 如果字幕与视频时长或 episode 对齐失败，应给出明确 warning，而不是静默忽略。

### 6.3 音频转写

音频转写指 ASR/STT 生成 transcript。当前优先路径是本地 `whisper.cpp`，可从视频音轨或音频文件生成 `EpisodeTranscript`。

处理目标：

- 把对白、旁白、可听文本沉淀为可追溯 transcript。
- 优先以 episode 级 `episode_transcript.json` 作为知识库落点。
- chunk 级只保存引用、时间范围或截取结果，不重复保存完整 transcript。

注意：

- Whisper 缺失不应阻塞不需要转写的素材流程。
- 音频转写失败要能让用户选择安装、跳过音频、切换为不需要 transcript 的模式，或停止运行。
- 日志不得记录完整转写文本。

### 6.4 原生音频理解

原生音频理解指模型直接接收音频，输出听觉摘要或结构化听觉线索。

处理目标：

- 补充语气、情绪、环境声、音乐、画外声音等 transcript 难以表达的信息。
- 作为独立 evidence 或 insight 进入知识库，而不是替代 transcript。

注意：

- 模型页音频测试通过不等于正式提取音频能力已接入。
- 原生音频输入必须按 provider/schema 走 `utils.ai_model_middleware`，UI 不拼请求体。
- 不支持音频的模型应返回可解释状态，不应把整次提取伪装成普通失败。

### 6.5 图片

图片素材包括单张图片、截图、插画和图片序列。

处理目标：

- 单图可成为一个 `image` unit。
- 图片序列可按目录、文件名排序或用户选择映射到 episode/unit。
- 模型请求应使用 image backend 或支持图片的多模态后端。
- 证据引用至少保存源路径和页/序号；后续可扩展图像区域。

注意：

- GIF 首版可按静态图片或拒绝处理，不默认做动画理解。
- 图片可能很大，需有尺寸、格式和失败原因反馈。
- 图片提取输出期望使用“期望图片输出 Token / 张”的软性口径。

### 6.6 漫画

漫画素材通常是有顺序的图片集合，可能按章节、页、跨页或目录组织。

处理目标：

- 目录映射为 season/episode，图片映射为页或页组 unit。
- 保留页码、文件名排序、可选章节标题和页组关系。
- 首版优先使用视觉模型理解画面与文字，不强制引入 OCR 新依赖。
- 需要支持漫画文件夹与普通图片文件夹的区分或用户选择。

注意：

- 漫画页组不能只写“来自漫画”，必须有页码或文件路径证据。
- 读图顺序可能影响剧情理解，应允许后续校正排序规则。
- 大批量漫画页费用高，必须有 preview 限制、正式批处理进度和预算反馈。

### 6.7 混合媒体

混合媒体指同一项目、season 或 episode 下存在多种素材类型，例如视频 + 字幕 + 漫画页 + 文本设定。

处理目标：

- 用统一运行计划表达一个 episode 中多个 material kinds。
- 同一事实可以有多个 evidence refs。
- 处理顺序应可解释：先准备派生素材，再提取单元，再聚合 episode/season。
- 冲突需要进入 `conflicts`、`open_questions` 或等价结构，不得静默覆盖。

注意：

- 混合媒体不等于把所有素材塞进同一次模型请求。
- 若模型不支持混合输入，应拆成多个单元提取后在文本聚合阶段合并。
- 混合媒体的费用和上下文风险高，必须有用户可见进度和跳过策略。

## 7. 数据与知识库规则

### 7.1 路径规则

保持现有项目根目录语义：

- `raw/` 保存可重新处理的源副本。
- `materials/` 保存当前处理管线实际消费的素材。
- `cache/` 保存临时处理、转码、转写和派生缓存。
- `knowledge_base/` 保存正式与预览结构化知识。
- `output/` 保存导出产物。

新增素材类型不得把用户素材写入 `res/`，不得把本地用户素材提交进仓库。

### 7.2 manifest 规则

路线 03 应复用路线 02 的通用 manifest 或 normalize 结果。

manifest 至少应能表达：

- `schema_version`
- `material_kinds`
- `source_root`
- season / episode / unit
- unit 的 `material_kind`、`unit_kind`、`source_path`
- 时间范围、页码、图片区域、文本范围等可选 evidence metadata
- 派生素材关系，例如 transcript 派生自视频或音频

旧视频 manifest 必须继续可读。

### 7.3 提取产物规则

优先复用现有产物路径：

- `seasons/{season_id}/episodes/{episode_id}/chunks/{unit_id}.json`
- `episode_content.json`
- `episode_summary.json`
- `season_content.json`
- `season_summary.json`
- `episode_transcript.json`

新增字段应优先落在已有结构中：

- `source_kind` 或后续 `material_kind`
- `source_counts`
- `context_policy`
- `aggregation_warnings`
- `model_profile_id`
- `model_metadata`
- `token_usage`
- `estimated_context_tokens`
- `requested_output_tokens`
- evidence refs

如果 `ChunkExtractionResult` 不足以表达图片、漫画或字幕证据，应先做兼容扩展，不应新增一套完全不同的知识库事实格式。

### 7.4 证据引用规则

证据引用必须能让用户和后续角色卡编译追溯来源。

建议最小字段：

| 素材类型 | 最小证据 |
| --- | --- |
| 文本 | 文件相对路径、章节或段落、字符范围 |
| 字幕 | 文件相对路径、字幕行号、开始/结束时间 |
| transcript | `episode_transcript.json` 路径、segment index、开始/结束时间 |
| 音频理解 | 音频相对路径、开始/结束时间、模型能力 |
| 图片 | 图片相对路径、序号、可选区域 |
| 漫画 | 章节/episode、页码、图片相对路径、可选区域 |
| 混合媒体 | 多个 evidence refs 的集合和冲突说明 |

## 8. 预算与模型能力

### 8.1 预算原则

- 输入/上下文窗口 Token 是硬约束。
- 输出 token 是软性期望，通过 prompt 或请求参数向模型表达，不保证模型严格遵守。
- 视频使用“期望视频输出 Token / 分钟”。
- 图片和漫画单页使用“期望图片输出 Token / 张”。
- 音频理解或音频摘要使用“期望音频输出 Token / 分钟”。
- 角色卡编译使用“期望角色卡编译输出 Token”。
- 文本、字幕和 transcript 的输出期望不得偷偷复用视频、图片或音频口径。

### 8.2 文本输出期望待确认

路线 01 已定义输入预算、视频输出期望、图片输出期望、音频输出期望和角色卡编译输出期望，但没有单独定义“期望文本输出 Token / 块”。

路线 03 执行前必须二选一：

- 方案 A：新增文本/字幕/转写提取的软性输出期望设置，并同步 i18n、默认值、规整 helper 和提示说明。
- 方案 B：不新增 UI 设置，内部按文本 chunk 大小和统一默认值计算输出期望，并在设置说明中明确文本类提取暂不提供独立用户配置。

无论选哪种方案，都不能把视频每分钟预算用于文本输入或文本输出。

### 8.3 模型能力分层

必须区分：

- `text`：处理文本、字幕、transcript、聚合、摘要。
- `image`：处理图片、漫画页、抽帧图片。
- `video`：处理原生视频或视频抽帧包装。
- `audio_transcription`：把音频转成 transcript。
- `audio_understanding`：理解音频中的非逐字听觉线索。
- `video_audio_understanding`：模型能同时理解视频画面和音轨。

模型能力不足时，应返回可解释状态。例如“当前模型不支持图片输入”“当前 API 不支持音频输入”“缺少 Whisper 运行时”“字幕解析失败”。

## 9. UI 与用户工作流

### 9.1 项目页

项目页需要支持用户导入更多素材类型，但仍只负责触发和反馈。

要求：

- 文件选择和文件夹导入应允许路线 03 支持的后缀。
- 素材列表应能显示素材类型、处理状态、是否可提取、是否需要额外工具。
- 处理按钮应能解释：复制/链接原素材、视频转码、音频转写、文本解析、图片/漫画索引。
- 清理 raw 的安全规则不变。
- 页面层不解析字幕、不转写音频、不写知识库。

### 9.2 模型页

模型页需要帮助用户理解当前模型可处理哪些素材。

要求：

- 文本、图片、音频、视频测试结果不应互相伪装。
- 音频测试仍是原生音频理解冒烟测试，不等于 Whisper/STT 转写测试。
- 不支持的素材能力显示为“模型不支持”或“API 不支持”，而不是普通失败。
- 需要 transcript 的流程应提示 Whisper 状态或可用转写后端。

### 9.3 洞察流

洞察流只展示用户关心的结构化事件。

要求：

- 事件 meta 包含 `material_kind`、`unit_id`、`source_path`、`stage`。
- 不输出完整原文、完整 transcript、API Key 或大型素材内容。
- 跳过、失败、模型拒绝、预算截断和证据缺失应能区分。

## 10. Prompt 与结构化输出

新增素材类型需要独立 prompt surface 或清晰变量分支。

建议新增或扩展的目的：

- `preview_text_unit_extraction`
- `formal_text_unit_extraction`
- `preview_image_unit_extraction`
- `formal_image_unit_extraction`
- `formal_transcript_unit_extraction`
- `formal_audio_insight_extraction`
- `formal_manga_page_extraction`
- `formal_mixed_episode_merge`

输出结构应尽量与视频 chunk 保持一致：

- `facts`
- `behavior_traits`
- `dialogue_style`
- `relationship_interactions`
- `conflicts`
- `open_questions`
- `evidence`
- `quality_warnings`

Prompt 必须强调：

- 不臆造角色名和关系。
- 证据不足时写不确定项。
- 图片和漫画不能凭单页推断整个剧情。
- 音频理解不能替代逐字转写。
- 字幕说话人未知时不得强行归属。

## 11. 里程碑

### M01：执行前闸门与 02 就绪矩阵复核

目标：确认 02 已经为 03 准备好结构边界。

范围：

- 检查路线 02 当前结构图、目标结构图和用户审核记录。
- 检查 02 多素材接入准备矩阵是否完整。
- 检查当前代码与 02 交接文档是否一致。

交付物：

- 03 执行前复核记录。
- 缺失准备项清单。
- 是否允许进入 03 代码实现的结论。

验收：

- 缺失项为零，或已明确先回补 02。
- 用户确认可以按 03 继续。

### M02：素材类型与后缀支持矩阵

目标：明确哪些素材可以导入、可以处理、可以预览、可以正式提取。

范围：

- 更新或规划 `utils.media_types` 中的视频、图片、文本、字幕、音频、漫画相关后缀。
- 明确 `.json`、`.gif`、漫画压缩包、未知扩展名的处理策略。
- 明确文件夹导入中图片序列、漫画目录、混合目录的识别规则。

验收：

- 支持矩阵能区分导入、预览、正式提取、需要额外工具、暂不支持。
- UI 文案不承诺未实现能力。

### M03：通用素材扫描与 unit 映射落地

目标：从 `materials/` 生成多素材 unit。

范围：

- 文本文件映射为文本 unit。
- 字幕映射为字幕 unit 或 transcript-like unit。
- 音频映射为 transcript 生成任务或音频理解 unit。
- 图片映射为 image unit。
- 漫画目录映射为 manga page/page group unit。
- 混合目录映射为一个 episode 下的多 kind unit 集合。

验收：

- 不同素材都能进入同一运行计划。
- 旧视频扫描兼容。
- unit 有稳定排序、来源路径和 evidence metadata。

### M04：文本素材解析与 chunking

目标：让纯文本进入预览和正式提取。

范围：

- 读取 `.txt`、`.md` 和受控 `.json`。
- 按输入预算切分文本 chunk。
- 建立文本 evidence。
- 调用 text backend 生成结构化结果。

验收：

- 无视频但有文本素材时，预览能生成 preview chunk。
- 正式提取能写入 full chunk、episode content 和 summary。
- 超长文本会截断或分块并给出 warning。

### M05：字幕接入

目标：让字幕成为可追溯文本素材。

范围：

- 解析 `.srt`、`.ass`、`.vtt`。
- 保留时间轴、行号和原始文本。
- 能与视频 episode 关联，也能独立形成文本提取单元。

验收：

- 字幕预览和正式提取可运行。
- 证据引用包含时间范围。
- 说话人未知时不会强行归属。

### M06：音频转写作为正式素材入口

目标：把音频或视频音轨转写结果作为知识库事实来源。

范围：

- 支持音频文件进入素材导入和转写任务。
- 复用 `utils.audio_transcription` 写入 `episode_transcript.json`。
- 从 transcript 构建提取 unit。
- 转写失败给出可解释反馈。

验收：

- 音频文件可生成 transcript。
- transcript 可进入预览和正式提取。
- Whisper 缺失只影响需要转写的流程。

### M07：原生音频理解接入

目标：补充 transcript 不覆盖的听觉线索。

范围：

- 按模型能力判断是否可直接音频输入。
- 构建音频理解请求。
- 保存听觉摘要、语气、环境声等 evidence。

验收：

- 支持音频的模型可返回结构化听觉线索。
- 不支持音频的模型有明确状态。
- 音频理解不覆盖 transcript 事实。

### M08：图片素材接入

目标：让单图和图片序列进入预览和正式提取。

范围：

- 图片 unit 构建。
- image backend 请求。
- 图片证据路径、序号和可选区域。
- 图片输出期望使用“每张”软性口径。

验收：

- 无视频但有图片时，预览可生成 preview chunk。
- 正式提取可写 full chunk。
- 图片过大、格式不支持或模型不支持时反馈明确。

### M09：漫画素材接入

目标：让漫画目录或页组进入知识库。

范围：

- 漫画目录识别与排序。
- 页、页组、章节和 episode 映射。
- 漫画页视觉提取。
- 页组聚合为 episode content。

验收：

- 漫画文件夹可生成稳定 units。
- 证据引用包含页码或文件名。
- 预览限制成本，正式提取显示批处理进度。

### M10：混合媒体 episode 编排

目标：同一 episode 中多种素材可协同提取。

范围：

- 先准备派生素材，如 transcript。
- 分素材提取 unit。
- 聚合同一 episode 的多个来源。
- 处理冲突、重复事实和证据合并。

验收：

- 视频 + 字幕、图片 + 文本、漫画 + 文本等组合可表达。
- 聚合结果保留多证据来源。
- 冲突不被静默覆盖。

### M11：预览链路多素材化

目标：预览不再只依赖视频 chunk。

范围：

- 从通用 unit 中采样预览素材。
- 保持 preview artifact 隔离。
- 针对不同素材类型显示合适进度和 warning。

验收：

- 没有视频时，文本、字幕、图片或漫画仍能预览。
- 预览不消费正式产物。
- 预览产物不进入正式角色卡编译。

### M12：正式提取多素材化

目标：正式 full/clean/fast 能消费多素材 unit。

范围：

- full 路径按素材单元提取并聚合。
- clean 路径遵守正式产物重建语义。
- fast 路径只在素材处理器支持并发时启用。
- 不支持并发的素材类型回退为串行并说明。

验收：

- 视频旧路径不回退。
- 文本、字幕、transcript、图片至少有正式提取路径。
- 漫画和混合媒体按本阶段完成范围通过验收。

### M13：知识库证据与角色卡消费

目标：让角色卡编译能消费多素材正式知识库。

范围：

- 统一 `source_kind`、`material_kind`、`source_counts` 和 evidence。
- 角色卡编译不回头分析原始素材。
- 质量评估可识别不同素材证据的可靠性。

验收：

- 角色卡编译能从多素材知识库读到事实。
- evidence 不丢失素材类型和来源。
- 旧视频项目仍可编译。

### M14：模型拒绝与失败样例记录适配

目标：让多素材失败和模型拒绝能进入 01 设计的拒绝样例流程。

范围：

- 失败记录包含 `material_kind`、unit、source path、模型、prompt purpose、错误类型。
- 用户打包拒绝样例时，能复制相关素材和 JSON。
- 大型素材按索引引用或受控复制，不泄露无关项目文件。

验收：

- 图片、音频、文本、漫画失败都能生成可回传的结构化记录。
- 记录不包含 API Key 或完整隐私文本。

### M15：GUI 与 i18n

目标：让用户看得懂多素材状态。

范围：

- 素材类型显示。
- 处理状态和失败反馈。
- 模型能力不支持提示。
- 预算设置说明。
- 四个 i18n JSON 同步。

验收：

- UI 不把未支持素材显示为可正式提取。
- 所有新增文案走 i18n。
- 长耗时任务仍在 worker/thread。

### M16：离线验证与测试素材

目标：补足不依赖云端模型的结构验证。

范围：

- 扫描和 unit 映射测试。
- 文本 chunking 测试。
- 字幕解析测试。
- transcript 读取测试。
- 图片/漫画排序测试。
- manifest 兼容测试。

验收：

- 不需要真实模型即可验证核心结构。
- 固定测试素材来源记录在 `docs/reference/asset-material-declaration.zh_CN.md`。

### M17：真实模型和手动验收

目标：用真实素材确认多素材链路可用。

范围：

- 文本项目。
- 字幕项目。
- 音频转写项目。
- 图片项目。
- 漫画目录。
- 至少一个混合媒体项目。

验收：

- 预览和正式提取都能运行。
- 知识库产物可检查。
- 角色卡编译能消费正式知识库。
- 失败场景能解释原因。

### M18：文档、架构和收尾

目标：把新事实沉淀到普通项目文档。

范围：

- 更新相关 `ARCHITECTURE.md`。
- 更新 `docs/reference/extraction-workflow.zh_CN.md`。
- 更新 TODO 状态。
- 如形成长期规则，建议是否更新 `AGENTS.md`，但不得擅自修改。

验收：

- 后续 agent 不依赖 `.codex/` 即可理解多素材链路。
- 03 偏差、未完成项和后续扩展清楚。

## 12. 推荐提交分组

- `docs: finalize multi-material coverage plan`
  - 正式化 03 计划并同步索引链接。
- `docs: record multi-material readiness from refactor`
  - 记录 02 交接矩阵和 03 执行前复核结论。
- `refactor: support material kind suffix metadata`
  - 扩展素材后缀、类型识别和导入状态。
- `feat: scan multi-material extraction units`
  - 将文本、字幕、音频、图片、漫画映射为通用 unit。
- `feat: extract text and subtitle materials`
  - 文本和字幕进入预览/正式提取。
- `feat: extract transcript material insights`
  - 音频转写作为正式素材入口。
- `feat: extract image material insights`
  - 单图和图片序列进入知识库。
- `feat: extract manga page insights`
  - 漫画页组进入知识库。
- `feat: merge mixed material episodes`
  - 混合媒体 episode 聚合和冲突处理。
- `feat: surface multi-material extraction status`
  - UI、洞察流和 i18n 状态反馈。
- `test: cover multi-material extraction planning`
  - 离线结构测试和 fixture。
- `docs: document multi-material extraction workflow`
  - 更新架构、工作流和验收说明。

## 13. 验证策略

### 13.1 静态验证

可用时运行：

```powershell
conda run -n CharaPicker python -m ruff check .
```

如果 Ruff 未安装，阶段报告中说明。

### 13.2 离线验证

至少覆盖：

- 各素材后缀识别。
- 文件夹导入和 raw/materials 映射。
- manifest normalize。
- unit 排序和 evidence。
- 文本 chunking。
- 字幕解析。
- transcript 缓存读取。
- 图片/漫画排序。
- preview/full artifact 隔离。

### 13.3 手动验收

至少准备：

- 一个纯文本项目。
- 一个字幕项目。
- 一个音频或视频音轨转写项目。
- 一个单图项目。
- 一个漫画目录项目。
- 一个混合媒体项目。
- 一个模型不支持目标素材的失败项目。

## 14. 风险与缓解

| 风险 | 表现 | 缓解 |
| --- | --- | --- |
| 02 准备不足 | 03 又开始移动架构 | 先回补 02 就绪矩阵 |
| 模型能力误判 | UI 显示可用但请求失败 | provider/schema/model 分层标记 |
| 预算口径混乱 | 文本误用视频每分钟 | 按素材类型分派预算 |
| 音频概念混淆 | 音频理解替代 transcript | ASR 与音频理解分开 |
| 漫画费用过高 | 大量页面一次性发送 | 页组、采样、进度和预算提示 |
| 证据不可追溯 | 角色卡事实找不到来源 | EvidenceRef 强制路径/时间/页码 |
| 预览污染正式 | preview 产物被正式编译消费 | 继续使用 preview stage 和前缀隔离 |
| UI 越界 | 页面直接解析素材或调模型 | worker/core/utils 边界审查 |
| 隐私泄露 | 日志记录原文或 transcript | 只记录摘要和路径，不记录完整内容 |

## 15. 执行时待确认事项

- 文本类输出期望是否新增用户设置，还是先使用内部默认值。
- 字幕支持首批是否只做 `.srt`，还是同时做 `.ass`、`.vtt`。
- GIF 首版是按静态图处理、拆帧处理，还是提示暂不支持。
- 漫画目录识别是否需要用户手动标记“这是漫画”。
- 漫画页组大小如何默认设置。
- 原生音频理解首批是否只接已有 provider 能力，还是先仅保留能力判断。
- 混合媒体正式提取首批支持哪些组合。
- 是否需要新增受控测试素材；如果新增，必须同步素材来源声明。

## 16. 代码审查自检表

执行 03 的每个阶段提交前，至少自查：

- 是否已经确认 02 的结构图和多素材接入准备矩阵通过用户审核。
- 是否绕过了路线 02 的通用素材单元、运行计划或模型能力分派。
- 是否新增了 UI 直接解析素材、写知识库或拼模型请求的行为。
- 是否绕过 `utils.ai_model_middleware`。
- 是否把音频理解当作 transcript。
- 是否把预览产物当正式知识库事实。
- 是否把视频每分钟预算用于文本、图片或音频之外的场景。
- 是否为新增素材类型提供了可追溯 evidence。
- 是否有新增用户可见文案未同步四个 i18n JSON。
- 是否有日志输出完整原文、完整 transcript、API Key 或隐私内容。
- 是否保持旧视频项目可用。
- 是否把测试素材来源写入素材声明。

## 17. 完成定义

路线 03 完成后，应满足：

- 文本、字幕、音频转写、图片、漫画和至少一种混合媒体组合可以进入预览。
- 文本、字幕、transcript、图片至少可以进入正式提取并写入知识库。
- 漫画素材具备稳定 unit 映射、证据引用和至少首版正式提取路径。
- 音频理解能力与音频转写能力分层明确。
- 角色卡编译能消费多素材正式知识库。
- 模型不支持或工具缺失时，用户能看到明确反馈。
- 旧视频预览、正式提取和角色卡编译不回退。
- 架构文档、工作流文档和 TODO 状态已同步。
