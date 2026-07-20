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
- `app_metadata.py`：集中保存应用名、组织名、当前运行时版本/阶段和 HTTP User-Agent。
- `media_types.py`：集中保存视频、图片、音频、文本后缀，以及直接素材和容器输入格式的独立支持档位；容器 profile 不新增顶层媒体类型，也不进入直接素材后缀集合。当前 `.zip` 已启用，后续格式仍受各自里程碑门禁控制。
- `material_preprocessing.py`：定义容器输入预处理请求、结果、warning、派生材料记录和 manifest 协议，统一负责安全路径校验、取消检查、临时目录、原子落盘、稳定派生路径、manifest 索引、完整性/复用判断和生命周期清理，不依赖 `core` 或 `gui`。
- `zip_material_preprocessor.py`：在预处理边界内使用标准库列举和流式展开 ZIP entry，复用统一的大小、数量、压缩比、后缀和路径安全规则；不负责项目导入或 UI 状态。
- `material_processing_events.py`：集中保存素材处理取消消息和 FFmpeg 进度事件前缀等跨层协议常量。
- `paths.py`：定义应用根目录、项目根目录和单个项目的标准目录结构。
- `global_store.py`：提供全局用户数据和配置选项的读写中间件，默认使用根目录 `config.yaml`。
- `proxy_preferences.py`：封装内置代理设置的默认值、归一化、读写和代理 URL 构造。
- `state_manager.py`：保存、读取和列出项目配置，项目配置写入 `projects/{project_id}/config.json`。
- `theme.py`：管理主题偏好，并调用 qfluentwidgets 应用亮色、暗色或系统主题。
- `chunker.py`：提供兼容旧调用的固定长度分块，以及保留起止 offset、段落边界、重叠范围、最大 chunk 数和截断 warning 的文本预算分块。
- `env_manager.py`：提供 conda 命令前缀、llama.cpp/whisper.cpp 二进制发现和可用性检测。
- `ffmpeg_tool.py`：封装 ffmpeg 工具可用性校验与素材转码/分段执行。
- `ffmpeg_detection.py`：封装 FFmpeg 设备/CPU 探测相关 helper，供 `ffmpeg_tool.py` 复用。
- `cloud_model_presets.py`：保存和读取云端模型配置预设，维护云端服务类型到模型调用后端的映射，提供视频输出 Token / 分钟到单次请求上限的换算工具，以及 GUI/core 共用的具体模型音频理解能力判断。
- `cloud_models.py`：按云端服务类型路由并拉取模型列表，当前底层复用 OpenAI-compatible 模型列表接口。
- `network_middleware.py`：统一应用内 HTTP(S) 请求、代理读取、连通性测试、URL/错误脱敏和 DashScope 临时代理环境。
- `llamacpp_downloader.py`：下载并安装 llama.cpp 运行时到 `bin/`。
- `whispercpp_downloader.py`：下载并安装 whisper.cpp 运行时到 `bin/whisper.cpp/`，下载 Whisper 模型到 `models/whisper/`。
- `audio_transcription.py`：封装本地 whisper.cpp episode 转写、音频/视频输入准备、缓存命中判断和 `episode_transcript.json` 写入；缓存键覆盖素材指纹、运行时、模型和语言，日志不记录完整转写文本。
- `ffmpeg_downloader.py`：下载并安装 ffmpeg 运行时到 `bin/`。
- `source_importer.py`：把直接素材或已启用容器按项目目录规则原子复制到 `projects/{project_id}/raw`，计算 raw 目标，并通过预处理 manifest 协调 raw 清理、素材移除和 stale 派生产物清理；容器不得进入普通 materials link 分支。
- `source_status.py`：计算项目页需要的素材显示名、raw/materials 或预处理 manifest 映射、项目内素材列表和素材状态。
- `material_processing_middleware.py`：统一接收上层的素材处理请求与工具可用性校验请求，把 raw 拆成直接素材、已启用容器和 unsupported 三类，再分别桥接预处理、source importer 和 FFmpeg。
- `startup_middleware.py`：启动阶段预加载中间件，集中探测 FFmpeg/llama.cpp/whisper.cpp、预取项目配置和云模型预设，供启动页线程复用。
- `logging_preferences.py`：管理日志等级偏好。
- `logging_middleware.py`：安装全局日志中间件，日志只写入文件；日志等级边界和敏感信息规则见运行时中间件参考文档。
- `ai_model_middleware.py`：统一模型调用入口，负责加载默认提示词、构造标准消息、携带按请求设置的超时/结构化输出/后端专用参数、屏蔽敏感日志并路由下层模型后端。
- `ai_model_middleware.py` 中的 OpenAI-compatible 视频输入会按请求中的 FPS 抽帧为图片组后发送；支持直接视频 FPS 的后端则由对应 provider 传递原始视频参数。
- `prompt_preferences.py`：管理用户自定义提示词覆盖，空内容不覆盖默认提示词。
- `__init__.py`：标记 `utils` 为 Python 包。

