# CharaPicker 架构说明

## 负责什么

- 说明仓库根目录的整体分层和主要入口。
- 约束代码、资源、文档、项目数据和外部工具的放置位置。
- 提供跳转到各主要目录架构说明的相对链接。

## 不负责什么

- 不在根目录放业务推理实现。
- 不在根目录放 UI 页面实现。
- 不在根目录长期保存用户项目素材、模型文件或运行缓存。
- 不把打包产物、测试缓存和临时文件提交到源码结构中。

## 根目录关键文件

- `main.py`：应用入口。创建 `QApplication`，应用主题偏好，并启动启动控制器。
- `requirements.txt`：运行依赖声明。
- `pyproject.toml`：项目和工具配置。
- `config.yaml`：本地全局配置文件，由 `utils/global_store.py` 读写，包含用户偏好和模型预设等私有配置，默认不提交。
- `main.spec`：PyInstaller 文件夹式打包配置，收集 `i18n/`、`res/` 和 qfluentwidgets 资源。
- `build.bat`：Windows 打包入口。调用 `scripts/build_meta.py`，执行 PyInstaller，整理 `release/CharaPicker/` 并压缩 zip。
- `README.md`：GitHub 首页说明，要求使用简体中文。

## 子目录架构说明

- [core 架构](core/ARCHITECTURE.md)
- [gui 架构](gui/ARCHITECTURE.md)
- [utils 架构](utils/ARCHITECTURE.md)
- [i18n 架构](i18n/ARCHITECTURE.md)
- [res 架构](res/ARCHITECTURE.md)
- [doc 架构](doc/ARCHITECTURE.md)
- [projects 架构](projects/ARCHITECTURE.md)
- [bin 架构](bin/ARCHITECTURE.md)
- [models 架构](models/ARCHITECTURE.md)
- [scripts 架构](scripts/ARCHITECTURE.md)
- [.github 架构](.github/ARCHITECTURE.md)

## 当前数据流

1. `main.py` 安装全局日志和 Qt 消息过滤器，创建 `QApplication`，应用主题偏好，并进入启动流程。
2. `gui/splash_screen.py` 通过 `utils/startup_middleware.py` 在线程中预热工具状态、项目配置和云模型预设。
3. `gui/main_window.py` 组装项目页、输出页、模型页、提示词页、关于页和设置页，并连接信号。
4. `gui/pages/project_page.py` 收集项目名、目标角色、提取模式、素材路径和素材处理配置。
5. `utils/material_processing_middleware.py` 调度素材导入、工具校验和 ffmpeg 处理；`utils/source_importer.py` 维护 `raw/` 与 `materials/`。
6. `utils/state_manager.py` 将项目配置保存到 `projects/{project_id}/config.json`。
7. `gui/main_window.py` 使用 `PreviewWorker` 在线程中调用 `core/extractor.py` 的流式预览。
8. `core/extractor.py` 通过 `utils/ai_model_middleware.py` 调用模型，写入知识库分层 JSON，并产出结构化洞察事件与 token 用量。
9. 洞察事件以 `dict` 形式通过 Qt Signal 推送到 `InsightStreamPanel`。
10. `core/compiler.py` 可按季/集聚合知识库，生成阶段性角色状态；主窗口当前仍使用简化角色状态生成输出预览。
11. `core/generator.py` 将角色状态渲染为 Markdown，并交给输出页展示。

## 维护注意事项

- 新增主要目录时，同步增加对应的 `ARCHITECTURE.md`。
- 修改模块职责时，同步更新根目录和对应子目录的说明。
- UI 可见文案必须放在 `i18n/`，不要长期硬编码在界面代码中。
- UI 颜色标识先放入 `res/colors.py`，界面代码再引用。
- 保持 `core`、`gui`、`utils` 的职责边界清楚。
- 打包元数据逻辑放在 `scripts/`；GitHub Actions 只编排构建，不承载应用运行逻辑。
