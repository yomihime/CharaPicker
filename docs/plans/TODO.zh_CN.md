# TODO List（zh_CN）

最近整理日期：2026-06-04。

本文只收录仍需执行或持续跟踪的任务。已完成的角色卡最终编译、角色卡页面、正式视频提取基础链路、多供应商首版和内置 proxy 设置计划已移入 `docs/archive/`；历史里程碑不再占用当前执行队列。

## P0：Extract Once 覆盖缺口

| 顺序 | 待办 | 优先级 | 规模 | 主要验收点 |
| --- | --- | --- | --- | --- |
| 1 | 文本、字幕与音频转写进入预览和知识库消费链路 | 高 | 大 | 没有视频 chunk 但存在可读文本、字幕或转写结果时，预览能生成真实 `ChunkExtractionResult`，来源路径和证据可追溯；正式提取已有 transcript 能力不得被破坏。详见 [真实预览结果后续计划](preview-real-result-ingestion-plan.zh_CN.md)。 |
| 2 | 图片、漫画与混合媒体接入 | 高 | 大 | 图片、漫画页组和混合媒体能映射到稳定 season/episode/chunk，并通过 `utils.ai_model_middleware` 生成与视频/text 一致结构的知识库结果。 |

## P1：角色卡质量后续

| 顺序 | 待办 | 优先级 | 规模 | 主要验收点 |
| --- | --- | --- | --- | --- |
| 3 | 角色卡编译上下文分层 | 高 | 中/大 | 在直接证据之外，明确拆出 `direct_evidence_episodes`、`mention_evidence_episodes`、`causal_context_episodes` 和 `season_context`；角色没出现但解释其行动动机的 episode 不能因 `targets` 或直接证据缺失而被丢掉。 |
| 4 | 角色卡冲突消解与质量评估强化 | 中 | 中/大 | 在已完成角色卡页面和正式知识库编译链路基础上，继续增强冲突证据保留、质量警告、`needs_review` 判断和输出可解释性；不得回退为重新分析原始素材。 |

## P2：提取质量与可观测性

| 顺序 | 待办 | 优先级 | 规模 | 主要验收点 |
| --- | --- | --- | --- | --- |
| 5 | 增加正式提取回归验证脚本 | 高 | 中 | 覆盖 run 过滤、洁净清理边界、完整/洁净/快速分流、JSON 三次重试、上下文预算降级、跳过片段聚合和 stale 标记；现有手动试跑不能替代最小自动化回归。 |
| 6 | 收敛模型日志隐私与体积 | 高 | 中 | DEBUG 日志不得展开完整模型请求/响应正文、临时素材 URL 或大段用户素材内容；保留 purpose、模型、token usage、状态和脱敏后的错误摘要。 |
| 7 | 持续更新提示词以尽量避免安全拒绝 | 中 | 中/长期 | 遇到新拒绝样例时优先维护 `res/default_prompts.json` 或用户 prompt override，不把 prompt 硬编码进代码，并保持 JSON 输出约束。 |
| 8 | 长期监测提取进度条是否真实反映工作流进度 | 中 | 小/长期 | 每次调整提取链路、chunk 跳过策略、失败处理或洞察流信号后，回归检查预览和正式提取的进度条是否随 chunk 处理、跳过、失败和完成事件稳定推进；前置失败不应显示为 100%。 |

## P3：归档后续与可选增强

| 顺序 | 待办 | 优先级 | 规模 | 主要验收点 |
| --- | --- | --- | --- | --- |
| 9 | 补充模型页图片与视频测试素材来源记录 | 低 | 小 | 如后续需要更完整素材声明，补充原始 URL；或替换为新的自由素材并更新 `docs/reference/asset-material-declaration.zh_CN.md`。 |
| 10 | 继续扩展首版以外的 API 规范 | 低 | 大 | 在多供应商首版稳定后，按优先级继续评估 OpenAI Responses、Gemini GenerateContent、Anthropic Messages 等 schema；每个 schema 需通过中间件路由和模型页测试验证后再开放。 |
| 11 | 增强 transcript 后处理能力 | 低 | 中 | 在 episode transcript 基础上按需增加说话人识别、置信度、字幕导入合并或人工校正流程，不影响首版 Whisper 接入。 |

## 已完成并移出队列

- 整理输出角色卡空间：基础版已完成，详细计划归档到 [角色卡最终编译与角色卡页面计划](../archive/character-card-compilation-plan.completed.zh_CN.md)。
- 目标角色移动到角色卡页面，提取只提取素材信息，角色卡页面编译角色卡：基础版已完成，主页不再编辑目标角色，预览完成不再自动生成角色卡。
- 正式提取模式、洁净提取、快速提取和线性上下文主线：阶段性完成，详细记录见 [正式素材详细提取流程与模式计划](formal-extraction-modes-and-context-plan.zh_CN.md)。
- 内置 proxy 设置：基础版已完成，设置页支持 HTTP、HTTPS、SOCKS5、SOCKS5 远程 DNS、固定三站点连通性测试和自定义 URL 测试；模型请求、模型列表、FFmpeg 下载和 llama.cpp 下载统一走网络中间件，日志和错误摘要需保持敏感信息脱敏。
- Proxy 运行时网络能力计划：已归档到 [Proxy 运行时网络能力计划完成记录](../archive/proxy-runtime-network-plan.completed.zh_CN.md)，未发现需迁入当前 TODO 的独立残项。

## 实施注意

- UI 可见文案继续同步维护 `i18n/*.json`。
- 模型请求仍必须通过 `utils.ai_model_middleware`。
- Prompt 修改优先维护 `res/default_prompts.json` 和用户 prompt override 机制，不在业务代码中硬编码 prompt。
- `ProjectConfig.target_characters` 仅作为旧项目兼容字段保留；新角色卡编译链路不应读取它。
