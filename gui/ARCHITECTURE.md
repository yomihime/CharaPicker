# gui 架构说明

## 负责什么

- 承载 PyQt6 + qfluentwidgets 的桌面界面。
- 组装主窗口、启动页、业务页面和复用控件。
- 负责用户交互、信号连接、界面展示和反馈提示。
- 展示来自 `core` 的结构化洞察事件。

## 不负责什么

- 不负责 AI 推理、媒体解析或角色状态编译。
- 不直接写入知识库 JSON。
- 不长期硬编码用户可见文案。
- 不直接定义业务模型。

## 关键文件

- `main_window.py`：主窗口。创建页面、导航项、`Extractor`，并连接预览、保存配置、主题和语言信号。
- `splash_screen.py`：启动流程和启动界面。
- `pages/project_page.py`：项目配置页。收集目标角色、提取模式和素材路径，并展示洞察流。
- `pages/output_page.py`：角色卡 Markdown 预览页。
- `pages/settings_page.py`：语言、主题和推理后端等设置页。
- `pages/about_page.py`：项目信息和注意事项页面。
- `pages/insights_page.py`：独立洞察页组件，当前未接入主窗口导航。
- `widgets/insight_stream_panel.py`：洞察流组件，使用 Card + Timeline 展示结构化事件。

## 与其他目录的关系

- 调用 `core.extractor.Extractor` 启动预览提取。
- 调用 `core.compiler` 和 `core.generator` 生成当前的角色卡预览。
- 调用 `utils.state_manager` 保存和读取项目配置。
- 调用 `utils.i18n.t()` 获取所有 UI 可见文案。
- 从 `res.colors` 读取界面颜色标识。

## 维护注意事项

- 新增页面时放入 `gui/pages/`，复用控件放入 `gui/widgets/`。
- 用户可见文案必须新增到 `i18n/*.json`。
- 新增颜色先维护 `res/colors.py`，再在界面中引用。
- `InsightStreamPanel` 只展示关键洞察，不展示普通调试日志。
- Qt Signal 传输的数据尽量保持为可序列化 `dict`。

Dialog middleware note:

- `widgets/dialog_middleware.py` owns the shared Fluent dialog shell.
- New app-owned modal dialogs should reuse it for the frameless window, translucent background, Card container, title bar, close button, margins, and spacing.
- Native platform dialogs, such as file pickers, can stay as direct Qt calls.
