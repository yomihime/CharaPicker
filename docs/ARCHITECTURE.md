# docs 架构说明

## 负责什么

- 放置面向用户和开发者的扩展说明文档。
- 承载 README 之外的多语言文档、设计说明和发布说明。
- 记录不属于运行时代码的项目知识。

## 不负责什么

- 不放 Python 运行时代码。
- 不放 UI 文案源文件。
- 不放运行时资源和模型文件。
- 不保存项目素材、缓存或导出结果。

## 关键文件与分组

- `README.md`：`docs/` 的文档索引和导航入口。
- `reference/`：稳定参考材料、长期设计说明和声明类文档；`reference/README.md` 负责按阅读目的分组，避免 reference 文件过多时只能按文件名猜用途。
- `reference/extraction-workflow.*.md`：面向用户和研究者的提取工作流技术说明，多语言版本。
- `reference/product-design-guidelines.zh_CN.md`：产品定位、产品语气、UI/i18n/资源规范、InsightStreamPanel 和混合媒体成本控制规范。
- `reference/runtime-middleware.zh_CN.md`：全局存储、日志、弹窗、启动预热、素材处理、网络代理和 AI 模型调用中间件的设计边界。
- `reference/release-packaging.zh_CN.md`：PyInstaller、版本阶段、发布包结构和 CI 发布规范。
- `reference/documentation-maintenance.zh_CN.md`：README、多语言文档、ARCHITECTURE.md 和计划类文档维护规则。
- `plans/`：仍在执行或持续跟踪的任务队列、长期路线和专项计划。
- `plans/extraction-development-roadmap.zh_CN.md`：面向开发者的 Extract Once、知识库和角色成长编译长期路线；不是当前剩余任务清单。
- `plans/01-extraction-quality-observability-plan.zh_CN.md`：提取质量与可观测性的第一阶段执行计划。
- `plans/02-multi-material-refactor-plan.framework.zh_CN.md`：多素材平级接入前架构体检与解耦的第二阶段计划框架，只作为正式计划起草入口。
- `plans/03-multi-material-coverage-plan.framework.zh_CN.md`：文本、字幕、音频转写、图片、漫画和混合媒体支持的第三阶段计划框架，只作为正式计划起草入口。
- `plans/preview-real-result-ingestion-plan.zh_CN.md`：面向开发者的真实预览结果后续计划，当前聚焦文本、字幕、音频转写、图片、漫画和混合媒体接入预览与统一知识库消费路径。
- `readme/`：README 的多语言补充版本，例如 `README.en_US.md`、`README.ja_JP.md`、`README.zh_TW.md`。
- `archive/`：已执行完成、已被替代或仅保留历史查阅价值的计划类文档，包括已完成的正式视频提取、角色卡最终编译、角色卡质量分层、多供应商和 proxy 计划。
- 后续多语言文档应在文件名中标明语种，例如 `usage.zh_CN.md`。

## 与其他目录的关系

- 根目录 `README.md` 负责 GitHub 首页说明。
- `docs/` 负责更细的扩展说明和多语言补充文档。
- 根目录 `AGENTS.md` 负责 Codex 默认自动加载的长期项目指导。
- `.codex/CONTENT.md` 是历史 AI 协作上下文，不再作为正式文档入口。

## 维护注意事项

- 文档默认使用 UTF-8。
- 文档内容应短句清楚，优先说明边界、流程和限制。
- 多语言文档文件名必须能区分语种。
- 计划类文档可能随代码演进而过期；如发现与当前代码冲突，应在文档中显式标注阶段和可用性，已完成或已替代的一次性计划应移入 `archive/`。
- 不要把运行时配置或用户数据写入 `docs/`。