## 与其他目录的关系

- `gui` 调用 `i18n.py`、`theme.py`、`logging_preferences.py`、`prompt_preferences.py`、`cloud_model_presets.py` 和 `state_manager.py`。
- `core` 可调用 `i18n.py` 获取流程文案，并通过 `ai_model_middleware.py` 访问模型后端。
- `core` 的 AI 请求必须通过 `ai_model_middleware.py` 构造和执行，不能直接访问下层模型接口。
- `ai_model_middleware.py` 从 `res/default_prompts.json` 加载默认提示词资源，并通过 `prompt_preferences.py` 读取非空用户覆盖。
- `ai_model_middleware.py` 是默认 prompt 的唯一加载与渲染入口；上层模块只传 purpose、变量、metadata 和多模态素材 part，不在业务代码中硬编码 prompt 正文。
- `i18n.py`、`theme.py`、`logging_preferences.py`、`prompt_preferences.py`、`cloud_model_presets.py` 和 `proxy_preferences.py` 通过 `global_store.py` 管理全局用户偏好。
- `state_manager.py` 使用 `core.models.ProjectConfig` 进行结构校验。
- `paths.py` 统一指向 `projects/` 下的工程目录。
- 应用内联网请求必须通过 `network_middleware.py` 或已接入它的上层封装执行；外部浏览器链接不属于内置代理管理范围。
- `audio_transcription.py` 通过 `ffmpeg_tool.py` 提取视频音轨，并通过 `core.knowledge_base` 写入 episode transcript；不得在日志中输出完整 transcript。
- `ai_model_middleware.py`、`cloud_models.py` 和联网下载器在记录 endpoint 或错误摘要前应复用 `network_middleware.py` 的脱敏能力。
- `ffmpeg_tool.py`、`material_processing_middleware.py` 和 `source_importer.py` 只记录素材处理摘要、文件名或项目内相对标识，不把完整 FFmpeg 命令或外部素材绝对路径作为常规日志输出。
- 容器输入必须先通过 `material_preprocessing.py` 产生可扫描派生材料；格式处理模块不得自行拼接项目路径、写 manifest 或把原容器链接进 `materials/`。
- `source_importer.py` 由 `gui/pages/project_page.py` 调用；它只处理文件系统操作，不负责弹窗、按钮状态或用户提示。
- `source_status.py` 由 `gui/pages/project_page.py` 调用；它只计算素材状态，不负责渲染列表行、弹窗或 InfoBar。
- `gui/pages/project_page.py` 通过 `material_processing_middleware.py` 触发素材处理和工具校验，不直接承担下层处理细节。
- `gui/splash_screen.py` 通过 `startup_middleware.py` 在子线程预热启动数据，再交给主窗口和页面复用。
- `main.py`、`gui/main_window.py`、`gui/splash_screen.py`、构建脚本和联网工具共享 `app_metadata.py` 中的应用名、版本和 User-Agent。

## 维护注意事项

- 工具函数保持无界面依赖，除非它本身就是 Qt 适配层。
- 跨 `utils`、`core`、`gui` 重复使用的运行时协议常量应集中在 `app_metadata.py`、`media_types.py` 或 `material_processing_events.py`，不要在页面、工具和中间件里各自硬编码。
- 启动预热逻辑集中在 `startup_middleware.py`，避免页面构造阶段重复执行同步探测。
- 路径相关逻辑集中放在 `paths.py`，避免各处拼接项目目录。
- 素材导入和清理逻辑集中放在 `source_importer.py`，页面层不要直接复制、链接或删除项目素材文件。
- raw/materials 状态判断集中放在 `source_status.py`，页面层只负责展示和触发操作。
- 全局用户数据和配置选项统一通过 `global_store.py` 读写。
- 项目配置读写保持 UTF-8 和结构化 JSON；全局配置读写保持 UTF-8 和结构化 YAML。
- 新增程序内联网入口时应复用 `network_middleware.py`，避免绕过代理偏好、网络锁和敏感信息脱敏规则。
- 模型执行必须通过 `call_text_model()`、`call_image_model()` 或 `call_video_model()` 进入后端。
- 新增模型任务时，默认 prompt 正文放入 `res/default_prompts.json`；业务代码不得为了临时修复而复制、拼接或长期硬编码 prompt 指令文本。
- 日志按 `INFO` 阶段摘要、`DEBUG` 诊断细节、`WARNING` 可恢复降级、`ERROR` 任务失败划分；不得输出 API Key、完整密钥、完整 prompt、完整模型响应、隐私文本或大型原始素材内容。
- 运行时中间件的详细职责边界见 [`../docs/reference/runtime-middleware.zh_CN.md`](../docs/reference/runtime-middleware.zh_CN.md)。
