# 正式素材详细提取流程与模式计划（zh_CN）

归档日期：2026-06-04。剩余待办已迁入 `docs/plans/TODO.zh_CN.md`。

最近核对日期：2026-06-04。

计划阶段：阶段性完成。M01-M22 主线已在 `formal-extraction-plan` 分支落地，并经过手动试跑、日志复核、角色卡编译回归和基础静态验证。

可用性：本文现在作为本轮正式提取模式与上下文实现的阶段性记录。当前行为仍以 `core/extractor.py`、`core/extraction_context.py`、`core/extraction_budget.py`、`core/models.py`、`gui/main_window.py`、`gui/pages/project_page.py`、`core/character_card_compiler.py`、`res/default_prompts.json` 和四个 `i18n/*.json` 为准。后续新工作应优先查看 `docs/plans/TODO.zh_CN.md`，不要把本文当作新的待执行主计划。

## 0. 阶段性完成摘要

已完成：

- 新增 `完整提取`、`洁净提取`、`快速提取` 三种正式入口；预览模式继续独立。
- 完整/洁净提取按 season -> episode -> chunk 串行推进，chunk 请求带同集已完成 chunk、当前季已完成 episode 和前序季背景。
- episode 结束后执行 AI 集级合并并生成 `episode_summary.json`；season 结束后执行 AI 季级合并并生成 `season_summary.json`。
- 快速提取支持用户确认并发数 1 到 500；chunk 阶段并发且不带上下文，随后并发重整理 episode，再重整理 season。
- 正式产物带 `extraction_run_id`、`extraction_stage`、`schema_version`、`context_policy`、`token_usage`、`requested_output_tokens` 等元数据；聚合只消费当前 run 中合格产物。
- 洁净提取清理可再生正式/预览中间产物，保留用户素材、导出结果和正式/预览角色卡母本。
- 新正式 run 成功写入后会把已编译正式角色卡标记为 stale。
- 供应商拒绝片段继续受“跳过拒绝片段”选项控制；跳过会写入 episode/season warnings。
- 角色卡编译已补充角色别名匹配和 AI 别名解析 fallback，避免中文名和知识库英文/罗马字候选不一致时直接失败。

后续专项状态：

- 角色卡编译上下文分层、AI 别名重分类、结构化复核原因和质量诊断基础实现已由 [角色卡质量后续执行计划完成记录](character-card-quality-followup-plan.completed.zh_CN.md) 接续完成；后续只保留真实素材分类边界和提示表现调优。
- 自动化回归仍不足，尤其是 run 过滤、clean 清理边界、上下文预算降级、JSON 重试、跳过片段聚合和 stale 标记。
- 日志隐私和体积仍需治理，避免模型请求/响应正文或临时素材 URL 在 DEBUG 日志中展开。
- 非视频素材、文本/字幕/转写、图片/漫画/混合媒体接入仍按 `TODO.zh_CN.md` 继续推进。

## 1. 目的与范围

本计划的重点是定义真正可执行、可追溯、上下文合理的正式素材提取流水线。提取模式只是入口差异，核心目标是让高质量流程符合 `Extract Once`：一次处理素材，逐层沉淀为可靠的 chunk、episode、season 知识库产物，后续角色卡编译只读取结构化知识库。

正式素材提取提供三种入口：

- `完整提取`：默认高质量正式提取。按季、集、chunk 严格线性串行推进，当前 chunk 提取时带入同集已完成 chunk 的结构化产物、当前季已完成集的信息，以及前序季度的长总结背景。
- `洁净提取`：先清理可再生提取中间产物，再执行与完整提取完全相同的线性上下文流程。
- `快速提取`：多请求并行提取 chunk，不带上下文；所有 chunk 完成后用 AI 并行重整理集，再用 AI 并行重整理季，用于速度优先和低成本试跑。

预览模式保持独立：继续最多处理前 2 个预览 chunk，写入 `preview__` 产物，不参与正式提取上下文。

## 2. 非目标

- 不改变 `raw/`、`materials/` 的导入和处理职责。
- 不删除用户素材、项目配置、导出结果或正式角色卡母本。
- 不绕过 `utils.ai_model_middleware` 直接调用模型后端。
- 不把 GUI 页面变成文件系统和 AI 推理的实现层。
- 不在快速提取中承诺设计文档要求的上下文连续性；快速提取是速度优先模式。

## 3. 已确认决策

- `完整提取` 和 `洁净提取` 必须执行同一套高质量正式提取流程。
- 高质量正式提取必须是线性的串行流程，不做 chunk 并行。
- 当前 chunk 提取必须按设计文档带上下文：当前 chunk 最高优先，同集已完成 chunk 的结构化产物其次，当前季已完成集的信息再次，前序季度长总结作为低优先级背景。
- 完成一集后必须执行 AI 合并：把本集 chunk 结构化产物发给模型，由 AI 生成集级完整内容，而不是只做本地数组拼接。
- 完成一集后必须生成可供后续集使用的集级摘要；摘要不能过短，必须保留主要人物、故事梗概、关系变化、冲突和待续线索。
- 完成一季后必须生成季级长总结；跨季上下文至少包含前一季，条件允许时包含更早季度的压缩长总结。
- 洁净提取必须删除 `preview__chunk_*.json` 等预览 chunk 中间产物，但保留 `preview_character_cards/`。
- 洁净提取清理完成后，现有正式角色卡必须标记为 stale，提示用户重新编译。按当前 `core.character_card_store.mark_card_stale()` 语义，只有已编译的正式卡从 `COMPILED` 变为 `STALE`；草稿卡和预览卡不应被改写。
- `FULL`、`CLEAN`、`FAST` 只要成功写入新的正式知识库 run 产物，就必须把已编译正式角色卡标记为 stale；如果 run 完全没有成功写入正式产物，则不因失败空跑改写角色卡状态。
- 供应商拒绝视频片段时，继续沿用现有“跳过拒绝片段”选项控制；允许跳过时必须在 episode/season 产物中标记缺失来源，不允许跳过时阻断对应正式流程。
- AI 输出 JSON 解析失败时，最多重试 3 次；3 次仍失败则报错，不写成功 artifact，不启用本地 concat fallback。
- 快速提取不带上下文，多请求并行，目标是速度优先；用户必须在确认窗中看到“提取偏差会很大”的提示。
- 快速提取由用户输入并发数，输入范围限制为 1 到 500。
- 快速提取不能停留在本地数组拼接。所有 chunk 提取完成后，必须再用 AI 多线程重整理集级内容，最后用 AI 多线程重整理季级内容。
- 快速提取的 episode/season AI 重整理允许使用部分成功输入；不额外弹确认窗，缺失来源通过洞察流、run 状态和 artifact warnings 暴露。如果某个 episode 没有任何成功 chunk，则跳过该 episode 重整理。
- episode AI 合并产物必须记录模型返回的输出 token，用作后续 episode 上下文成本参考；没有供应商 usage 时使用保守估算并标记。
- `episode merge`、`episode summary`、`season merge`、`season summary` 的输出 token 预算必须单独设计，不能复用“视频输出 Token / 分钟”的含义。
- 当前季已完成 episode 的历史上下文池上限采用 `128k tokens`；实际发送预算仍必须受模型上下文窗口、当前 chunk/transcript、prompt、输出预留和安全余量共同约束。
- 本轮新增可选 `context_window_tokens` 能力：模型 preset 可保存该值，应用可用内置模型能力表按 model id 推断；provider adapter 只有在供应商明确返回上下文窗口时才自动写入。三者都不可用时，使用保守默认预算。当前尚无独立 UI 手动输入入口。
- 第一版不做精确费用估算；只展示 token usage、预算警告、并发风险、跳过/失败数量和输出截断风险。
- episode 上下文选择不能按固定集数实现，必须按信息量、相关性、成本和可用预算动态选择。
- 本计划后续实施时，优先完成详细合理的高质量提取流程；模式 UI、并发输入和清理确认都服务于该流程，不反过来压缩提取质量。

