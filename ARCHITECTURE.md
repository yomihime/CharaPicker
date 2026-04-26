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
- `config.yaml`：预留的全局配置文件。
- `main.spec`：PyInstaller 打包配置预留文件。
- `build.bat`：Windows 打包入口预留文件。
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

## 当前数据流

1. `main.py` 创建应用并进入启动流程。
2. `gui/main_window.py` 组装窗口、页面和信号连接。
3. `gui/pages/project_page.py` 收集项目名、目标角色、提取模式、素材路径和素材处理配置。
4. `utils/source_importer.py` 将外部素材导入 `projects/{project_id}/raw/`，并按处理方案准备 `materials/`。
5. `utils/state_manager.py` 将项目配置保存到 `projects/{project_id}/config.json`。
6. `core/extractor.py` 在预览阶段产出结构化洞察事件。
7. 洞察事件以 `dict` 形式通过 Qt Signal 推送到 `InsightStreamPanel`。
8. `core/compiler.py` 生成占位 `CharacterState`。
9. `core/generator.py` 将角色状态渲染为 Markdown，并交给输出页展示。

## 维护注意事项

- 新增主要目录时，同步增加对应的 `ARCHITECTURE.md`。
- 修改模块职责时，同步更新根目录和对应子目录的说明。
- UI 可见文案必须放在 `i18n/`，不要长期硬编码在界面代码中。
- UI 颜色标识先放入 `res/colors.py`，界面代码再引用。
- 保持 `core`、`gui`、`utils` 的职责边界清楚。
