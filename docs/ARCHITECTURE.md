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

## 关键文件

- `README.md`：`docs/` 的文档索引和导航入口。
- `extraction-workflow.zh_CN.md`：面向用户和研究者的提取工作流技术说明，简体中文版本。
- `extraction-workflow.zh_TW.md`：面向用户和研究者的提取工作流技术说明，繁体中文版本。
- `extraction-workflow.en_US.md`：面向用户和研究者的提取工作流技术说明，英语版本。
- `extraction-workflow.ja_JP.md`：面向用户和研究者的提取工作流技术说明，日语版本。
- `extraction-development-roadmap.zh_CN.md`：面向开发者的提取与角色成长编译开发路线。
- `preview-real-result-ingestion-plan.zh_CN.md`：面向开发者的真实预览结果接入计划。
- `product-design-guidelines.zh_CN.md`：产品定位、产品语气、UI/i18n/资源规范、InsightStreamPanel 和混合媒体成本控制规范。
- `runtime-middleware.zh_CN.md`：全局存储、日志、弹窗、启动预热、素材处理和 AI 模型调用中间件的设计边界。
- `release-packaging.zh_CN.md`：PyInstaller、版本阶段、发布包结构和 CI 发布规范。
- `documentation-maintenance.zh_CN.md`：README、多语言文档、ARCHITECTURE.md 和计划类文档维护规则。
- `TODO.zh_CN.md`：后续体验、工作流、品牌和网络能力的待办清单。
- `archive/`：已执行完成、已被替代或仅保留历史查阅价值的计划类文档。
- `README.en_US.md`、`README.ja_JP.md`、`README.zh_TW.md`：README 的多语言补充版本。
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
- 计划类文档可能随代码演进而过期；如发现与当前代码冲突，应在文档中显式标注状态，已完成或已替代的一次性计划应移入 `archive/`。
- 不要把运行时配置或用户数据写入 `docs/`。