## 4. 当前状态与目标状态

当前代码事实：

- `run_full_extraction_streaming()` 已按 `ProjectConfig.extraction_mode` 分流为 `FULL`、`CLEAN` 和 `FAST`。
- `FULL` 和 `CLEAN` 共享线性正式提取路径，按 manifest 中的 season、episode、chunk 顺序串行推进。
- chunk 提取通过 `formal_contextual_video_chunk_extraction` 发送当前 chunk、同集已完成 chunk、当前季已完成 episode 上下文和前序季背景；历史上下文只作为识别人物、关系和前因后果的背景。
- episode 完成后会通过 AI 生成 `episode_content.json`，再基于该内容生成 `episode_summary.json`。
- season 完成后会通过 AI 生成 `season_content.json`，再基于该内容生成 `season_summary.json`。
- `FAST` chunk 阶段并发且不带上下文；chunk 阶段完成后按 episode 并发执行 AI 重整理，再按 season 执行 AI 重整理。
- 正式知识库产物带 `extraction_run_id` 和 `extraction_stage = "full"`；episode/season 聚合只消费当前 run 中 schema 合格的 full artifact。
- `context_window_tokens` 已进入模型 preset 与预算路径，可由内置模型能力表推断或使用保守默认预算；当前没有独立 UI 手动输入入口。
- 洁净提取已接入可再生中间产物清理，保留 `raw/`、`materials/`、`output/`、正式角色卡母本和预览角色卡母本。
- 新正式 run 成功写入后，已编译正式角色卡会标记为 stale；失败空跑不会改写角色卡状态。
- 角色卡编译已支持角色卡身份字段中的 `aliases`、`original_names`、`romanized_names`，并在本地匹配失败时用 AI 从知识库 `targets` 候选中解析别名。

已达到的目标状态：

- 正式知识库产物带有当前 `extraction_run_id`，聚合只消费同一 run 的 full artifact。
- 完整提取按 manifest 顺序串行：season -> episode -> chunk。
- 每个 chunk 的模型输入包含明确分段的上下文和当前素材，不把低优先级背景伪装成当前证据。
- 每个 episode 结束后立即生成 AI 合并版 `episode_content.json` 和集级摘要。
- 每个 season 结束后生成 AI 合并版 `season_content.json` 和季级长总结。
- 洁净提取只清除可再生提取中间产物，再调用完整提取。
- 快速提取使用用户确认的有界并发，并通过分阶段 AI 重整理生成 episode 和 season 产物。

保留为后续专项的问题：

- 角色卡编译当前仍以直接命中角色名/别名的证据聚合为主；没有出现但解释角色行动动机的 episode 还没有独立的因果上下文通道。
- 角色状态编译中的 `targets` 仍承担门禁作用；后续应改为相关性信号，并把非直接命中 episode 作为压缩上下文进入角色卡 AI 复核。

## 5. 详细提取流程

### 5.1 流程总览

完整提取和洁净提取的高质量路径必须按下面的依赖顺序执行：

```text
准备提取 run
-> 扫描 materials 并生成 source_manifest
-> 初始化 season/episode/chunk 目录
-> 按需准备 episode transcript
-> season_001
   -> episode_001
      -> chunk_0001：只带当前素材和更高层背景
      -> chunk_0002：带 chunk_0001 的结构化产物
      -> ...
      -> AI 合并本集 episode_content
      -> AI 生成本集 episode_summary
   -> episode_002：带 episode_001 的完整信息或摘要
   -> ...
   -> AI 合并本季 season_content
   -> AI 生成本季 season_summary
-> season_002：带前序季度长总结背景
-> ...
-> 完成 run，记录统计、警告和可追溯来源
```

快速提取只改变 chunk 提取阶段：chunk 可并发且不带上下文；但 chunk 全部完成后，仍必须执行 AI 集级和季级重整理。

### 5.2 Run 准备阶段

执行入口必须先构造一个明确的 `ExtractionRunPlan` 概念，即使实现时不一定新增同名模型。它至少包含：

- `project_id`
- `extraction_run_id`
- `mode`
- `source_manifest`
- 排序后的 `season -> episode -> chunk` 列表
- 当前使用的模型预设、视频输入模式和 token 预算
- 是否需要 transcript，以及 transcript 准备状态
- 产物写入策略和上下文预算策略

准备阶段要求：

- `source_manifest.json` 必须记录当前 run id 和扫描到的素材层级。
- 所有 chunk 路径必须在 `materials/` 下解析，不能让外部路径进入知识库 run。
- 排序必须稳定：manifest 一旦生成，本次 run 后续流程都按 manifest 顺序走，不在中途重新扫描改变顺序。
- 如果视频模式需要 transcript，则先按 episode 准备 transcript。某集 transcript 失败时，应记录该集警告；如果当前视频输入模式必须依赖 transcript，才阻断对应 chunk。
- 洁净提取在 run 准备前先执行清理；快速提取在 run 准备后、发起 chunk 请求前弹并发确认窗。

### 5.3 Chunk 提取阶段

每个 chunk 的提取目标不是写“短总结”，而是写可供后续合并和角色编译使用的结构化观察结果。输出必须区分：

- 客观事实：发生了什么。
- 角色身份和称呼：谁出现了，如何被称呼。
- 行为和情绪：角色做了什么、呈现什么状态。
- 对白和语气：可追溯到 transcript 或画面听见的表达。
- 关系互动：角色之间的关系变化、误会、冲突、亲近或疏离。
- 冲突和悬念：本 chunk 中出现或延续的问题。
- 状态变化：角色的立场、目标、能力、处境、心理变化。
- 证据引用：至少能定位到 season/episode/chunk；如果有 transcript 或时间线，尽量带时间范围。
- 不确定点：模型不能确认的身份、事件或关系必须标注，不能补写。

完整/洁净模式中，当前 chunk 请求必须按优先级带上下文：

1. `CURRENT_CHUNK`：当前视频、帧采样和可选 transcript，是唯一最高优先级证据。
2. `CURRENT_EPISODE_EXTRACTED_CHUNKS`：同一集已经完成的 chunk 结构化产物，尽量完整传入。
3. `CURRENT_SEASON_COMPLETED_EPISODES`：当前季已完成集的信息，预算允许时传完整 `episode_content.json`，否则传 `episode_summary.json`。
4. `PREVIOUS_SEASON_BACKGROUNDS`：前序季度长总结，作为低优先级背景。

prompt 必须明确告诉模型：

- 当前 chunk 证据高于所有历史上下文。
- 历史上下文只帮助识别人物、关系和前因后果。
- 如果当前 chunk 和历史上下文冲突，输出要记录冲突或变化，不能用旧信息覆盖新观察。
- 不得从历史上下文中复制没有在当前 chunk 出现的新事实到当前 chunk 证据字段。

### 5.4 Episode AI 合并阶段

