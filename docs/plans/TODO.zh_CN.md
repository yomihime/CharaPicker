# TODO List（zh_CN）

本文只收录仍需执行或持续跟踪的任务。已完成的角色卡最终编译、角色卡页面、角色卡质量调优、正式视频提取基础链路、多供应商首版、日志治理和内置 proxy 设置计划已移入完成区或 `docs/archive/`；历史里程碑不再占用当前执行队列。

## 当前状态摘要

路线 01 的提取质量基线、路线 02 的正式提取架构重构、路线 03 的多内容形态实现与真实验收，以及更多输入格式专项计划已经按顺序完成。当前没有独立 Extract Once 覆盖缺口；后续如真实素材暴露新的阻断问题，应先核对 [多内容形态完成记录](../archive/03-multi-material-coverage-plan.completed.zh_CN.md) 和 [更多输入格式完成记录](../archive/input-format-support-plan.completed.zh_CN.md)，再建立专项任务。

未完成内容按用途分为三类：持续跟踪、功能候选、加固与清理。这里是候选池和跟踪池，不表示所有条目都会进入后续版本；进入具体版本前仍按实际需要取舍，并以当前代码复核为准。规模只表示粗略改动幅度。

## 持续跟踪

| 顺序 | 待办 | 优先级 | 规模 | 主要验收点 |
| --- | --- | --- | --- | --- |
| 1 | 持续运行统一离线回归和打包验收 | 高 | 小/持续 | 保持四媒体类型、预览/正式隔离、来源追踪、旧视频链路、自更新包结构和打包态运行根目录不回退；发布前按 [打包与发布规范](../reference/release-packaging.zh_CN.md) 复核。 |
| 2 | 持续更新提示词以尽量避免安全拒绝 | 中 | 中/长期 | 遇到新拒绝样例时优先维护 `res/default_prompts.json` 或用户 prompt override，不把 prompt 硬编码进代码，并保持 JSON 输出约束。 |
| 3 | 监测提取进度条是否真实反映工作流进度 | 中 | 小/长期 | 每次调整提取链路、chunk 跳过策略、失败处理或洞察流信号后，回归检查预览和正式提取进度条是否随 chunk 处理、跳过、失败和完成事件稳定推进；前置失败不应显示为 100%。 |

## 功能候选

| 顺序 | 待办 | 优先级 | 规模 | 主要验收点 |
| --- | --- | --- | --- | --- |
| 4 | 接入本地模型真实推理 | 高 | 大 | 预计 `1.1.0` 版实作。`utils.ai_model_middleware` 的 `local` backend 不再抛出未接线错误；模型页本地文本测试调用真实 llama.cpp；提取与角色卡编译可按统一中间件使用本地文本模型。首轮建议只接文本推理，本地图像/音频/视频多模态另列后续项。 |
| 5 | 强化跨内容形态证据消费体验 | 中 | 大 | 在保留现有 `source_metadata`、`source_trace` 和 `extraction_run_id` 的基础上，继续完善跨内容形态关联、证据可信度权重和角色卡页面中的证据可读 UI。 |
| 6 | 增强 transcript 后处理能力 | 低 | 中 | 在 episode transcript 基础上按需增加说话人识别、置信度、字幕导入合并或人工校正流程，不影响首版 Whisper 接入和 transcript-as-text 边界。 |
| 7 | 继续扩展首版以外的 API 规范 | 低 | 大 | 在多供应商首版稳定后，按优先级继续评估 OpenAI Responses、Gemini GenerateContent、Anthropic Messages 等 schema；每个 schema 需通过中间件路由和模型页测试验证后再开放。 |
| 8 | 增加剧集顺序人工调整或更复杂识别 | 低 | 中/大 | 当前仍按文件夹和文件名简单排序，不联网匹配番剧数据库；如真实项目需要，可先做人工排序 UI，再评估外部数据库匹配。 |
| 9 | 独立洞察页接入主窗口导航 | 低 | 小 | `gui/pages/insights_page.py` 已存在但未接入导航；如需要独立洞察页，再补导航入口、i18n 文案和页面状态同步。 |

## 加固与清理

| 顺序 | 待办 | 优先级 | 规模 | 主要验收点 |
| --- | --- | --- | --- | --- |
| 10 | 增加自更新下载包大小上限 | 中 | 小/中 | 在现有 HTTPS、精确资产名、SHA-256 校验、成员数量上限和解压后体积上限之外，增加下载阶段的压缩包体积限制和用户可读错误。 |
| 11 | 增加原生音频理解的大文件请求体保护 | 中 | 小/中 | native audio/video 补充 handler 在构造请求前限制或解释大文件风险；首选 transcript 路径不受影响。 |
| 12 | 明确目录导入递归深度策略 | 低 | 中 | 根据真实素材目录形态决定是否增加递归深度限制、提示或配置项；当前继续按既有导入规则处理。 |
| 13 | 清理 i18n 重复 key 和遗留占位文案 | 低 | 小 | 四个 i18n JSON 中 `project.inputFormat.7z` 存在重复 key；`project.processing.placeholder.*` 仍写“真实转码/分段下一步接入”，但 FFmpeg 管线已经接入，应删除未引用文案或改成当前事实。 |
| 14 | 补充模型页图片与视频测试素材来源记录 | 低 | 小 | 如后续需要更完整素材声明，补充原始 URL；或替换为新的自由素材并更新 `docs/reference/asset-material-declaration.zh_CN.md`。 |

## 已完成并移出队列

- 打包运行根目录修复完成：frozen/packaged Windows one-folder 运行时以 `CharaPicker.exe` 所在目录作为 `APP_ROOT`，自更新 relaunch cwd 同步使用安装目录；相关单测、Ruff 和统一离线回归已通过。
- 路线 01 提取质量与可观测性基础实施完成，正式提取回归、失败策略和可观察状态已建立。
- 路线 02 多媒体平级接入前重构完成：正式提取以 `FormalExtractionRunPlan` 为主索引，顶层媒体类型固定为 `video`、`image`、`audio`、`text`，transcript 作为 text 型派生成果处理。
- 路线 03 离线实现完成：普通文本、SRT/ASS、音频 transcript、PNG/JPEG/WEBP、漫画页组、视频 + 字幕关联和原生视听补充 handler 已进入统一扫描、预览、正式分派、聚合、角色卡证据和失败记录链路；`scripts/validate_multi_material_regression.py` 提供统一离线回归。
- 路线 03 多内容形态真实验收完成：视频、小说文本、独立图片、漫画目录、SRT 字幕、独立音频 transcript、视频 + 字幕、当前 run 聚合和非视频角色卡编译均已验证。
- 更多输入格式计划完成：ZIP、CBZ、EPUB、文本型 PDF、7z、RAR 与 CBR 已进入受控预处理、来源追踪、缓存复用和清理流程，完成记录见 [更多输入格式支持执行计划](../archive/input-format-support-plan.completed.zh_CN.md)。
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
