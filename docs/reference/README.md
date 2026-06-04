# 参考文档

最近整理日期：2026-06-04。

本目录存放长期有效、但不直接作为执行计划排期入口的参考材料、声明和规范补充。简体中文文档默认是维护主版本；多语言参考文档用于读者补充阅读，涉及实现判断时优先核对中文主版本和当前代码。

## 先读入口

| 文件 | 用途 | 状态 |
| --- | --- | --- |
| `extraction-workflow.zh_CN.md` | Extract Once、季/集/chunk、知识库结构和角色卡生成思路 | 长期参考；部分实现细节需以代码为准 |
| `product-design-guidelines.zh_CN.md` | 产品语气、UI/i18n、洞察流和混合媒体成本控制 | 长期参考 |
| `runtime-middleware.zh_CN.md` | 全局存储、日志、弹窗、启动预热、素材处理、网络代理和 AI 模型调用边界 | 长期参考 |

## 补充与翻译

| 文件 | 用途 | 状态 |
| --- | --- | --- |
| `extraction-workflow.zh_TW.md` | 提取工作流繁體中文补充版 | 跟随 zh_CN 主版本维护 |
| `extraction-workflow.en_US.md` | Extraction Workflow English supplement | 跟随 zh_CN 主版本维护 |
| `extraction-workflow.ja_JP.md` | 抽出ワークフロー日本語補足版 | 跟随 zh_CN 主版本维护 |

## 维护、发布与声明

| 文件 | 用途 | 状态 |
| --- | --- | --- |
| `documentation-maintenance.zh_CN.md` | README、多语言文档、架构说明、计划和归档维护规则 | 长期维护规则 |
| `release-packaging.zh_CN.md` | PyInstaller、版本阶段、发布包结构和 CI 发布规范 | 发布参考 |
| `asset-material-declaration.zh_CN.md` | 随包测试素材、图标资源等来源与授权声明 | 声明材料 |

## 维护规则

- 涉及发布包随附素材、第三方资源、授权说明或长期引用材料时，优先放在本目录。
- 如果文档开始承担任务排期作用，应移入 `docs/plans/` 或新建专项计划。
- 如果某个参考文档只是已完成计划的历史记录，应移入 `docs/archive/`，不要继续留在 reference。
- reference 文件较多时先整理本索引和 `docs/README.md` 的阅读顺序；不要轻易移动已被 `AGENTS.md` 或架构文档引用的稳定路径。