完成一个 episode 的所有 chunk 后，必须立即执行 AI 集级合并。集级合并不是简单 concat，它要把多个 chunk 产物重整理成“本集完整结构化内容”。

episode merge 输入：

- 本集所有成功 chunk 的完整结构化结果。
- 本集 source metadata，包括 season_id、episode_id、display_title、source_path、chunk 顺序。
- 本集可用 transcript metadata，不需要重复发送完整原始 transcript，除非后续实现决定让合并模型复核时间线。
- 当前季前面已完成集的信息，优先完整内容，超预算时用摘要。
- 前序季度长总结，低优先级背景。

episode merge 输出必须包含：

- `episode_outline`：本集故事梗概，不能短到丢失主要人物和事件。
- `characters`：本集出现或被明确提到的角色、别名、称呼和身份不确定性。
- `facts`：按事件组织的事实列表。
- `behavior_traits`：角色行为和稳定倾向，只基于本集证据。
- `dialogue_style`：角色说话方式、口癖、态度和证据。
- `relationship_interactions`：关系变化和互动证据。
- `conflicts`：冲突、悬念、误会和待续线索。
- `character_state_changes`：角色状态变化，保留“从什么变到什么”的方向。
- `evidence_refs`：能回溯到 chunk，必要时回溯到时间段。
- `uncertainties`：身份、动机、关系或事件不确定点。
- `chunk_refs` 或 `chunk_results`：保留来源引用，方便后续角色卡追溯。

episode merge 成功后再生成 `episode_summary.json`。集级摘要面向后续提取上下文，不是 UI 的一句话摘要，必须保留：

- 本集主要人物。
- 本集故事梗概。
- 关键关系变化。
- 角色状态变化。
- 未解决冲突。
- 需要后续集继续确认的不确定点。
- 用于后续上下文选择的 metadata，例如 `important_characters`、`open_threads`、`continuity_hooks`、`importance_score`、`context_brief` 和 `context_long`。

### 5.5 Season AI 合并阶段

完成一个 season 的所有 episode 后，必须执行 AI 季级合并和季级长总结。

season merge 输入：

- 当前季所有 `episode_content.json`。
- 当前季所有 `episode_summary.json`。
- 前序季度长总结，作为低优先级背景，用于理解连续性。

season merge 输出必须包含：

- `season_outline`：本季完整故事梗概。
- `major_characters`：本季主要角色、身份、别名和角色定位。
- `character_arcs`：主要角色阶段性成长、退化、转变、伪装或误解。
- `relationship_map`：主要关系、关系变化和证据来源。
- `major_events`：本季关键事件。
- `unresolved_threads`：延续到后续季度的冲突、悬念和不确定点。
- `world_context`：后续角色卡需要知道的世界观、组织、地点或规则。
- `episode_refs`：来源集引用。

`season_summary.json` 是跨季上下文的核心产物，必须是长总结而不是短摘要。它要让下一季在不重读所有 episode 的情况下，仍能知道：

- 这季讲了什么。
- 谁是主要角色。
- 角色之间是什么关系。
- 每个主要角色到季末处在什么状态。
- 哪些冲突和悬念还没解决。
- 哪些信息仍不确定或需要人工复核。

### 5.6 上下文预算与降级策略

实现时必须有统一的上下文预算 helper，不能在各个请求里临时截断字符串。目标是“尽量多带有效信息，但不让历史上下文吞掉当前 chunk 和输出空间”。

预算 helper 至少需要维护这些概念：

- `current_evidence_reserved_budget`：为当前 chunk、transcript、prompt 固定说明和输出预留空间。
- `history_context_budget`：本次请求最多允许历史上下文使用的估算 token 或估算字符预算。
- `safety_margin`：为供应商 token 估算误差和 JSON 输出保留的安全余量。
- `context_policy`：实际采用了完整信息、长摘要、短摘要或裁剪的记录。

当前仓库已有可选 `context_window_tokens` preset 字段和内置模型能力表推断。该值用于计算输入上下文和输出预留的总窗口，不等同于输出 token 上限。估算必须保守，尤其是中文、日文和 JSON 字段名不能按过低 token 成本估算。当前尚无独立 UI 手动输入入口。

上下文选择按“近、强、够”三条原则：

- `近`：时间越接近当前 chunk 的 episode，越优先带完整信息。
- `强`：与当前 episode 已识别人物、冲突、地点、组织、关系线索越相关，越优先带完整信息。
- `够`：只有在放入后仍不挤占当前 chunk 和输出预算时，才带完整信息；否则降级为长摘要或短摘要。

同集已完成 chunk 的策略：

- 默认尽量带完整结构化结果，因为同集 chunk 对当前理解价值最高。
- 如果同集已完成 chunk 过多，保留最近若干 chunk 的完整结构；更早 chunk 先合成为 `episode_rolling_context`，再作为同集背景传入。
- 同集上下文不得只剩一句短摘要；至少要保留人物、关系、冲突和状态变化。

当前季已完成 episode 的策略：

- `上一集` 默认优先尝试带完整 episode context view。
- `更早 episode` 默认带 `episode_summary.context_long`，除非预算非常充裕，或被判定与当前 episode 强相关。
- 如果当前 episode 的已完成 chunk 已经识别出人物、关系或冲突，则后续 chunk 可以据此从更早 episode 中挑选强相关 episode，优先带完整 context view。
- 如果当前 episode 还没有任何已完成 chunk，例如本集第一个 chunk，则只能按时间接近度、上一集未解决线索、season rolling context 来选择历史信息。
- 如果放入某集完整信息会导致历史上下文超过预算，则该集降级为 `context_long`；仍超预算时再降级为 `context_brief`。

这里的“完整 episode 信息”不是把 `episode_content.json` 中所有原始 `chunk_results` 无限制塞进请求。它应优先使用 episode AI 合并后的完整结构化字段，并保留 chunk 引用；只有在预算允许且确实需要复核细节时，才附带相关 chunk 的精简 evidence。

不要把“带多少集完整信息”实现成固定集数。推荐实现为按信息量和相关性动态选择：

- 主轴按估算 token 或估算字符成本，而不是按集数。每个 episode 都计算 `full_cost`、`context_long_cost`、`context_brief_cost`。
- 时间长度只能作为前置估算或排序参考；真正进入上下文时，优先看结构化产物的信息量和 token 成本。因为一集可能很长但角色信息很少，也可能很短但关系变化密集。
- 对每个已完成 episode 计算 `context_value`，来源包括时间接近度、`important_characters` 重叠、`open_threads` 重叠、`continuity_hooks` 命中、`importance_score` 和是否为上一集。
- 选择时按性价比排序：优先放入上一集完整 context view；再放入与当前人物/冲突强相关且成本可接受的 episode 完整 context view；剩余 episode 用 `context_long` 或 `context_brief` 覆盖。
- 无论完整 episode 放入多少集，都必须保留一个覆盖全部已完成集的 `season_rolling_context`，避免早期集完全失忆。

相关性和成本必须可解释地计算，不依赖固定集数：

候选 episode 需要从 `episode_content.json` 和 `episode_summary.json` 生成一个 `context_candidate`：

- `episode_id`、`season_id`、时间顺序和距当前 episode 的距离。
- `important_characters`、别名和称呼。
- `relationship_edges`，例如 `A -> B: 冲突/亲近/误会/保护`。
- `open_threads` 和 `continuity_hooks`，例如未解决冲突、伏笔、目标、承诺、误会。
- `locations`、`organizations`、关键物品和世界观术语。
- `importance_score`，由 episode summary 生成或本地估算，表示该集对后续理解的重要程度。
- 三种可传入视图：`full_context_view`、`context_long`、`context_brief`。

