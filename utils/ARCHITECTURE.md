# utils 架构说明

## 负责什么

- 放置跨模块复用的轻量工具。
- 管理本地化加载、路径计算、项目配置保存、全局配置存储、主题偏好、日志偏好和模型调用入口。
- 提供分块、环境检测和状态管理等通用能力。

## 不负责什么

- 不承载页面业务流程。
- 不创建完整 UI 页面。
- 不放用户可见文案内容。
- 不放运行时图片、图标或颜色表。

## 关键文件

- `i18n.py`：管理语言偏好、系统语言归一化、文案加载和 `t()` 翻译函数。
- `paths.py`：定义应用根目录、项目根目录和单个项目的标准目录结构。
- `global_store.py`：提供全局用户数据和配置选项的读写中间件，默认使用根目录 `config.yaml`。
- `state_manager.py`：保存、读取和列出项目配置，项目配置写入 `projects/{project_id}/config.json`。
- `theme.py`：管理主题偏好，并调用 qfluentwidgets 应用亮色、暗色或系统主题。
- `chunker.py`：预留文本或素材分块工具。
- `env_manager.py`：预留环境检测工具。
- `ffmpeg_tool.py`：封装 ffmpeg 工具探测、可用性校验与素材转码/分段执行（一个工具一个文件）。
- `cloud_model_presets.py`：保存和读取云端模型配置预设。
- `cloud_models.py`：拉取 OpenAI-compatible 云端模型列表。
- `llamacpp_downloader.py`：下载并安装 llama.cpp 运行时到 `bin/`。
- `ffmpeg_downloader.py`：下载并安装 ffmpeg 运行时到 `bin/`。
- `source_importer.py`：把外部原始素材按项目目录规则复制到 `projects/{project_id}/raw`，计算外部路径对应的 raw 目标，准备 `materials`，并支持 raw 清理和素材移除。
- `material_processing_middleware.py`：统一接收上层的素材处理请求与工具可用性校验请求，桥接 `source_importer.py` 和 `ffmpeg_tool.py`。
- `startup_middleware.py`：启动阶段预加载中间件，集中探测 FFmpeg/llama.cpp、预取项目配置和云模型预设，供启动页线程复用。
- `logging_preferences.py`：管理日志等级偏好。
- `logging_middleware.py`：安装全局日志中间件，日志只写入文件。
- `ai_model_middleware.py`：统一模型调用入口，负责加载默认提示词、构造标准消息、屏蔽敏感日志并路由下层模型后端。
- `prompt_preferences.py`：管理用户自定义提示词覆盖，空内容不覆盖默认提示词。
- `__init__.py`：标记 `utils` 为 Python 包。

## 与其他目录的关系

- `gui` 调用 `i18n.py`、`theme.py`、`logging_preferences.py`、`prompt_preferences.py`、`cloud_model_presets.py` 和 `state_manager.py`。
- `core` 可调用 `i18n.py` 获取当前占位流程文案。
- `core` 的 AI 请求必须通过 `ai_model_middleware.py` 构造和执行，不能直接访问下层模型接口。
- `ai_model_middleware.py` 从 `res/default_prompts.json` 加载默认提示词资源，并通过 `prompt_preferences.py` 读取非空用户覆盖。
- `i18n.py`、`theme.py`、`logging_preferences.py`、`prompt_preferences.py` 和 `cloud_model_presets.py` 通过 `global_store.py` 管理全局用户偏好。
- `state_manager.py` 使用 `core.models.ProjectConfig` 进行结构校验。
- `paths.py` 统一指向 `projects/` 下的工程目录。
- `source_importer.py` 由 `gui/pages/project_page.py` 调用；它只处理文件系统操作，不负责弹窗、按钮状态或用户提示。
- `gui/pages/project_page.py` 通过 `material_processing_middleware.py` 触发素材处理和工具校验，不直接承担下层处理细节。
- `gui/splash_screen.py` 通过 `startup_middleware.py` 在子线程预热启动数据，再交给主窗口和页面复用。

## 维护注意事项

- 工具函数保持无界面依赖，除非它本身就是 Qt 适配层。
- 启动预热逻辑集中在 `startup_middleware.py`，避免页面构造阶段重复执行同步探测。
- 路径相关逻辑集中放在 `paths.py`，避免各处拼接项目目录。
- 素材导入和清理逻辑集中放在 `source_importer.py`，页面层不要直接复制、链接或删除项目素材文件。
- 全局用户数据和配置选项统一通过 `global_store.py` 读写。
- 项目配置读写保持 UTF-8 和结构化 JSON；全局配置读写保持 UTF-8 和结构化 YAML。
- Model execution must enter backends through `call_text_model()`, `call_image_model()`, or `call_video_model()`.
- 日志不得输出 API Key、完整密钥、隐私文本或大型原始素材内容。
