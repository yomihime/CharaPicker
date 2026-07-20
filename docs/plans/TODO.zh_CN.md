# TODO List（zh_CN）

最近整理日期：2026-07-20。

本文只收录仍需执行或持续跟踪的任务。已完成的角色卡最终编译、角色卡页面、角色卡质量调优、正式视频提取基础链路、多供应商首版、日志治理和内置 proxy 设置计划已移入完成区或 `docs/archive/`；历史里程碑不再占用当前执行队列。

## 近期执行路线

路线 01 的提取质量基线、路线 02 的正式提取架构重构、路线 03 的多内容形态实现与真实验收已经按顺序完成。当前执行重点调整为：

1. 持续运行统一离线回归，保持四媒体类型、预览/正式隔离、来源追踪和旧视频链路不回退。
2. 按已确认的工具链顺序完成 RAR 和 CBR；ZIP、CBZ、EPUB、PDF 与 7z 已通过受控预处理和统一回归。
3. 根据真实验收结果继续调整供应商拒绝、证据质量、进度和 UI 反馈，不提前扩展新的媒体类型或大范围插件架构。

## P0：Extract Once 覆盖缺口

路线 03 的扫描、handler、预览、正式聚合、角色卡证据、失败记录、GUI 状态、统一离线回归和支持格式真实验收已经落地，执行事实见 [番剧、漫画、广播剧、小说等内容形态支持执行计划完成记录](../archive/03-multi-material-coverage-plan.completed.zh_CN.md)。当前 P0 只保留真实素材暴露出的输入容器缺口。

| 顺序 | 待办 | 优先级 | 规模 | 主要验收点 |
| --- | --- | --- | --- | --- |
| 1 | 继续执行 [更多输入格式支持执行计划](input-format-support-plan.zh_CN.md)，完成 RAR 和 CBR 的受控导入预处理 | 中 | 中 | ZIP、CBZ、EPUB、PDF 和 7z 已启用并通过格式独立验证；RAR/CBR 必须复用已确认的 7-Zip backend，并继续保持路径、解压大小、来源追踪和清理边界。 |

## P1：提取质量与可观测性

基础计划已归档到 [提取质量与可观测性执行计划完成记录](../archive/01-extraction-quality-observability-plan.completed.zh_CN.md)。正式提取与多内容形态回归已进入统一离线入口，以下只保留长期质量任务。

| 顺序 | 待办 | 优先级 | 规模 | 主要验收点 |
| --- | --- | --- | --- | --- |
| 2 | 持续更新提示词以尽量避免安全拒绝 | 中 | 中/长期 | 遇到新拒绝样例时优先维护 `res/default_prompts.json` 或用户 prompt override，不把 prompt 硬编码进代码，并保持 JSON 输出约束。 |
| 3 | 长期监测提取进度条是否真实反映工作流进度 | 中 | 小/长期 | 每次调整提取链路、chunk 跳过策略、失败处理或洞察流信号后，回归检查预览和正式提取的进度条是否随 chunk 处理、跳过、失败和完成事件稳定推进；前置失败不应显示为 100%。 |

## P2：归档后续与可选增强

| 顺序 | 待办 | 优先级 | 规模 | 主要验收点 |
| --- | --- | --- | --- | --- |
| 4 | 补充模型页图片与视频测试素材来源记录 | 低 | 小 | 如后续需要更完整素材声明，补充原始 URL；或替换为新的自由素材并更新 `docs/reference/asset-material-declaration.zh_CN.md`。 |
| 5 | 继续扩展首版以外的 API 规范 | 低 | 大 | 在多供应商首版稳定后，按优先级继续评估 OpenAI Responses、Gemini GenerateContent、Anthropic Messages 等 schema；每个 schema 需通过中间件路由和模型页测试验证后再开放。 |
| 6 | 增强 transcript 后处理能力 | 低 | 中 | 在 episode transcript 基础上按需增加说话人识别、置信度、字幕导入合并或人工校正流程，不影响首版 Whisper 接入。 |