当前请求也要构造 `current_signals`：

- 当前 episode 第一个 chunk：可用信号较少，只使用 episode 顺序、上一集未解决线索、当前季 rolling context、前一季长总结和素材标题。
- 当前 episode 后续 chunk：从已完成 chunk 中提取当前已出现角色、别名、关系、冲突、地点、组织、关键词和不确定点。
- 如果当前 chunk 输出暂时没有角色名，只按时间接近度和未解决线索选上下文，不为了“凑相关性”臆测角色。

初始相关性评分建议用可调权重，不写死在 prompt 中：

```text
relevance =
  0.25 * recency_score
+ 0.30 * character_overlap_score
+ 0.20 * thread_overlap_score
+ 0.10 * relationship_overlap_score
+ 0.05 * location_or_org_overlap_score
+ 0.10 * importance_score
+ previous_episode_bonus
- resolved_or_duplicate_penalty
```

评分说明：

- `recency_score` 随 episode 距离衰减；上一集有额外 bonus。
- `character_overlap_score` 使用角色名、别名、称呼做归一化匹配；精确角色名高于模糊称呼。
- `thread_overlap_score` 看当前线索是否命中候选集的未解决冲突、伏笔、目标或承诺。
- `relationship_overlap_score` 看当前出现的人物对或关系边是否在候选集中出现过。
- `location_or_org_overlap_score` 只作为弱信号，避免地点相同但剧情无关时误判。
- `importance_score` 防止关键转折集因为距离较远被过早降级。
- `resolved_or_duplicate_penalty` 用于已经明确完结、且和当前线索无关的旧事件。

初始分层阈值建议：

- `relevance >= 0.65`：强相关，优先尝试完整 `full_context_view`。
- `0.35 <= relevance < 0.65`：中相关，默认使用 `context_long`，预算充裕时可升级为完整。
- `relevance < 0.35`：弱相关，默认使用 `context_brief` 或只进入 `season_rolling_context`。
- 上一集即使分数较低，也至少尝试 `context_long`；预算允许时优先完整。

成本估算按“实际要发送的上下文视图”计算，不按原视频时长计算：

- 每个候选分别估算 `full_cost`、`context_long_cost`、`context_brief_cost`。
- 成本来源是序列化后的 JSON/text 视图，而不是原始视频时长。
- 中文、日文、韩文按保守 token 成本估算；英文按较低成本估算；JSON 字段名、标点和换行也要计入。
- 不新增 tokenizer 依赖的第一版可使用保守字符估算，例如 CJK/Kana/Hangul 约按 1 字符 1 token，英文和数字约按 3 到 4 字符 1 token，再整体加 15% 到 25% 安全余量。
- 后续可以把真实 `prompt_tokens` 和估算值记录到日志或 run metadata 中，逐步校准估算倍率。

AI 合并产物必须记录真实 token 用量，作为后续上下文成本参考：

- episode merge 成功后，把该次模型调用的 `prompt_tokens`、`completion_tokens`、`total_tokens` 写入 `episode_content.json` 的 metadata。
- `completion_tokens` 可作为该集完整结构化信息量的第一参考，因为它接近 AI 合并后完整 episode context view 的内容规模。
- episode summary 成功后，也记录 summary 的 token 用量，用于估算 `context_long` 和 `context_brief` 的成本。
- season merge 和 season summary 同样记录 token 用量，用于跨季背景成本估算。
- token 用量只能作为参考，不直接等同于下一次请求成本；下一次真正发送前仍要对实际序列化后的上下文视图重新估算，并记录估算值。
- 如果供应商没有返回 token usage，则回退到保守字符估算，并在 `context_policy` 中标记 `token_usage_unavailable`。

上下文预算建议用比例而不是固定集数：

- `context_window_tokens` 来源优先级：preset 中已有值 > 内置模型能力表推断 > provider adapter 自动获取 > 保守默认预算。
- provider adapter 只有在供应商 API 明确返回上下文窗口或最大输入 token 时，才把它当成自动获取结果；不能从模型名臆测为已验证事实。
- 如果暂时没有 context window，就使用保守内部默认预算，并在 `context_policy` 中记录 `context_window_unknown`。
- 当前 chunk、transcript、固定 prompt 和预期输出必须先预留预算。
- 历史上下文默认不应超过可用输入预算的约 40% 到 50%；如果当前 chunk 很短且模型窗口充裕，可放宽；如果当前 chunk transcript 很长，则收紧。
- `season_rolling_context` 和前一季长总结要有保底预算，但不能挤掉当前 chunk 和上一集上下文。
- 当前季已完成 episode 的历史上下文池设置 `128k tokens` 硬上限。这个上限约束的是“集上下文池”，不是整次请求总 token。
- 实际可用集上下文预算取更小值：`min(128k, 模型可用输入预算 - 当前 chunk/transcript/prompt/output 预留 - 安全余量)`。
- 如果模型上下文窗口未知或小于 128k，不能假设一定可发送 128k；必须按保守预算运行，并把 `episode_context_cap_requested=128k` 与实际采用的 `episode_context_budget` 都写入 `context_policy`。
- 128k 池内优先放上一集完整 context view、强相关完整 context view、其他集长摘要和 season rolling context；超过 128k 时按降级顺序处理。

选择算法建议：

1. 生成所有已完成 episode 的三种视图和三种成本。
2. 从当前已完成 chunk 生成 `current_signals`。
3. 计算每个候选 episode 的 `relevance`。
4. 强制保留上一集至少 `context_long`，除非预算连长摘要都放不下。
5. 强制保留覆盖所有已完成集的 `season_rolling_context`。
6. 按 `relevance / cost` 和时间接近度排序，贪心加入完整或长摘要视图。
7. 如果预算剩余，优先把强相关 `context_long` 升级为 `full_context_view`。
8. 如果预算不足，按弱相关、远距离、重复信息优先降级或移除。
9. 写入 `context_policy`：每个候选 episode 的分数、成本、选择层级和选择理由。

建议的实际行为：

- 当前集第一个 chunk：优先带上一集完整 context view、当前季 rolling context、前一季长总结。
- 当前集后续 chunk：根据已经识别出的人物和冲突，动态补入强相关旧集的完整 context view。
- 信息量很小的旧集可以多带几集完整信息；信息量很大的旧集即使只有一集，也可能降级为长摘要。
- 强相关旧集比单纯更近但无关的旧集更值得完整带入；但上一集保留最高默认优先级，因为它最容易承接剧情。

前序季度的策略：

- 跨季默认不带完整 `season_content.json`，只带 `season_summary.json` 的长总结。
- 前一季长总结优先级最高；更早季度可以压缩成 `series_background_summary`。
- 季度背景必须讲清主要人物、关系、故事梗概、季末状态和未解决冲突，不能只写一句概括。

降级顺序：

1. 删除重复信息：如果带了完整 episode context view，就不再重复带同一集的长摘要。
2. 更早 episode 从完整 context view 降为 `context_long`。
3. 低相关 episode 从 `context_long` 降为 `context_brief`。
4. 更早季度从单季长总结合并为 `series_background_summary`。
5. 保留最近 episode、强相关 episode 和前一季核心背景；丢弃低相关、低价值的历史细节。

