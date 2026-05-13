# AGENTS.md

This file is the default long-term project context for Codex in this repository. It must be usable on its own: future work must not depend on `.codex/` files unless the user explicitly asks to inspect them for a specific task.

## 1. Project snapshot

CharaPicker（拾卡姬）是一个 Python 桌面应用，用于从番剧、漫画、视频、图片或文本素材中提取角色相关信息，并生成结构化角色档案与洞察。

当前阶段是 `v0.1.0` 开发中：仓库已有可运行的 PyQt6 + qfluentwidgets UI 骨架、项目配置、素材导入/处理、云端模型预设、洞察流面板和预览链路；真实素材提取、知识库稳定落盘、角色状态迭代编译与冲突消解仍在持续完善。

当前主线任务是把 Extract Once 工作流做实：让素材处理结果可靠进入 `projects/{project_id}/knowledge_base/`，后续角色卡生成优先读取结构化 JSON，而不是反复分析原始素材。

## 2. Repository map

- `main.py`：应用入口，安装日志与 Qt 消息过滤器，创建 `QApplication`，应用主题并启动启动控制器。
- `core/`：核心业务模型与流程。`models.py` 定义 Pydantic 数据模型；`extractor.py` 负责素材扫描、知识库结构、chunk 洞察与预览提取；`compiler.py` 负责角色状态聚合/阶段状态；`generator.py` 负责输出渲染。
- `gui/`：PyQt6 + qfluentwidgets 界面层。`main_window.py` 组装页面和线程 worker；`pages/` 放项目、输出、模型、提示词、设置、关于等页面；`widgets/` 放洞察流、弹窗外壳和流式文本控件。
- `utils/`：跨模块中间件与工具，包括 i18n、路径、项目配置、全局配置、主题、日志、素材导入/处理、FFmpeg、模型调用、提示词覆盖和启动预热。
- `i18n/`：用户可见文本的多语言 JSON，当前基础语系为 `zh_CN`、`zh_TW`、`en_US`、`ja_JP`。
- `res/`：运行时资源标识、颜色常量、默认 prompt 和固定测试素材；不放用户可见文案。
- `docs/`：用户与开发者文档，包括多语言 README、提取工作流说明、开发路线和专项接入计划。
- `projects/`：本地用户工程数据根目录，按 `project_id` 隔离配置、原素材、可处理素材、缓存、知识库和输出。默认不应提交用户数据。
- `bin/`、`models/`：本地外部工具和模型文件位置，通常不提交实际二进制或权重。
- `scripts/`、`build.bat`、`main.spec`、`.github/`：构建元数据、Windows PyInstaller 打包和 GitHub Actions 编排。

## 3. Canonical project knowledge

- 核心产品原则是 Extract Once、Targeted Insight、Iterative Compilation 和 Visible Thinking。
- 项目级数据通过 `utils.paths.ensure_project_tree()` 创建标准结构：`raw/`、`materials/`、`cache/`、`knowledge_base/`、`output/` 和 `config.json`。
- `raw/` 保存可重新处理的源副本；`materials/` 保存当前处理管线实际消费的素材入口。清理 `raw/` 前必须确认 `materials/` 中已有可用素材，并把清理状态写回项目配置。
- 当前结构化模型集中在 `core/models.py`，新增业务数据结构应优先放在那里并保持 Type Hints。
- 当前代码已经支持按季/集/chunk 初始化和写入 `knowledge_base/seasons/.../episodes/.../chunks/*.json`，并能合并生成 `episode_content.json`、`episode_summary.json`、`season_content.json`、`season_summary.json`。`facts.json` 和 `targeted_insights.json` 仍作为项目初始化/早期结构存在，遇到知识库任务时要核对当前代码和文档。
- 预览链路由 `gui.main_window.PreviewWorker` 在线程中调用 `core.extractor.Extractor.run_preview_streaming()`。当前预览最多处理前 2 个 chunk，并依赖云端模型预设；没有可读 chunk/视频结果时会发出警告事件。
- 主窗口预览成功后，当前输出页仍使用 `compile_character_state()` 的简化占位角色状态生成 Markdown。不要把完整迭代编译误认为已经全部实现。
- 所有模型请求应通过 `utils.ai_model_middleware` 进入后端。当前支持 OpenAI-compatible 和 DashScope 路径；本地模型执行入口存在但尚未真正接线。
- `InsightStreamPanel` 只展示用户关心的结构化洞察事件，不展示普通调试日志。日志通过 `utils.logging_middleware` 写入 `log/`。
- UI 可见文本必须走 `i18n/`；UI 颜色常量应先定义在 `res/colors.py`，再由界面代码引用。
- 产品文案可以轻微拟人化，但清晰度优先；错误、费用、清理素材、密钥等高风险场景必须直白。
- 长耗时任务应放入 Qt worker/thread；页面层负责触发、进度、取消和反馈，不承担 AI 推理或文件系统细节。

