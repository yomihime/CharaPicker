# docs 历史归档

这里存放已经执行完成、被当前代码或新文档替代，或主要只保留历史查阅价值的计划类文档。

归档文档不再作为默认开发入口；如果后续任务需要引用其中的背景，必须先核对当前代码、根目录 `README.md`、相关 `ARCHITECTURE.md` 和仍在主目录中的稳定说明。

## 已归档文档

- [代码结构整理执行计划](refactor-plan.md)：所有计划里程碑已于 2026-05-13 完成，保留为历史阶段记录。
- [正式视频提取架构指南与任务计划](formal-video-extraction-architecture-plan.zh_CN.md)：S1-S7 正式视频提取 MVP 已于 2026-05-15 完成，保留为架构演进和验收记录。
- [真实预览结果接入计划完成记录](preview-real-result-ingestion-plan.completed.zh_CN.md)：视频 chunk 真实预览、`preview__` 产物隔离和早期预览计划已完成部分的历史记录。
- [角色卡最终编译与角色卡页面计划](character-card-compilation-plan.completed.zh_CN.md)：角色卡页面、CharaPicker JSON 母本、封面裁剪、预览、编译、导入、导出和 AstrBot 手动复制辅助已完成基础生命周期，保留为历史阶段记录。
- [角色卡质量后续执行计划完成记录](character-card-quality-followup-plan.completed.zh_CN.md)：角色卡编译上下文分层、AI 别名重分类、结构化复核原因、冲突分组、质量诊断和本轮真实素材调优已阶段性完成。
- [多供应商与多 API 规范接入计划完成记录](multi-provider-api-support-plan.completed.zh_CN.md)：供应商 endpoint、API 规范、视频输入方式、DashScope 原生音频测试、Whisper 管理和音频转写首版已完成，保留为本阶段验收记录。
- [Proxy 运行时网络能力计划完成记录](proxy-runtime-network-plan.completed.zh_CN.md)：内置代理设置、统一网络中间件、连通性测试、DashScope 临时代理环境和相关文档同步已完成，保留为本阶段验收记录。
- [正式素材详细提取流程与模式计划完成记录](formal-extraction-modes-and-context-plan.completed.zh_CN.md)：完整提取、洁净提取、快速提取、线性上下文、AI 集/季整理、run 隔离、stale 标记和角色卡别名解析已阶段性完成；角色卡质量与日志治理已由后续分支接续完成，更完整的正式提取回归验证仍在当前 TODO 跟踪。
- [提取质量与可观测性执行计划完成记录](01-extraction-quality-observability-plan.completed.zh_CN.md)：路线 01 已完成，正式提取回归、失败策略和可观察状态已建立；长期 prompt 与进度监测留在当前 TODO 跟踪。
- [多媒体平级接入前重构解耦执行计划完成记录](02-multi-material-refactor-plan.completed.zh_CN.md)：路线 02 已完成，正式提取已转向 `FormalExtractionRunPlan`、通用 unit、派生成果和四媒体类型边界。
- [番剧、漫画、广播剧、小说等内容形态支持执行计划完成记录](03-multi-material-coverage-plan.completed.zh_CN.md)：路线 03 已完成 M19 收尾，多内容形态扫描、预览、正式分派、知识库证据、真实验收和文档同步均已落地。
- [真实预览结果后续计划完成记录](preview-real-result-followup-plan.completed.zh_CN.md)：原文本、字幕、音频转写、图片/漫画和视频+字幕预览覆盖计划已被路线 03 吸收；当时遗留的容器导入缺口已由更多输入格式计划完成。
- [更多输入格式支持执行计划完成记录](input-format-support-plan.completed.zh_CN.md)：ZIP、CBZ、EPUB、文本型 PDF、7z、RAR 与 CBR 的受控预处理、来源追踪、安全边界和全量回归已完成。