上下文裁剪不能简单按字符截断 JSON 中间片段。必须优先使用结构化字段选择、条目数量限制或已生成摘要，避免产生不可解析或语义断裂的上下文。所有降级都写入 `context_policy`，说明哪些信息被完整传入、哪些被摘要替代、哪些被裁剪，以及原因是预算不足、相关性较低还是重复信息。

AI 合并和摘要的输出 token 预算必须作为文本请求单独设计：

- 不复用视频请求的“输出 Token / 分钟”；视频 chunk、episode merge、episode summary、season merge、season summary 是不同 purpose。
- 每个文本合并 purpose 都应有 `min_output_tokens`、`target_output_tokens`、`max_output_tokens` 或等价配置。
- `episode merge` 的目标输出预算要随本集成功 chunk 数量、chunk 信息量、历史 completion token 和 schema 字段复杂度增长，不能固定成很小值。
- `episode summary` 的目标输出预算要保证能写出 `context_long`、`context_brief`、`context_candidate` 和主要人物/关系/冲突，不得只够一句话。
- `season merge` 和 `season summary` 要优先保证主要人物、关系图谱、故事梗概、季末状态和未解决线索完整，不得因为输出预算不足变成短摘要。
- 如果预算 helper 发现模型可用窗口无法同时容纳输入上下文和最低输出预算，应优先降级历史上下文；仍不足时阻断请求并给出清晰 warning。
- 每次请求都记录 `requested_output_tokens`、实际 `completion_tokens`、`finish_reason` 和是否疑似输出截断；输出截断不能写入成功 artifact。

### 5.7 失败、部分成功与恢复

高质量流程默认不把失败伪装成成功：

- chunk 提取失败：记录 warning，是否继续由失败类型和配置决定。供应商拒绝类错误沿用现有 `allow_provider_rejected_chunk_skip`；允许跳过时，episode merge 必须知道缺失 chunk，并在 `source_counts` 和 `aggregation_warnings` 中标记部分成功；不允许跳过时，阻断当前正式流程。
- 非供应商拒绝类 chunk 失败：`FULL`/`CLEAN` 默认不把该 episode 写成成功态；如果未来要继续合并部分 episode，必须新增显式用户选项或调试选项。`FAST` 可以继续其他并发 chunk，并只用成功且 schema 合格的产物重整理。
- 输出 token 截断、JSON 解析失败或 schema 校验失败：默认不能当成成功 chunk。JSON 解析失败最多重试 3 次；仍失败时，不写成功 artifact，并按非供应商拒绝类失败处理。
- episode merge 失败：该 episode 不写成功态 `episode_content.json`，也不能用本地 concat 假装成功；后续 episode 只能使用此前已成功 episode 上下文，并记录当前 episode 缺失。
- episode summary 失败：该 episode 不作为完整上下文进入后续 episode；如果 `episode_content.json` 成功，允许用它生成临时 `context_brief` 只作为恢复提示，但必须标记为非正式摘要。
- season merge 或 summary 失败：后续 season 不能把失败季当成可靠背景；如果前一季 summary 缺失，跨季上下文必须明确写入缺失警告。
- 快速提取的 chunk 阶段可以继续处理其他并发任务；episode/season 重整理只消费当前 run 中成功且 schema 合格的产物。部分输入是内部流程策略，不新增确认窗，但必须在洞察流和产物 metadata 中说明哪些 chunk 或 episode 缺失。

每个 artifact 应记录：

- `extraction_run_id`
- `extraction_stage`
- `source_kind`
- `schema_version`
- `source_counts`
- `context_policy`
- `aggregation_warnings`
- `model_profile_id` 或模型 metadata
- `token_usage`，包含本 artifact 对应 AI 调用的输入、输出和总 token；没有供应商统计时记录为空并使用估算字段。
- `estimated_context_tokens`，记录后续作为上下文视图时的估算 token 成本。
- `failure_policy` 或等价字段，记录本次 run 对供应商拒绝、输出截断、JSON 解析失败和部分成功聚合的处理规则。

## 6. 数据与持久化

### 6.1 提取模式

扩展 `ExtractionMode`：

- `PREVIEW = "preview"`
- `FULL = "full"`
- `CLEAN = "clean"`
- `FAST = "fast"`

UI 展示文案使用：

- 预览
- 完整提取
- 洁净提取
- 快速提取

### 6.2 Run 隔离

新增 `extraction_run_id`，每次正式提取、洁净提取、快速提取开始时生成。写入：

- `source_manifest.json`
- 每个 `ChunkExtractionResult`
- `episode_content.json`
- `episode_summary.json`
- `season_content.json`
- `season_summary.json`

聚合和后续上下文读取默认只消费当前 run 的 full artifact。若未来要恢复中断任务，再另行设计“选择/恢复 run”的 UI，不在本计划中默认启用旧 run 混读。

### 6.3 洁净提取清理边界

默认清理：

- `knowledge_base/source_manifest.json`
- `knowledge_base/seasons/**/chunks/*.json`
- `knowledge_base/seasons/**/episode_content.json`
- `knowledge_base/seasons/**/preview__episode_content.json`
- `knowledge_base/seasons/**/episode_summary.json`
- `knowledge_base/seasons/**/episode_transcript.json`
- `knowledge_base/seasons/*/season_content.json`
- `knowledge_base/seasons/*/season_summary.json`
- `knowledge_base/seasons/*/character_stage_states.json`

默认保留：

- `raw/`
- `materials/`
- `cache/`
- `output/`
- `knowledge_base/character_cards/`
- `knowledge_base/preview_character_cards/`
- 项目 `config.json`

清理必须由 `core.knowledge_base` 或窄 helper 执行，做项目根路径校验，不能在 GUI 层拼接删除路径。
清理后已有已编译正式角色卡必须标记 stale。该操作只更新角色卡状态和质量提示，不删除 `character_cards/{card_id}/card.json` 母本；草稿卡和预览卡保持原状态。

### 6.4 上下文产物

继续使用现有文件名，增强内容结构：

- `chunks/chunk_0001.json`：当前 chunk 提取结果，保留 `facts`、`behavior_traits`、`dialogue_style`、`relationship_interactions`、`conflicts`、`character_state_changes`、`insight_summary`、`evidence_refs`。
- `episode_content.json`：AI 合并后的本集完整结构化内容，必须保留 `chunk_results` 或 chunk 引用，便于追溯；同时生成可直接作为上下文的 `full_context_view`，它应来自合并后的结构化字段，而不是无限展开原始 chunk 结果。
- `episode_summary.json`：AI 生成的集级压缩摘要，面向后续提取上下文，不是 UI 短摘要；至少包含 `context_long`、`context_brief`、`context_candidate`、`estimated_context_tokens` 和 token usage metadata。
- `season_content.json`：AI 或分层合并后的本季完整结构化内容，保留 episode 引用。
- `season_summary.json`：AI 生成的季级长总结，作为跨季背景，必须包含主要人物、剧情梗概、关系图谱、状态变化、未解决冲突和不确定点；同时提供可压缩成 `series_background_summary` 的结构化段落。

## 7. 上下文构造规则

本章是第 5.6 节预算策略的执行摘要；若实现时发现两处表述不一致，以第 5.6 节的动态预算与降级规则为准。

### 7.1 Chunk 提取上下文优先级

每个正式 chunk 请求必须包含这些语义段：

