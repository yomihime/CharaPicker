# CharaPicker / 拾卡姬

<p align="center">
  <img src="res/app_icon.png" alt="CharaPicker logo" width="96">
</p>

[繁體中文](docs/readme/README.zh_TW.md) | [日本語](docs/readme/README.ja_JP.md) | [English](docs/readme/README.en_US.md)

## 项目简介

CharaPicker（拾卡姬）是一个面向二次元素材分析的桌面工具，用于从番剧、漫画、视频、图片或文本中提取角色相关信息，并生成结构化角色档案与洞察。

## 核心目标

- Extract Once：素材尽量只处理一次，沉淀可复用知识库。
- Targeted Insight：围绕指定角色或世界观输出定向洞察。
- Visible Thinking：在界面中展示关键洞察流，而不只是调试日志。

## 当前状态

- 当前版本：`v0.6.0-beta.1`（开发中）
- 文档更新时间：`2026-06-05`

## 已实现内容

- 启动流程与预热链路：启动页、主题应用、基础环境探测。
- 主界面骨架：项目页、角色卡页、模型页、提示词页、设置页、关于页。
- 项目配置管理：项目配置保存/读取、最近项目列表。
- 素材处理链路：导入 `raw/`、链接/处理到 `materials/`，支持 FFmpeg 分段与转码配置。
- 洞察流界面：InsightStreamPanel 卡片时间线展示与流式更新。
- 云端模型接入：通过统一中间件发起 OpenAI-compatible 请求并记录 token usage。
- 预览链路打通：`project -> extractor -> insight stream -> preview knowledge base`。
- 角色卡页面：支持项目内角色卡海报墙、搜索、创建、编辑、封面裁剪、预览、编译、导入和导出。

## 项目进展

- 已完成：可运行的 UI 骨架与预览主流程。
- 进行中：从真实素材生成更高质量、可复用的结构化洞察。
- 下一阶段重点：知识库质量提升、编译阶段状态迭代、冲突处理与角色卡输出质量打磨。

## 未完成项

- 真实素材预览已开始接入 `materials/` 中的视频 chunk 和云端模型，但文本、字幕、漫画/图片等完整真实素材消费链路仍在完善。
- 角色卡编译已能从正式知识库生成 CharaPicker JSON，但完整迭代编译、冲突消解和质量评估仍需继续完善。
- 知识库文件（如 `facts.json`、`targeted_insights.json`）尚未形成稳定自动写入闭环。

## 环境要求

- Python `>=3.10`
- 主要依赖：
  - `PyQt6>=6.6`
  - `PyQt6-Fluent-Widgets>=1.5`
  - `pydantic>=2.6`

## 安装

```powershell
python -m pip install -r requirements.txt
```

## 运行

```powershell
python main.py
```

## 构建

```powershell
build.bat
```

- 产物输出到 `release/` 目录。
- 常用参数示例：
  - `build.bat --tag=v0.6.0-beta.1`
  - `build.bat --version=0.6.0 --stage=beta.1`
  - `build.bat --local`

## 功能概览

- 项目化素材管理（`projects/{project_id}`）
- 素材提取模式配置
- 项目内角色卡管理与 CharaPicker JSON 母本
- 提取阶段洞察事件流（Insight Stream）
- 角色卡 Markdown、HTML、Character Card V2 JSON 和 AstrBot 手动复制清单导出（持续迭代中）

## 截图

- 截图文档待补充。

## 文档导航

- [繁體中文 README](docs/readme/README.zh_TW.md)
- [日本語 README](docs/readme/README.ja_JP.md)
- [English README](docs/readme/README.en_US.md)
- [更新日志](CHANGELOG.md)
- [Codex 长期项目指导](AGENTS.md)
- [根目录架构说明](ARCHITECTURE.md)
- [项目文档索引](docs/README.md)
- [docs 架构说明](docs/ARCHITECTURE.md)
- [提取工作流说明](docs/reference/extraction-workflow.zh_CN.md)
- [提取与角色成长编译路线](docs/plans/extraction-development-roadmap.zh_CN.md)
- [产品与设计规范](docs/reference/product-design-guidelines.zh_CN.md)
- [运行时中间件设计说明](docs/reference/runtime-middleware.zh_CN.md)
- [打包与发布规范](docs/reference/release-packaging.zh_CN.md)
- [文档维护规范](docs/reference/documentation-maintenance.zh_CN.md)

## 开发说明

- 本项目遵循目录边界：`core` / `gui` / `utils` 分层清晰。
- UI 可见文本应通过 `i18n/` 管理，避免长期硬编码。
- 运行时资源统一放在 `res/`。

## 许可证

- CharaPicker 自有源码采用 [Mozilla Public License 2.0](LICENSE)（`MPL-2.0`）。
- 第三方依赖和打包产物中的第三方组件遵循各自许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
- 当前开源构建使用 GPL 许可的 PyQt6 / PyQt6-Fluent-Widgets 组件；发布二进制包时需要同时遵守这些第三方许可证义务。
