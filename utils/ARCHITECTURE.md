# utils 架构说明

## 负责什么

- 放置跨模块复用的轻量工具。
- 管理本地化加载、路径计算、项目配置保存和主题偏好。
- 提供分块、环境检测和状态管理等通用能力。

## 不负责什么

- 不承载核心 AI 推理流程。
- 不创建完整 UI 页面。
- 不放用户可见文案内容。
- 不放运行时图片、图标或颜色表。

## 关键文件

- `i18n.py`：管理语言偏好、系统语言归一化、文案加载和 `t()` 翻译函数。
- `paths.py`：定义应用根目录、项目根目录和单个项目的标准目录结构。
- `global_store.py`：提供全局用户数据和配置选项的读写中间件，默认使用根目录 `config.yaml`，并通过 `GlobalStore` 抽象保留迁移到其他存储方式的入口。
- `state_manager.py`：保存、读取和列出项目配置。
- `theme.py`：管理主题偏好，并调用 qfluentwidgets 应用亮色、暗色或系统主题。
- `chunker.py`：预留文本或素材分块工具。
- `env_manager.py`：预留环境检测工具。
- `cloud_model_presets.py`：保存和读取云端模型配置预设，使用 Qt 本地设置。
- `cloud_models.py`：拉取 OpenAI-compatible 云端模型列表。
- `llamacpp_downloader.py`：下载并安装 llama.cpp 运行时到 `bin/`。
- `logging_middleware.py`：安装全局日志中间件。每次启动在 `log/` 中创建一个按启动时间命名的 `.log` 文件，并接收 Qt 消息和未捕获异常；日志等级和输出目标在中间件内定义，日志只写入文件；加载时清理旧日志，最多保留 20 个日志文件。
- `__init__.py`：标记 `utils` 为 Python 包。

## 与其他目录的关系

- `gui` 调用 `i18n.py`、`theme.py` 和 `state_manager.py`。
- `core` 调用 `i18n.py` 获取当前占位流程文案。
- `i18n.py`、`theme.py` 和 `cloud_model_presets.py` 通过 `global_store.py` 管理全局用户偏好。
- `state_manager.py` 使用 `core.models.ProjectConfig` 进行结构校验。
- `paths.py` 统一指向 `projects/` 下的工程目录。

## 维护注意事项

- 工具函数保持无界面依赖，除非它本身就是 Qt 偏好或设置适配层。
- 路径相关逻辑集中放在 `paths.py`，避免各处拼接项目目录。
- 全局用户数据和配置选项统一通过 `global_store.py` 读写，不直接散落到 UI 或业务模块。
- 项目配置读写保持 UTF-8 和结构化 JSON；全局配置读写保持 UTF-8 和结构化 YAML。
- 不要把 `utils` 变成业务逻辑堆放区。
