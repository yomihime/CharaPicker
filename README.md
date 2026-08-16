# CharaPicker / 拾卡姬

<p align="center">
  <img src="res/app_icon.png" alt="CharaPicker logo" width="96">
</p>

[繁體中文](docs/readme/README.zh_TW.md) | [日本語](docs/readme/README.ja_JP.md) | [English](docs/readme/README.en_US.md)

## 这是什么

CharaPicker（拾卡姬）是一个个人实验性质的桌面工具。它尝试从番剧、漫画、视频、图片、音频和文本素材里整理角色相关信息，再把这些信息沉淀成可追踪的知识库和角色档案。

它不是成熟的商业软件，也不是可以直接托付重要资料的生产工具。这个项目很大程度上是纯 vibe coding：边试、边写、边重构，用 AI 协助把想法快速落到代码里。文档会尽量写清楚当前能做什么、哪里还不稳，以及使用时需要自己判断的风险。

## 我想解决的问题

- 素材不要反复分析。一次处理后，结果应该尽量进入可复用的知识库。
- 角色卡不要只靠一次大模型自由发挥。后续生成应优先读取结构化结果和证据。
- 长任务不能像黑盒。提取、跳过、失败和整理过程应该在界面里有可读的反馈。

## 当前状态

- 当前处于 1.0 RC（发布候选）阶段，正在验证首个稳定基线；它还不是最终稳定版，提取质量和少量数据契约仍可能调整。
- 官方二进制目前只发布 Windows x64 包；源码运行支持 Python `>=3.10`，正式发布包使用锁定的 Windows 构建环境。
- 最新发布包和每个版本的变化请看 [GitHub Releases](https://github.com/yomihime/CharaPicker/releases) 与 [更新日志](CHANGELOG.md)。

## 现在能做什么

- 建项目、导入素材，并把原始素材保留在 `raw/`，处理后的入口放到 `materials/`。
- 扫描视频、图片、音频和文本四类素材，生成预览或正式提取 run plan。
- 对 ZIP、CBZ、EPUB、文本型 PDF、7z、RAR、CBR 做受控预处理，再交给现有文本或图片链路。
- 通过统一模型中间件调用 OpenAI-compatible 或 DashScope 云端后端，并记录 token usage。
- 在洞察流面板里看到提取过程中的关键事件，而不是只看日志。
- 在角色卡页面管理项目内角色卡：创建、编辑、封面裁剪、预览、编译、导入和导出。
- 从正式知识库编译 CharaPicker JSON，并导出 Markdown、HTML、Character Card V2 JSON 和 AstrBot 手动复制清单。

## 还不稳的地方

- 真实素材提取质量还在打磨，尤其是跨集、跨媒体和长文本上下文。
- 角色卡冲突消解、质量评估和证据取舍仍需要更多样本验证。
- `facts.json`、`targeted_insights.json` 等早期知识库文件还没有形成稳定的自动写入闭环。
- 云端模型调用会产生费用，也可能失败、拒绝或产生幻觉；重要角色事实需要人工复核。
- 本地模型执行入口尚未真正接线；下载器、运行时探测或界面占位不等于已经支持本地推理。

## 数据、隐私与更新

- `projects/` 是用户数据根目录。应用会对关键配置和角色卡保留一份最近有效备份，并在检测到损坏时提供恢复入口，但这不是完整备份方案；重要升级前仍应自行复制 `projects/` 和 `config.yaml`。
- 更新器会尽量保留 `projects/`、`config.yaml`、`log/`、`bin/` 和 `models/`，并在启动确认失败时回滚；断电、磁盘故障或手工移动文件仍可能超出自动恢复范围。
- `config.yaml` 可能包含 API Key，目前保存在本地应用目录，没有使用系统凭据库加密。不要分享该文件，也不要把它提交到版本控制。
- 发送给云端模型的素材会离开本机，并受所选供应商的计费、隐私和内容策略约束；请只处理你有权使用的素材。
- 官方下载入口只有本项目的 [GitHub Releases](https://github.com/yomihime/CharaPicker/releases)。当前 Windows 二进制没有 Authenticode 签名，Windows 可能显示未知发布者或 SmartScreen 提示。
- 同名 `.sha256` 用于核对下载字节；GitHub artifact attestation 用于核对 GitHub Actions 构建来源。两者都不等同于 Windows 发布者签名，详细验证命令见[打包与发布规范](docs/reference/release-packaging.zh_CN.md)。

## 环境要求

- Python `>=3.10`
- 官方 Windows x64 发布包不需要另行安装 Python。
- 主要依赖：
  - `PyQt6>=6.6`
  - `PyQt6-Fluent-Widgets>=1.5`
  - `pydantic>=2.6`
  - `pypdf>=6.14.2,<7`

## 支持的输入

- 直接素材：常见视频、静态图片、音频、TXT/Markdown/JSON、SRT/ASS 等格式。
- 受控预处理：`.zip`、`.cbz`、`.epub`、`.pdf`、`.7z`、`.rar`、`.cbr`。
- PDF 首版只提取已有文本，不执行 OCR；加密 PDF、DRM EPUB 和密码归档会被明确拒绝。
- 7z/RAR/CBR 需要本地 7-Zip。应用依次查找 `bin/7zip/7z.exe`、`bin/7z.exe`、`PATH`、Windows 标准安装目录，也可通过 `CHARAPICKER_7ZIP_PATH` 指定；应用不自动下载该工具。
- 嵌套容器不会递归展开，只记录 warning；原容器保留在 `raw/`，派生素材和来源映射分别进入 `materials/derived_inputs/` 与预处理 manifest。
- 通用 ZIP/7z/RAR 内的视频不会被展开；视频必须作为独立素材显式导入。CBZ/CBR 继续只接纳漫画图片页。
- 非原始处理方案只在选中了直接视频时需要 FFmpeg。缺少 FFmpeg 时可取消、忽略全部视频并继续处理其它素材，或下载 FFmpeg 后自动执行。
- 音视频对白事实优先来自字幕或 Whisper transcript；原生音视频理解只补充视听线索，且是否可用取决于供应商、API schema 和具体模型。

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
  - `build.bat --tag=vX.Y.Z-beta`
  - `build.bat --version=X.Y.Z --stage=beta`
  - `build.bat --local`

## 主要功能

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
- [GitHub Releases](https://github.com/yomihime/CharaPicker/releases)
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