## 4. Documentation guidance

- 先看 `README.md`：了解当前状态、已实现内容、安装、运行和构建方式。
- 先看 `ARCHITECTURE.md`：了解当前仓库分层、入口、数据流和各子目录架构文档链接。
- 做核心业务改动时看 `core/ARCHITECTURE.md`、`projects/ARCHITECTURE.md`、`utils/ARCHITECTURE.md`。
- 做 UI 或交互改动时看 `gui/ARCHITECTURE.md`、`i18n/ARCHITECTURE.md`、`res/ARCHITECTURE.md`。
- 做文档或路线相关改动时看 `docs/ARCHITECTURE.md`。
- 做产品语气、UI 体验、洞察流、混合媒体或成本控制相关改动时看 `docs/product-design-guidelines.zh_CN.md`。
- `docs/extraction-workflow.zh_CN.md` 描述目标工作流和领域模型，可用于理解 Extract Once、季/集/chunk、上下文优先级和角色卡生成思路；它不是全部已实现证明。
- `docs/extraction-development-roadmap.zh_CN.md` 是开发路线，默认当作计划和验收依据，不要直接当作当前代码事实。
- `docs/preview-real-result-ingestion-plan.zh_CN.md` 是专项计划，部分内容可能已被当前代码推进或替代；实施前必须重新核对 `core/extractor.py` 和相关 UI 代码。
- 做运行时中间件改动时看 `docs/runtime-middleware.zh_CN.md`。
- 做打包、版本、发布包结构或 CI 发布改动时看 `docs/release-packaging.zh_CN.md`。
- 做 README、多语言文档、架构说明维护时看 `docs/documentation-maintenance.zh_CN.md`。
- `.codex/` 不应作为后续长期工作流依赖。未来进入仓库时以本 `AGENTS.md` 和普通项目文档为默认依据。

冲突处理优先级：

1. 当前代码、工程配置和实际文件结构。
2. 根目录 `README.md`、`ARCHITECTURE.md` 与相关子目录 `ARCHITECTURE.md`。
3. `docs/extraction-workflow.*` 等稳定设计说明。
4. roadmap、专项计划和历史方案。

低优先级文档可以提供方向，但不能覆盖当前代码事实。若优先级相近的来源互相矛盾，先向用户说明冲突和建议处理方式。

## 5. Development commands

主要开发环境偏向 Anaconda，默认环境名是 `CharaPicker`。日常命令可优先包一层 `conda run -n CharaPicker ...`。

- Install: `python -m pip install -r requirements.txt`
- Dev: `python main.py`
- Build: `build.bat`
- Build examples: `build.bat --tag=v0.1.0-alpha.1`、`build.bat --version=0.1.0 --stage=release`、`build.bat --local`
- Lint: `pyproject.toml` 配置了 Ruff（`line-length = 100`，`target-version = "py310"`），但 `requirements.txt` 未声明 Ruff；若环境中已安装，可运行 `python -m ruff check .`
- Typecheck: 仓库未发现独立 typecheck 配置或固定命令。
- Test: 仓库未发现测试目录、pytest 配置或固定测试命令。

本仓库没有发现 `package.json`、lockfile 或 `tsconfig`；不要按 JS/TS 项目假设工作流。

## 6. Working rules for Codex