## 已完成并移出队列

- 路线 01 提取质量与可观测性基础实施完成，正式提取回归、失败策略和可观察状态已建立。
- 路线 02 多媒体平级接入前重构完成：正式提取以 `FormalExtractionRunPlan` 为主索引，顶层媒体类型固定为 `video`、`image`、`audio`、`text`，transcript 作为 text 型派生成果处理。
- 路线 03 离线实现完成：普通文本、SRT/ASS、音频 transcript、PNG/JPEG/WEBP、漫画页组、视频 + 字幕关联和原生视听补充 handler 已进入统一扫描、预览、正式分派、聚合、角色卡证据和失败记录链路；`scripts/validate_multi_material_regression.py` 提供统一离线回归。
- 路线 03 多内容形态真实验收完成：视频、小说文本、独立图片、漫画目录、SRT 字幕、独立音频 transcript、视频 + 字幕、当前 run 聚合和非视频角色卡编译均已验证。验收使用从 EPUB/漫画 ZIP 安全抽取后的支持格式，容器直接导入仍保留在 P0。
- 模型级原生音频能力判断已统一：阿里云普通模型不会再因 provider 能力被误派到 native audio；不支持时保留 transcript 路径并返回可解释 warning，预检可通过 `--preset-name` 复用同一规则。
- 正式提取回归验证已覆盖 run 过滤、clean/fast 边界、handler 分派、preview/full 隔离、失败样例、stale 标记和多内容形态聚合；手动真实验收仍不能被离线回归替代。
- 整理输出角色卡空间：基础版已完成，详细计划归档到 [角色卡最终编译与角色卡页面计划](../archive/character-card-compilation-plan.completed.zh_CN.md)。
- 目标角色移动到角色卡页面，提取只提取素材信息，角色卡页面编译角色卡：基础版已完成，主页不再编辑目标角色，预览完成不再自动生成角色卡。
- 角色卡编译上下文分层、别名重分类、结构化复核原因和质量诊断基础实现：阶段性完成，详细记录已归档到 [角色卡质量后续执行计划完成记录](../archive/character-card-quality-followup-plan.completed.zh_CN.md)。
- 角色卡真实素材质量回归与提示调优：基础版已完成，真实试跑已覆盖未出场角色失败保护、中文名/别名与知识库候选名不一致时的别名重分类、结构化复核原因和内部 reason key 隔离。
- 正式提取模式、洁净提取、快速提取和线性上下文主线：阶段性完成，详细记录已归档到 [正式素材详细提取流程与模式计划完成记录](../archive/formal-extraction-modes-and-context-plan.completed.zh_CN.md)。
- 内置 proxy 设置：基础版已完成，设置页支持 HTTP、HTTPS、SOCKS5、SOCKS5 远程 DNS、固定三站点连通性测试和自定义 URL 测试；模型请求、模型列表、FFmpeg 下载和 llama.cpp 下载统一走网络中间件，日志和错误摘要需保持敏感信息脱敏。
- Proxy 运行时网络能力计划：已归档到 [Proxy 运行时网络能力计划完成记录](../archive/proxy-runtime-network-plan.completed.zh_CN.md)，未发现需迁入当前 TODO 的独立残项。
- 模型日志隐私与体积收敛：基础版已完成，模型调用、素材处理、正式提取和角色卡编译只保留安全摘要与 DEBUG 诊断信号；日志等级划分和脱敏边界已沉淀到 [运行时中间件设计说明](../reference/runtime-middleware.zh_CN.md)。

## 实施注意

- UI 可见文案继续同步维护 `i18n/*.json`。
- 模型请求仍必须通过 `utils.ai_model_middleware`。
- Prompt 修改优先维护 `res/default_prompts.json` 和用户 prompt override 机制，不在业务代码中硬编码 prompt。
- `ProjectConfig.target_characters` 仅作为旧项目兼容字段保留；新角色卡编译链路不应读取它。