1. `CURRENT_CHUNK`：当前视频 chunk 和可选 transcript，是最高优先级证据。
2. `CURRENT_EPISODE_EXTRACTED_CHUNKS`：当前集已完成 chunk 的完整结构化结果。
3. `CURRENT_SEASON_COMPLETED_EPISODES`：当前季已完成集的信息。预算允许时优先放完整 `episode_content.json`；超预算时放 `episode_summary.json`。
4. `PREVIOUS_SEASON_BACKGROUNDS`：前序季度长总结。至少包含前一季；更早季度可用更压缩的系列背景表示。

提示词必须明确说明：低优先级上下文只用于连续性，不得覆盖当前 chunk 观察到的新事实。

### 7.2 过长上下文降级

上下文预算按优先级降级：

- 当前 chunk 永不降级。
- 同集 chunk 产物尽量全量带入；若过长，保留最近若干个完整 chunk，并把更早 chunk 先合成为 `episode_rolling_context`。
- 当前季已完成集优先带完整 `episode_content.json`；若过长，替换为 `episode_summary.json`。
- 前序季度使用 `season_summary.json`，必要时再合成为更短的 `series_background_summary`。

降级必须写入 artifact 的 `context_policy` 或 `aggregation_warnings`，方便后续复核。

### 7.3 AI 合并与摘要

新增或扩展 prompt purpose：

- `formal_contextual_video_chunk_extraction`
- `formal_episode_content_merge`
- `formal_episode_summary`
- `formal_season_content_merge`
- `formal_season_summary`

episode AI 合并输入：

- 本集所有 chunk 结构化产物。
- 本集 source metadata。
- 可选当前季已完成集摘要和前序季背景，用于连续性，但不得补写无证据事实。

episode AI 合并输出：

- 本集事实、角色行为、对白风格、关系互动、冲突、状态变化、证据引用。
- 按 chunk 可追溯的来源引用。
- 不确定点和需要人工复核点。

如果 AI 合并失败，不得静默写入“看起来成功”的本地合并结果。允许写失败事件和日志；是否启用本地 fallback 必须作为显式调试选项，不作为默认行为。

## 8. 模式行为

### 8.1 完整提取

顺序：

1. 创建 `extraction_run_id` 和 run plan。
2. 扫描 `materials/` 并保存带 run id 的 manifest。
3. 初始化知识库结构。
4. 逐季、逐集、逐 chunk 串行提取。
5. 每个 chunk 成功后写 full chunk artifact。
6. 每集 chunk 完成后执行 AI episode merge。
7. 每集 AI merge 成功后执行 AI episode summary。
8. 每季 episode 完成后执行 AI season merge。
9. 每季 AI merge 成功后执行 AI season summary。
10. 如果本次 run 成功写入正式知识库产物，标记已编译正式角色卡 stale。
11. 发出完成事件、token 用量和聚合产物数量。

### 8.2 洁净提取

顺序：

1. 进入高风险确认：提示会清除可再生提取中间产物，但不会删除素材、项目配置、角色卡和导出结果。
2. 调用知识库清理 helper。
3. 执行完整提取的同一套流程。

### 8.3 快速提取

顺序：

1. 创建 `extraction_run_id` 和 run plan。
2. 扫描 `materials/` 并保存带 run id 的 manifest。
3. 初始化知识库结构。
4. 弹出确认窗，提示快速提取偏差会很大，并要求用户输入并发数。
5. 使用用户输入的有界并发处理 chunk，不带同集、跨集、跨季上下文。
6. 保存 chunk full artifact。
7. 全部 chunk 完成后，按 episode 并发执行 AI 集级重整理，生成 `episode_content.json` 和 `episode_summary.json`。
8. 全部 episode 重整理完成后，按 season 并发执行 AI 季级重整理，生成 `season_content.json` 和 `season_summary.json`。
9. 如果本次 run 成功写入正式知识库产物，标记已编译正式角色卡 stale。

并发规则：

- 并发数由用户在确认窗输入，允许范围为 1 到 500。
- UI 必须提示高并发可能触发供应商限流、费用增加、输出不稳定和本机资源压力。
- chunk 提取、episode AI 重整理和 season AI 重整理都使用同一并发配置，除非后续用户另行确认拆分配置。
- 遇到供应商拒绝、限流或输出截断时，必须按 chunk 记录 warning，不影响其他已完成 chunk。
- 聚合只消费当前 `extraction_run_id` 的 full artifact。

## 9. 模块边界

- `core.models`：扩展 `ExtractionMode`，必要时扩展提取 artifact metadata 模型或字段。
- `core.knowledge_base`：新增清理 helper、run id 过滤 helper、读取当前 run artifact 的 helper。
- `core.extractor`：承载完整提取、洁净提取、快速提取的编排；上下文构造可拆出窄 helper，避免 `Extractor` 继续膨胀。
- `core.source_scanner`：继续只负责素材结构扫描，不承担模式逻辑。
- `utils.ai_model_middleware`：继续负责 prompt 渲染和模型调用，不写业务流程。
- `res/default_prompts.json`：新增或更新 prompt purpose，不在 Python 代码中硬编码大段 prompt。
- `gui.main_window` 和 worker：按模式调用对应入口，展示进度、失败、token 用量。
- `gui.pages.project_page`：提供模式选择、洁净提取确认入口和快速提取并发确认入口；不直接删除文件。
- `i18n`：同步四个语种的模式名、确认文案、警告、失败和完成提示。

## 10. 里程碑与负荷均衡

本轮重新拆分后的原则：

- 每个里程碑只承担一个主要风险面：流程编排、存储、预算、prompt、AI 调用、正式流程、快速流程、UI 或验证，不混在一起。
- 每个里程碑最好只跨 1 到 3 个主要模块；跨 `core`、`gui`、`utils`、`res`、`i18n` 的改动拆到不同阶段。
- 每个里程碑都要有可观察验收，不要求真实大模型才能判断基本完成。
- 高质量正式流程优先，快速提取和 UI 在核心能力稳定后接入。
- 大阶段拆小，但不把一个必须同时完成的原子行为拆碎到无法验证。

负荷复查结论：

- 原 M03 负荷过重，已拆为模型窗口、上下文视图、相关性选择、prompt/schema、AI 调用与重试五组。
- 原 M04 负荷过重，已拆为 FULL chunk 串行、episode 合并、season 合并、失败恢复四组。
- 原 M06 负荷过重，已拆为 FAST chunk 并行、FAST episode 重整理、FAST season 重整理三组。
- 原 M07 混合 UI、i18n、验证和文档，已拆成 UI 控制、洞察展示/i18n、验证文档三组。

### M01：模式枚举与 run plan 骨架

交付：

- 扩展 `ExtractionMode`，加入 `CLEAN` 和 `FAST`。
- 定义 `ExtractionRunPlan` 或等价结构，包含 run id、mode、manifest 引用、模型预设、素材顺序和预算策略占位。
- 明确阶段枚举或状态常量：prepare、chunk、episode_merge、episode_summary、season_merge、season_summary、done、failed。

验收：

- 假数据能创建 run plan，并稳定输出 season/episode/chunk 顺序。
- 状态结构能表达部分成功和阶段失败。
- 不发真实模型请求。

边界：

- 不接 GUI。
- 不改变现有正式提取行为。

### M02：artifact metadata 与 schema 版本

交付：