- 不得只凭局部片段、目录名或旧记忆推断全局事实。非琐碎任务必须先定位相关代码和相关文档，再下结论。
- 若文档与代码冲突，必须显式指出冲突、说明采用依据，不得静默裁决。
- 不得把 roadmap、专项计划或历史建议当成当前已经实现的功能。
- 不得无计划地跨模块大改。跨 `core`、`gui`、`utils`、`projects` 边界的改动要先说明目标、范围和风险。
- 架构变更、大范围重构或会改变后续开发方式的任务，在没有用户明确同意前只能完成理解、分析和方案，不直接落地代码。
- 不得为了“看起来更优雅”而做无收益的大规模抽象；优先沿用现有结构和中间件。
- 不得擅自引入新依赖。确需新增依赖时，先说明用途、替代方案、影响范围和更新位置。
- 不得静默改变现有用户可见行为、核心业务语义、知识库结构或项目数据迁移规则。
- `projects/`、`config.yaml`、`log/`、`bin/` 和 `models/` 默认视为本地运行时或用户私有数据区域；除非任务明确要求，不把它们当作普通源码改动对象。
- 改 UI 时保持 qfluentwidgets/Fluent 风格，优先使用社区版已有组件；用户可见文案同步维护四个 i18n JSON；颜色先进入 `res/colors.py`。
- 改模型调用、prompt 或提取/编译流程时，必须保持 `utils.ai_model_middleware` 作为统一入口，不绕过中间件直连后端。
- 改素材处理时，页面层不应直接复制、删除或重命名项目素材；优先通过 `utils.source_importer` 和 `utils.material_processing_middleware`。
- 日志使用标准 `logging.getLogger(__name__)`；不要用普通日志替代洞察流，也不要在日志中输出 API Key、完整密钥、隐私文本或大型原始素材内容。
- 增加主要目录、改变目录职责或改变长期数据结构时，同步考虑是否要更新对应 `ARCHITECTURE.md`。
- 修改打包逻辑时保持 PyInstaller one-folder 形态和 zip 顶层 `CharaPicker/` 结构；版本、阶段和文件命名规则先核对 `docs/release-packaging.zh_CN.md`。
- 如果用户要求提交 commit，提交信息遵循 Conventional Commits，并使用 `git commit -s` 签名。

## 7. Refactor and architecture-change protocol

以下任务默认必须先规划再实施：代码结构整理、架构分析、大范围重构、跨模块改动、会影响后续开发方式的调整。

默认流程：

1. 先理解现状：读相关代码、架构文档和当前数据/调用链。
2. 明确问题与目标：区分 bug、缺口、技术债和风格偏好。
3. 给出分阶段方案：每个阶段有清晰边界、预期结果和验证方式。
4. 等用户同意后再实施。
5. 每次只执行一个清晰阶段。
6. 阶段完成后运行相关验证；若无法验证，说明原因。
7. 汇报改动、结果、风险、偏差和下一步建议。

## 8. Definition of done

重要修改完成后，默认汇报：

- 改了什么，涉及哪些文件或模块。
- 为什么这样改，如何符合当前架构和用户目标。
- 运行了哪些验证命令，以及结果。
- 已知风险、未解决问题或仍需用户确认的取舍。
- 如果改变了长期项目事实、模块边界、工作流或数据结构，提示是否应更新 `AGENTS.md` 或相关普通项目文档。

## 9. AGENTS.md maintenance policy

- `AGENTS.md` 是长期项目指导文件，不记录临时任务进度、一次性计划或短期 TODO。
- Codex 不得擅自修改 `AGENTS.md`。
- 当用户明确指出长期有效的项目规则、反复出现的误判、应长期记住的工作约束，或已经稳定下来的架构事实时，Codex 可以建议将其沉淀到 `AGENTS.md`。
- 修改 `AGENTS.md` 前，必须先向用户说明：建议新增或修改什么、为什么值得长期沉淀、将修改哪个章节。
- 只有在用户明确允许后，才能修改 `AGENTS.md`。
- 修改时保持简洁，优先保留长期稳定、频繁复用、高价值的信息，避免文件持续膨胀。
- 若某条规则只适用于单个专项任务，应优先写入专项文档，而不是 `AGENTS.md`。
