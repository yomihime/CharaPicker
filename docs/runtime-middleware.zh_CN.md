# 运行时中间件设计说明（zh_CN）

本文记录 CharaPicker 运行时中间件的长期职责边界。它补充 `utils/ARCHITECTURE.md`，用于避免跨页面重复实现基础能力。

## 1. 总原则

运行时中间件负责跨页面、跨模块复用的基础能力，应保持职责单一。

- 中间件不承载 AI 推理本身。
- 中间件不创建完整业务页面。
- 页面层负责触发、展示进度和用户反馈。
- 长耗时任务应进入 worker/thread，避免阻塞 UI。
- 敏感信息不得进入普通日志或洞察流。

## 2. 全局存储中间件

当前全局用户数据和配置选项统一通过 `utils/global_store.py` 管理。

定位：

- 存储软件级用户偏好、云端模型预设、日志等级等跨项目配置。
- 为后续迁移到其他存储后端保留适配层。
- 避免 UI、业务模块和工具模块各自直接读写零散配置文件。

边界：

- 默认存储文件为根目录 `config.yaml`，路径由 `CONFIG_PATH` 定义。
- `config.yaml` 使用 UTF-8 和结构化 YAML。
- `config.yaml` 可能包含 API Key、模型服务地址和用户偏好，不得提交到版本库。
- 项目级配置仍使用 `projects/{project_id}/config.json`，不并入全局配置。
- `GlobalStore` 只暴露 `get()`、`set()` 和 `all()` 三类基础能力。
- 配置键使用 `/` 分隔路径，例如 `logging/level`。
- `get()` 返回深拷贝，调用方不要依赖修改返回对象来写回配置。
- `set_global_store()` 只用于测试、替换存储适配层或后续迁移，不应在普通业务流程里频繁切换。
- 当前 YAML 读写由项目内轻量解析/输出函数完成；不要为了全局存储单独引入新技术栈。

使用规则：

- 新增全局配置项时，通过 `get_global_value()` / `set_global_value()` 或语义化封装读写。
- 页面层不要散落原始 key，应优先调用 `theme_preference()`、`set_log_level_preference()` 等封装。
- 写入敏感信息时避免日志输出明文值。

当前已接入全局存储的配置包括语言、主题、云模型预设、日志等级和用户 prompt 覆盖。

## 3. 日志中间件

当前应用日志统一通过 `utils/logging_middleware.py` 安装和管理。

定位：

- 记录运行状态、异常、下载、网络请求、配置保存等开发诊断信息。
- 接收 Python `logging`、Qt 消息和未捕获异常。
- 让日志等级跟随全局存储中的用户偏好。

边界：

- `main.py` 在创建 `QApplication` 前调用 `install_global_logging()`。
- 日志文件统一写入根目录 `log/`，文件名按启动时间生成，编码为 UTF-8。
- 日志只写入文件，不作为普通 UI 文案展示，也不得伪装成 `InsightStreamPanel` 洞察事件。
- Qt 消息由入口层过滤后转交 `log_qt_message()`。
- 启动时自动清理旧日志；当前最多保留 20 个 `.log` 文件。
- 设置页修改日志等级后，必须调用 `apply_log_level_preference()` 让当前进程立即生效。
- 新增日志使用 `logging.getLogger(__name__)`，不要用 `print()` 调试运行流程。

维护要求：

- 用户可见反馈使用 `InfoBar`、页面状态或 i18n 文案。
- 不要在日志中记录 API Key、完整密钥、隐私文本或大型原始素材内容。

## 4. 弹窗中间件

当前应用自有模态弹窗统一复用 `gui/widgets/dialog_middleware.py` 中的 `FluentDialog`。

定位：

- 统一应用自有弹窗的 Fluent 风格外壳。
- 让业务弹窗只关注内容、动作和信号。

边界：

- `FluentDialog` 负责无边框窗口、透明背景、Card 容器、标题栏、关闭按钮、边距和间距。
- 具体业务弹窗在页面或组件内继承 `FluentDialog`，只添加自身表单、列表、进度条、按钮和信号。
- 自有业务弹窗不要重复手写窗口外壳、标题栏和关闭按钮。
- 文件选择器、目录选择器等原生平台弹窗可以继续直接调用 Qt。
- 弹窗内所有用户可见文案必须走 `i18n/`。

## 5. 启动预热中间件

当前启动阶段预热统一通过 `utils/startup_middleware.py` 管理。

定位：

- 在启动页阶段集中探测工具可用性并预取页面初始化数据。
- 通过 `StartupWarmupSnapshot` 向主窗口和页面复用预热结果，减少页面构造阶段重复探测。

边界：

- 启动预热在 worker 线程执行，不阻塞主线程 UI 响应。
- 预热只做可复用的读取和探测，不做项目业务写操作。
- 页面层优先消费预热快照；仅在快照缺失时再按需本地探测。

## 6. 素材处理中间件

当前素材处理流程通过 `utils/material_processing_middleware.py` 和 `utils/source_importer.py` 协同管理。

定位：

- 统一接收上层素材处理请求。
- 执行工具校验、导入、转码/分段和结果回填。
- 维护 `raw/` 与 `materials/` 的对应关系，避免页面层直接操作文件系统细节。

边界：

- 页面层只触发请求、展示进度和反馈结果，不直接复制、删除或重命名项目素材文件。
- 素材处理 worker 负责长耗时任务和取消逻辑，UI 线程只处理信号。
- 使用原素材方案时，`materials/` 通常指向或复制 `raw/` 中对应素材。
- 清理 `raw/` 时必须以 `materials/` 中已有可用素材为前置条件，并写回项目配置中的清理标记。

## 7. AI 模型调用中间件

当前 AI 模型调用统一通过 `utils/ai_model_middleware.py` 管理。

定位：

- 统一加载默认 prompt、读取用户覆盖、构造标准模型请求并路由后端。
- 为 `core` 和模型页提供稳定调用入口，降低上层对具体模型后端的耦合。

边界：

- 默认 prompt 资源放在 `res/default_prompts.json`。
- 用户覆盖 prompt 由 `utils/prompt_preferences.py` 管理，空内容不覆盖默认 prompt。
- `core`、`gui` 和其他上层模块不得绕过中间件直连模型后端。
- 模型执行必须通过 `call_text_model()`、`call_image_model()` 或 `call_video_model()` 进入后端。
- OpenAI-compatible 视频输入当前会按请求 FPS 抽帧为图片组后发送；支持直接视频 FPS 的后端由对应 provider 传递原始视频参数。
- `ModelCallRequest` 支持按请求设置超时时间、结构化输出 `response_format` 和后端专用 `extra_body` 参数；调用方不得把 API Key 或完整模型响应写入普通日志。
- 云端视频预览的输出上限按“输出 Token / 分钟”配置并结合视频 chunk 时长换算为单次请求 `max_tokens`；调用方应检查后端返回的停止原因，识别 `length` / `max_tokens` 等输出截断情况。
- 本地模型执行入口存在，但是否可用必须以当前代码为准，不要假定已完整接线。