- 为 chunk、episode、season 产物统一 metadata 字段：`extraction_run_id`、`extraction_stage`、`schema_version`、`source_counts`、`model_profile_id`、`token_usage`、`estimated_context_tokens`。
- 定义 `context_policy`、`aggregation_warnings`、`failure_policy` 的最小结构。
- 明确 preview artifact 与 full artifact 的区分字段或命名规则。

验收：

- 假 artifact 能序列化和反序列化。
- 缺少新 metadata 的旧 artifact 不会让读取路径崩溃。
- 新 schema 不改变角色卡母本格式。

边界：

- 不做 AI 合并。
- 不做清理删除。

### M03：manifest 与 run 隔离读写

交付：

- `source_manifest.json` 写入当前 `extraction_run_id`。
- 新增按 run id 读取 chunk/episode/season artifact 的 helper。
- 聚合和上下文读取默认只消费当前 run 的正式产物。

验收：

- 构造旧 run 和新 run 混合文件时，只读取新 run。
- preview 产物不会被 full/clean/fast 聚合消费。
- manifest 排序在本次 run 内稳定。

边界：

- 不处理洁净删除。
- 不改 UI。

### M04：洁净清理 helper 与 stale 标记

交付：

- 新增知识库可再生产物清理 helper，路径限定在当前项目知识库内。
- 清理 `preview__chunk_*.json` 等预览 chunk 中间产物，保留 `preview_character_cards/`。
- 复用或补齐正式角色卡 stale 标记 helper，只影响已编译正式卡。

验收：

- 清理不会删除 `raw/`、`materials/`、`output/`、`character_cards/`、`preview_character_cards/`。
- 已编译正式卡可被标记 stale，草稿卡和预览卡保持原状态。
- 清理失败时返回明确错误，不继续后续提取。

边界：

- 不在 GUI 层拼接删除路径。
- 不删除角色卡母本。

### M05：模型窗口与输出预算基础

交付：

- 增加可选 `context_window_tokens`，支持 preset 持久化、内置模型能力表推断和 provider 尽力自动获取；当前不含独立 UI 手动输入入口。
- 建立文本合并请求的输出 token 预算模型，不复用视频“输出 Token / 分钟”。
- 定义 `episode merge`、`episode summary`、`season merge`、`season summary` 的最低、目标和最大输出预算策略。

验收：

- 有 context window 时能计算可用输入预算。
- 无 context window 时使用保守默认预算，并记录 `context_window_unknown`。
- 输出预算不足时能给出 warning，而不是悄悄截断。

边界：

- 不发真实合并请求。
- 不做上下文相关性选择。

### M06：episode 上下文视图构造

交付：

- 从 `episode_content.json` 生成 `full_context_view`。
- 从 `episode_summary.json` 生成 `context_long` 和 `context_brief`。
- 生成 `context_candidate`，包含人物、关系、线索、地点、组织、重要度和成本估算。

验收：

- 假 episode 能生成三种上下文视图和候选 metadata。
- 成本估算基于实际序列化内容，不按固定集数或视频时长。
- 视图不无限展开原始 chunk 结果。

边界：

- 不选择哪些 episode 入上下文。
- 不改 prompt。

### M07：相关性评分与上下文选择

交付：

- 实现 `current_signals` 构造。
- 实现 episode 相关性评分和 `relevance / cost` 选择。
- 实现 128k episode context pool、降级顺序和 `season_rolling_context` 保底。

验收：

- 上一集至少尝试 `context_long`。
- 强相关旧集可优先于近但无关的旧集。
- 超预算时按完整视图、长摘要、短摘要、滚动上下文顺序降级，并写入 `context_policy`。

边界：

- 不发模型请求。
- 不简单截断 JSON。

### M08：prompt purpose 与输出 schema

交付：

- 在 `res/default_prompts.json` 增加或更新 `formal_contextual_video_chunk_extraction`、`formal_episode_content_merge`、`formal_episode_summary`、`formal_season_content_merge`、`formal_season_summary`。
- 明确 chunk、episode、season 输出字段和证据引用格式。
- prompt 明确当前 chunk 证据高于历史上下文。

验收：

- 假 payload 能渲染五类 prompt。
- prompt 不要求模型用历史上下文补写当前 chunk 未出现的事实。
- 输出 schema 包含不确定点和来源引用。

边界：

- 不在 Python 中硬编码大段 prompt。
- 不改 UI 文案。

### M09：AI 调用、JSON 重试与 token usage 记录

交付：

- 为正式提取的文本合并请求建立统一调用 helper，仍通过 `utils.ai_model_middleware`。
- JSON 解析失败最多重试 3 次，仍失败则报错。
- 写入 `token_usage`、`requested_output_tokens`、`finish_reason` 和输出截断标记。

验收：

- 模拟 JSON 解析失败时会重试 3 次。
- 三次失败不写成功 artifact。
- token usage 缺失时写入估算字段和缺失标记。

边界：

- 不绕过模型中间件。
- 不启用本地 concat fallback。

### M10：FULL 串行 chunk 提取接线

交付：

- `FULL` 模式按 season -> episode -> chunk 串行推进。
- chunk 请求带当前 chunk、同集已完成 chunk、已选择 episode 上下文和前序季背景。
- 每个成功 chunk 写入当前 run 的 full artifact。

验收：

- 第二个 chunk 能拿到第一个 chunk 的结构化结果。
- 第二集第一个 chunk 能拿到第一集上下文。
- full 不消费 preview artifact。

边界：

- 不做 episode AI merge 接线。
- 不启用 chunk 并行。

### M11：episode AI 合并接线

交付：

- 每集 chunk 阶段结束后执行 `formal_episode_content_merge`。
- episode merge 输入包含本集成功 chunk、source metadata、必要历史上下文和缺失来源说明。
- 写入 AI 合并后的 `episode_content.json`，包含 `full_context_view` 或可生成它的结构化字段。

验收：

- 多 chunk episode 能生成 AI 合并产物。
- 缺失 chunk 会进入 `aggregation_warnings`。
- merge 失败不写成功态 `episode_content.json`。

边界：

- 不做 episode summary。
- 不做 season merge。

### M12：episode summary 接线

交付：

- episode merge 成功后执行 `formal_episode_summary`。
- 写入 `episode_summary.json`，包含 `context_long`、`context_brief`、`context_candidate` 和 token metadata。
- 后续 episode 上下文读取优先使用成功 summary。

验收：

- summary 不短到只剩一句话。
- summary 失败时不把该 episode 当作完整上下文。
- token usage 和估算成本可供 M07 复用。

边界：

- 不做 season merge。

### M13：season AI 合并接线

交付：

- 每季 episode 全部处理后执行 `formal_season_content_merge`。
- 输入当前季 episode content、episode summary 和前序季长总结。
- 写入 `season_content.json`，保留 episode refs。

验收：

- 多 episode season 能生成 AI 季级内容。
- season content 包含主要角色、关系、事件和未解决线索。
- merge 失败不写成功态 season content。

边界：

- 不做 season summary。

### M14：season summary 与跨季背景

交付：

- season merge 成功后执行 `formal_season_summary`。
- 写入长 `season_summary.json`，可作为下一季低优先级背景。
- 支持更早季度压缩为 `series_background_summary`。

验收：

- 第二季第一个 chunk 能拿到第一季长总结。
- 前一季 summary 缺失时写入跨季上下文缺失警告。
- summary 包含主要人物、故事梗概、关系、季末状态和未解决冲突。

边界：

- 不回改已完成 episode。

### M15：失败、部分成功与恢复状态

交付：

