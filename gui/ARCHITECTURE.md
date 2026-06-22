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

- `main_window.py`：主窗口。创建页面、导航项、`Extractor`，并连接预览、保存配置、项目切换、主题和语言信号。
- `insight_metadata.py`：无 Qt 依赖的洞察 metadata 显示映射，把 `media_type`、`content_form`、unit 和素材路径整理为本地化摘要；不判断提取能力或业务状态。
- `splash_screen.py`：启动流程和启动界面；在加载阶段通过子线程执行启动预热中间件，并在预热完成后创建主窗口。
- `pages/project_page.py`：项目配置页。负责项目选择、提取模式、素材路径和素材处理配置；启动异步素材导入；展示素材状态和洞察流；不再编辑目标角色。
- `pages/character_card_page.py`：角色卡页面。负责角色卡海报墙、搜索过滤、选择、新建、删除、元数据编辑、封面裁剪、预览、编译、预览草稿、导入和导出入口。
- `pages/model_page.py`：模型设置和连通性测试页。管理本地 llama.cpp 可用性、云模型预设、模型列表拉取，以及文本/图片/视频模型测试。
- `pages/model_test_helpers.py`：模型连通性测试页使用的纯 helper，负责 token 用量格式化、测试素材 data URL 和响应语言提示等逻辑。
- `pages/prompt_page.py`：提示词设置页。显示默认提示词，保存或清除用户自定义提示词覆盖。
- `pages/settings_page.py`：语言、主题和日志等级等应用设置页。
- `pages/about_page.py`：项目信息和注意事项页面。
- `pages/insights_page.py`：独立洞察页组件，当前未接入主窗口导航。
- `widgets/insight_stream_panel.py`：洞察流组件，使用 Card + Timeline 展示结构化事件，并把事件 `meta` 中的 `media_type`、`content_form`、unit 和素材名转换为本地化摘要；不自行判断提取能力或业务状态。
- `widgets/dialog_middleware.py`：应用自有 Fluent 弹窗外壳。
- `widgets/streaming_text_session.py`：把流式文本 delta 安全追加到 `QTextCursor`。
- `widgets/character_card_gallery.py`：角色卡海报墙/列表组件，只消费轻量 summary，不读取文件。
- `widgets/character_card_detail_panel.py`：当前角色卡元数据、状态和操作区，不直接落盘；读取 core 写入的结构化 `needs_review_reasons` 并转换为本地化提示，不直接暴露内部 reason key。
- `widgets/character_card_preview_dialog.py`：角色卡 HTML、Markdown、结构化 JSON、AstrBot 和 Card V2 预览弹窗。
- `widgets/human_json_view.py`：人类友好的结构化 JSON 展示组件。
- `widgets/cover_crop_dialog.py`：9:16 封面裁剪确认弹窗。
- `workers/character_card_workers.py`：角色卡编译、预览草稿、导入和导出的 Qt worker，只桥接信号与 core 调用。

## 与其他目录的关系

- 调用 `core.extractor.Extractor` 启动预览提取。
- 调用 `core.character_card_*` 模块管理、编译、预览、导入和导出 CharaPicker 角色卡；角色卡证据分层、别名校验、质量判断和导出字段映射均留在 core。
- 调用 `utils.state_manager` 保存和读取项目配置。
- 调用 `utils.cloud_model_presets`、`utils.cloud_models`、`utils.llamacpp_downloader` 和 `utils.ai_model_middleware` 支持模型页。
- 调用 `utils.source_importer` 导入外部素材、准备 `materials/`、清理 raw 和移除项目素材。
- 调用 `utils.source_status` 计算项目页素材显示名、raw/materials 映射和状态。
- 调用 `utils.prompt_preferences` 保存和读取用户自定义提示词覆盖。
- 调用 `utils.i18n.t()` 获取所有 UI 可见文案。
- 从 `res.colors` 读取界面颜色标识。

## 维护注意事项

- 新增页面时放入 `gui/pages/`，复用控件放入 `gui/widgets/`。
- 用户可见文案必须新增到 `i18n/*.json`。
- 新增颜色先维护 `res/colors.py`，再在界面中引用。
- `InsightStreamPanel` 只展示关键洞察和可解释 metadata，不展示普通调试日志；媒体类型、内容形态等可见标签必须走 i18n。
- Qt Signal 传输的数据尽量保持为可序列化 `dict`。
- 角色卡页面不直接拼接 `knowledge_base/character_cards/...` 路径，不直接做导出字段映射，也不自行判断 direct/mention/causal 证据；这些规则属于 core。
- 长耗时素材处理应放在线程 worker 中执行，页面只负责进度弹窗、取消信号和完成反馈。
- 启动阶段的耗时预加载应放在线程 worker 中执行，启动页完成前不要提前进入主窗口。

## 弹窗中间件说明

- `widgets/dialog_middleware.py` 负责共享 Fluent 弹窗外壳。
- 新增应用自有模态弹窗应复用它的无边框窗口、透明背景、Card 容器、标题栏、关闭按钮、边距和间距。
- 文件选择器等原生平台弹窗可以继续直接调用 Qt。
