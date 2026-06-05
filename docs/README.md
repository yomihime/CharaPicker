# CharaPicker 文档索引

最近整理日期：2026-06-05。

`docs/` 是 CharaPicker 的正式专题文档目录。根目录 `README.md` 负责项目首页说明；根目录和各主要代码目录中的 `ARCHITECTURE.md` 负责就近说明目录职责。已完成的一次性开发计划默认移入 `archive/`，稳定说明放入 `reference/`，仍有效路线和当前后续队列放入 `plans/`。

## 入口与多语言

- [README 多语言补充分组](readme/README.md)
- [繁體中文 README](readme/README.zh_TW.md)
- [日本語 README](readme/README.ja_JP.md)
- [English README](readme/README.en_US.md)

## 稳定说明

- [参考文档分组](reference/README.md)：按“先读入口、领域设计、运行规范、维护/发布、声明材料”整理的 reference 导航。
- [提取工作流说明](reference/extraction-workflow.zh_CN.md)：Extract Once 与知识库设计的默认中文参考。
- [产品与设计规范](reference/product-design-guidelines.zh_CN.md)：产品语气、UI、洞察流和混合媒体成本控制。
- [运行时中间件设计说明](reference/runtime-middleware.zh_CN.md)：全局存储、日志、弹窗、启动预热、素材处理、网络代理和 AI 模型调用边界。

## 剩余项目队列

以下顺序按“先稳住当前正式提取链路，再做多素材前解耦，最后推进多素材种类支持”整理。实施前仍必须重新核对当前代码和相关架构文档。

1. [当前计划与任务队列分组](plans/README.md)：仍需执行或持续跟踪的计划类文档入口。
2. [TODO List](plans/TODO.zh_CN.md)：当前剩余任务总表，已移出完成的历史项目。
3. [提取质量与可观测性计划框架](plans/extraction-quality-observability-plan.framework.zh_CN.md)：TODO P1 的框架占位，正式执行前需重新扩写计划。
4. [多素材平级接入前重构解耦计划框架](plans/multi-material-refactor-plan.framework.zh_CN.md)：第二阶段架构体检与解耦的框架占位。
5. [多素材种类支持计划框架](plans/multi-material-coverage-plan.framework.zh_CN.md)：TODO P0 的框架占位，正式执行前需结合第二阶段结果扩写计划。
6. [提取与角色成长编译路线](plans/extraction-development-roadmap.zh_CN.md)：Extract Once、知识库和角色状态编译的长期目标与验收基准。
7. [真实预览结果后续计划](plans/preview-real-result-ingestion-plan.zh_CN.md)：文本/字幕/音频、图片/漫画和混合媒体进入预览与统一知识库消费路径的后续专项计划。

## 发布与维护

- [打包与发布规范](reference/release-packaging.zh_CN.md)
- [文档维护规范](reference/documentation-maintenance.zh_CN.md)

## 多语言补充与声明

- [Extraction Workflow](reference/extraction-workflow.en_US.md)
- [提取工作流说明（繁體中文）](reference/extraction-workflow.zh_TW.md)
- [抽出ワークフロー説明](reference/extraction-workflow.ja_JP.md)
- [素材来源与授权声明](reference/asset-material-declaration.zh_CN.md)

## 历史归档

- [归档说明](archive/README.md)
- [代码结构整理执行计划](archive/refactor-plan.md)
- [正式视频提取架构指南与任务计划](archive/formal-video-extraction-architecture-plan.zh_CN.md)
- [真实预览结果接入计划完成记录](archive/preview-real-result-ingestion-plan.completed.zh_CN.md)
- [角色卡最终编译与角色卡页面计划](archive/character-card-compilation-plan.completed.zh_CN.md)
- [角色卡质量后续执行计划完成记录](archive/character-card-quality-followup-plan.completed.zh_CN.md)
- [多供应商与多 API 规范接入计划完成记录](archive/multi-provider-api-support-plan.completed.zh_CN.md)
- [Proxy 运行时网络能力计划完成记录](archive/proxy-runtime-network-plan.completed.zh_CN.md)

## 目录说明

- [docs 架构说明](ARCHITECTURE.md)
- [根目录架构说明](../ARCHITECTURE.md)
- [Codex 长期项目指导](../AGENTS.md)