- 统一处理供应商拒绝、输出截断、JSON 失败、schema 失败、merge 失败和 summary 失败。
- 沿用 `allow_provider_rejected_chunk_skip` 控制拒绝片段是否跳过。
- run 结束时输出成功数、跳过数、失败数和 stale 标记结果。

验收：

- 不允许跳过拒绝片段时阻断正式流程。
- 允许跳过时 episode/season 标记缺失来源。
- 所有失败都不会伪装成成功 artifact。

边界：

- 不新增复杂恢复 UI。

### M16：CLEAN 模式 core 接线

交付：

- `CLEAN` 模式先调用清理 helper，再调用 FULL 高质量流程。
- 清理成功和重新提取成功分别发出洞察事件。
- 成功写入正式知识库产物后标记已编译正式卡 stale。

验收：

- 清理失败不启动提取。
- CLEAN 与 FULL 使用同一套线性上下文流程。
- 不删除用户素材、导出结果或角色卡母本。

边界：

- 本阶段不做确认弹窗 UI。

### M17：FAST chunk 并行执行器

交付：

- `FAST` 模式按用户并发数并行提取 chunk。
- chunk 请求不注入同集、跨集、跨季上下文。
- 单个 chunk 失败不阻断其他 chunk。

验收：

- 多 chunk 假项目中请求可以并行发起。
- 并发数边界由调用参数控制在 1 到 500。
- 聚合只读取当前 run 的成功 chunk。

边界：

- 不做 episode/season 重整理。
- 不承诺上下文连续性。

### M18：FAST episode 重整理

交付：

- 所有 chunk 完成后，按 episode 并发执行 AI 集级重整理。
- 允许部分成功输入，不额外弹确认窗。
- 没有任何成功 chunk 的 episode 跳过重整理。

验收：

- episode 重整理等待对应 episode 的 chunk 阶段结束。
- 缺失 chunk 在洞察流、run 状态和 artifact warnings 中可见。
- 输出 `episode_content.json` 和 `episode_summary.json`。

边界：

- 不做 season 重整理。

### M19：FAST season 重整理与 stale

交付：

- 所有 episode 重整理完成后，按 season 并发执行 AI 季级重整理。
- season 重整理只消费当前 run 中成功且 schema 合格的 episode。
- FAST 成功写入正式知识库产物后标记已编译正式卡 stale。

验收：

- season 重整理等待对应 season 的 episode 重整理阶段结束。
- 部分 episode 缺失会进入 season warnings。
- 聚合结果不混入旧 run。

边界：

- 不新增独立并发配置；继续共用用户输入的并发数。

### M20：模式选择 UI 与确认弹窗

交付：

- 项目页模式选择显示预览、完整提取、洁净提取、快速提取。
- 洁净提取确认窗说明清理边界。
- 快速提取确认窗提示偏差大，并要求输入 1 到 500 的并发数。

验收：

- 用户取消确认时不启动任务。
- 用户输入 0、501、非数字或空值时阻止启动。
- GUI 只触发 worker/core，不直接删除文件。

边界：

- 不在本阶段补齐全部洞察流文案。

### M21：洞察流、token 展示与 i18n

交付：

- 洞察流展示 run 阶段、跳过片段、部分成功、输出截断风险和 stale 标记结果。
- 项目页 token usage 附近展示本次 run token 用量和预算警告。
- 四个 `i18n` 文件补齐新增模式名、确认文案、警告、失败和完成提示。

验收：

- 没有新增硬编码 UI 文案。
- 第一版不展示精确费用估算。
- 用户能看出哪些片段或 episode 被跳过。

边界：

- 不重做洞察流整体设计。

### M22：验证、架构文档与收尾

交付：

- 增加最小测试或脚本级验证，覆盖 run 过滤、清理边界、上下文排序、预算降级、JSON 重试、模式分流。
- 更新 `core/ARCHITECTURE.md` 和必要的 `docs/reference/extraction-workflow.*.md`。
- 补充手动验收步骤和已知限制。

验收：

- 可运行现有启动路径。
- 预览和现有完整提取入口不被破坏。
- 若环境可用，运行 `python -m ruff check .`。
- 若添加测试，测试命令在阶段总结中明确。

边界：

- 不把一次性任务进度写入 `AGENTS.md`。

## 11. 验证与自审要求

每个里程碑完成后检查：

- 是否只完成该里程碑边界内的工作，未顺手跨到后续阶段。
- 是否仍通过 `utils.ai_model_middleware` 调用模型。
- 是否只由 core/helper 执行知识库删除、读取和写入，GUI 不拼接业务路径。
- 是否保持 preview/full/clean/fast 产物互不污染。
- 是否记录 `extraction_run_id`、`context_policy`、warnings 和 token usage。
- 是否避免本地 concat fallback 伪装 AI 合并成功。
- 是否没有新增硬编码 UI 文案。

进入用户验收前整体检查：

- full/clean 不并行 chunk，依赖顺序符合 season -> episode -> chunk。
- fast 的 chunk、episode 重整理和 season 重整理按依赖阶段并发执行。
- 洁净清理保留用户素材、导出结果、正式角色卡母本和预览角色卡。
- 已编译正式角色卡在正式知识库新 run 成功写入后标记 stale。
- 128k episode context pool 能随模型窗口收缩，并记录实际预算。
- AI 合并失败、输出截断和 JSON 三次重试失败都不会写入成功 artifact。
- 四个 i18n JSON 覆盖所有新增用户可见文案。

## 12. 提交分组建议

提交 1：模式枚举、run plan、阶段状态和 artifact metadata。覆盖 M01-M02。

提交 2：manifest/run 隔离、清理 helper 和 stale 标记。覆盖 M03-M04。

提交 3：模型窗口、输出预算、episode 上下文视图和相关性选择。覆盖 M05-M07。

提交 4：prompt purpose、输出 schema、AI 调用 helper、JSON 三次重试和 token usage 记录。覆盖 M08-M09。

提交 5：FULL 串行 chunk、episode merge/summary、season merge/summary。覆盖 M10-M14。

提交 6：失败处理、部分成功、CLEAN core 接线。覆盖 M15-M16。

提交 7：FAST chunk 并行、episode 重整理、season 重整理。覆盖 M17-M19。

提交 8：模式 UI、确认弹窗、洞察流、token 展示和 i18n。覆盖 M20-M21。

提交 9：验证、架构文档、手动验收说明和计划状态更新。覆盖 M22。

提交信息使用 Conventional Commits，并在用户要求提交时使用 `git commit -s`。

## 13. 阶段性结论与待跟踪问题

当前没有阻塞本轮正式提取模式实施的产品决策。本轮已完成的主线不再继续扩写成新的待办；后续工作进入 `docs/plans/TODO.zh_CN.md` 或独立专项计划。

仍需跟踪：

- 角色卡分层证据仍需真实素材回归和分类边界调优；基础实现已归档到 `character-card-quality-followup-plan.completed.zh_CN.md`。
- 自动化验证需要从手动试跑扩展到脚本级回归。
- 日志隐私需要收敛模型请求/响应正文和临时素材 URL。

## 14. 后续可选扩展

- 如后续需要，可为快速提取的 chunk 提取、episode 重整理、season 重整理分别设置并发数。当前计划按用户确认，三者共用同一个 1 到 500 的并发数。
- 如后续需要，可在快速提取确认窗中加入费用估算。当前计划先显示质量偏差、限流、费用和资源压力警告，不做精确估算。
