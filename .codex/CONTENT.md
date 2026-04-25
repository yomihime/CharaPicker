# CharaPicker / 拾卡姬 项目上下文

本文档是给人类开发者和 AI 助手共用的项目说明。它整理自 `init_prompt.md`、`memo.txt` 以及后续补充要求，用来明确 CharaPicker 的产品目标、架构边界、UI 规范、文档规范和发布规范。

若原始提示文档出现编码乱码，以本文档作为当前项目语义基准。

## 1. 项目定位

CharaPicker，中文名“拾卡姬”，是一个从番剧、漫画、视频、图像或文本素材中提取角色信息，并生成角色卡、人设资料或结构化角色档案的桌面工具。

核心目标：

- 素材只提取一次，沉淀为可复用知识库。
- AI 根据用户指定的目标角色或世界观，生成定向洞察。
- 提取阶段和编译阶段都要实时向 UI 推送“洞察流”。
- 后续生成角色卡时优先读取结构化 JSON，避免重复处理原始视频或漫画素材。

核心原则：

- Extract Once：原始素材只处理一次。
- Targeted Insight：面向目标角色或世界观生成专属洞察。
- Iterative Compilation：通过多轮状态更新编译角色人格。
- Visible Thinking：用户应能通过 InsightStreamPanel 看到 AI 的关键发现，而不是只看到普通日志。

## 2. 开发环境

主要开发环境是 Anaconda。

- 默认 conda 环境名：`CharaPicker`
- 日常运行、调试、测试、脚本执行和打包命令优先使用：

```powershell
conda run -n CharaPicker ...
```

依赖管理：

- 主要依赖声明放在 `requirements.txt` 或 `pyproject.toml`。
- 后续可以为源码用户提供 `uv` 安装依赖的方式。
- `uv` 只是辅助安装路径，不作为项目主要开发环境。

## 3. 产品语气

“拾卡姬”可以有轻微拟人化语气：可爱、活泼、二次元，但不能牺牲信息清晰度。UI 文案应让用户明确知道当前正在发生什么。

参考文案：

- 启动：`拾卡姬 (CharaPicker) v0.1.0 已就位`
- 引导：`准备好帮您从番剧/漫画里扒角色卡啦！请投喂视频文件或漫画文件夹吧。`
- 字幕提取：`拾卡姬正在听写台词... [|||||| ] 60%`
- 表情/分镜分析：`拾卡姬正在逐帧观察表情...`
- AI 生成人设：`拾卡姬正在大脑风暴中...`
- 格式不支持：`呜...这个格式姬读不懂呢，请换成 MP4 或 PNG 试试？`
- 没检测到角色声音：`拾卡姬没有听到有效声音，请确认音轨是否正常。`
- 完成：`搞定啦！角色卡已生成。`
- 保存路径示例：`./output/zero_two_astrabot.json`
- 完成后提醒：`记得检查一下“开场白”是否符合您的心意。`

## 4. UI 与多语言

界面框架：

- 使用 PyQt6 或 PySide6。
- 使用 `qfluentwidgets`，优先使用免费社区版组件。
- 视觉风格为 Windows 11 Fluent Design / Acrylic。
- 支持亮色/暗色自适应。

多语言要求：

- UI 中所有用户能看见的字串都必须支持多语言适配。
- 不要在界面代码中长期硬编码用户可见文本。
- 语系字串文件统一放在 `i18n/` 文件夹中。
- 默认语系为简体中文。
- 基础支持语系至少包括：
  - `zh_CN`：简体中文，default
  - `zh_TW`：繁体中文
  - `en_US`：英语
  - `ja_JP`：日语

资源与颜色要求：

- 运行时通用资源统一放在 `res/` 文件夹中。
- 当前 UI 使用的颜色标识统一放在 `res/colors.py`。
- UI、组件和页面代码中不要直接硬编码 RGB、RGBA 或 Hex 颜色值。
- 新增颜色时先在 `res/colors.py` 中定义语义化常量，再在界面代码中引用。
- 后续新增图片、图标、贴图等素材文件时，应放在 `res/` 下，并保持文件名语义清楚。
- `res/` 不放用户可见文案；用户可见文本仍然必须放在 `i18n/`。

## 5. InsightStreamPanel

`InsightStreamPanel` 是核心 UI 组件。

定位：

- 位于主进度区域下方或侧边。
- 采用 Card + Timeline 的流式卡片列表。
- 展示 AI 的关键发现，不展示普通调试日志。

行为：

- 通过 `pyqtSignal(dict)` 接收结构化洞察事件。
- 支持自动滚动。
- 支持关键词高亮。
- 支持按角色过滤查看。

文案风格：

- `姬在第 3 集捕捉到 [角色名] 的微表情变化...`
- `正在调和性格矛盾...`
- `[角色A] 初期表现顺从 -> 第 5 章出现反抗倾向 -> 已标记为“隐性叛逆”成长弧光。`

## 6. 推荐目录结构

```text
CharaPicker/
├── .codex/                      # AI 协作上下文
├── bin/                         # 外部二进制，如 ffmpeg/llama，Git Ignore
├── core/
│   ├── formats/                 # 导出格式插件
│   ├── compiler.py              # AI 迭代编译器
│   ├── generator.py             # 管线调度与输出管理
│   └── extractor.py             # 媒体解析与特征提取
├── doc/                         # 多语言文档与扩展说明
├── gui/                         # FluentUI 界面
├── i18n/                        # 语系字串文件
├── models/                      # 本地模型，Git Ignore
├── projects/
│   └── {project_id}/
│       ├── config.json          # 工程配置：target_characters、extraction_mode 等
│       ├── raw/                 # 原始素材
│       ├── cache/               # 切片与临时文件
│       ├── knowledge_base/
│       │   ├── facts.json       # 客观事实记录
│       │   └── targeted_insights.json
│       │                         # 定向洞察，按角色/世界观索引
│       └── output/              # 导出的角色卡
├── res/                         # 颜色标识与运行时资源素材
├── utils/
│   ├── chunker.py               # 长文本/视频分块
│   ├── state_manager.py         # 状态积累与冲突处理
│   └── env_manager.py           # Conda 环境检测与依赖管理
├── main.py
├── README.md                    # GitHub 首页说明，简体中文
└── build.bat                    # Windows 打包入口
```

## 7. 核心数据流

### 7.1 提取阶段：Targeted Insight Generation

原则：一次提取，多维洞察。

流程：

1. 读取 `config.json` 中的 `target_characters`。
2. 将素材切成 Chunk。
3. 每个 Chunk 的 Prompt 必须包含目标角色列表，并要求 AI 提取：
   - 行为特征
   - 台词风格
   - 关系互动
   - 不超过 50 字的洞察摘要
4. 结构化输出到 `knowledge_base/targeted_insights.json`。
5. 同步把关键洞察推送到 `InsightStreamPanel`。

提示词意图示例：

```text
针对 [目标列表]，提取专属行为特征、台词风格、关系互动，
并生成一段不超过 50 字的简短洞察摘要。
```

要求：支持多目标并行洞察，避免为每个角色重复跑模型。

### 7.2 编译阶段：Iterative Compilation

触发条件：用户请求生成指定角色卡。

流程：

1. `Retrieval`：从 `facts.json` 过滤目标角色相关数据。
2. `Chunking`：按固定 Token 预算切块。
3. `Rolling Update`：维护 `CharacterState`，逐块执行 `state = ai_refine(state, chunk)`。
4. `Conflict Resolution`：显式处理前后矛盾，例如伪装、黑化、成长；不要简单覆盖旧信息，应记录为动态属性。
5. `Final Polish`：做全局一致性检查，输出结构化角色人格。

性能要求：

- 编译过程必须异步。
- 通过 Qt Signal 实时推送 `state` 变化和洞察摘要到 UI。

## 8. 模块边界

保持职责清晰，禁止跨层混用。

- `extractor`：只负责媒体解析、事实提取和洞察产出。
- `compiler`：只负责角色状态迭代、长文阅读、冲突处理。
- `generator`：只负责调度编译器、组织输出格式。
- `gui`：只负责展示、交互和信号连接，不直接承载业务推理。
- `utils`：放通用工具，如分块、状态管理、环境检查。
- `i18n`：只放语系字串与本地化资源，不放业务逻辑。
- `res`：只放颜色标识、主题资源和图片等运行时素材，不放业务逻辑或用户文案。
- `doc`：只放说明文档，不放运行时代码。

数据结构建议：

- 全面使用 Type Hints。
- 使用 Pydantic 或 attrs 校验结构化数据。
- UI 信号传递尽量使用可序列化的 `dict`。

## 9. 混合媒体与成本控制

素材支持方向：

- 支持视频与漫画/图片文件夹混合输入。
- 自动路由到对应解析流程。
- 画质预设、片头片尾裁剪等应在 ingestor 或提取前处理。

Extract Once 原则：

- 原始素材只处理一次。
- 处理结果写入 `knowledge_base`。
- 后续生成角色卡时读取 JSON，不重复调用视频解析。

动态环境：

- 自动检测 `bin/` 下的 ffmpeg/llama 等工具版本。
- 本地模式按显存预算反推切片。
- 云端模式按 Token/费用预算反推切片。

Preview 试算：

- 正式运行前先处理前 2 个 Chunk。
- 返回预估耗时、预估费用和首段定向洞察样张。

## 10. README 与文档语言

根目录 `README.md`：

- 未来作为 GitHub 仓库首页使用。
- 必须使用简体中文撰写。
- 用于说明项目定位、安装方式、运行方式、截图、功能和开发状态。

多语言文档：

- 项目需要同时支持简体中文、繁体中文、英语和日语。
- 其他语言版本或扩展说明文档统一放在 `doc/` 文件夹中。
- `doc/` 内的多语言文档应在文件名中标明语种，避免混淆。

## 11. 架构文档规范

每个主要文件夹内都要有 Markdown 架构说明文件。

推荐命名：

```text
ARCHITECTURE.md
```

每份架构说明应包含：

- 该目录负责什么。
- 该目录不负责什么。
- 关键文件说明。
- 与其他目录的数据流或调用关系。
- 后续维护注意事项。

根目录也必须有架构说明 Markdown 文件。根目录架构说明必须提供可点击的相对链接，跳转到各子目录的架构说明文件。

示例：

```markdown
- [core 架构](core/ARCHITECTURE.md)
- [gui 架构](gui/ARCHITECTURE.md)
- [utils 架构](utils/ARCHITECTURE.md)
- [i18n 架构](i18n/ARCHITECTURE.md)
- [res 架构](res/ARCHITECTURE.md)
- [doc 架构](doc/ARCHITECTURE.md)
```

架构说明要面向人和 AI 同时可读：句子短、边界清楚、少用隐喻，优先说明职责和禁止事项。

## 12. 打包与发布

编译脚本必须使用 PyInstaller。

要求：

- 使用 PyInstaller 生成文件夹形式的 `dist`。
- 不要只生成单文件 exe。
- 打包完成后压缩为 zip 档。
- zip 内部顶层目录必须是 `CharaPicker/`。
- 用户解压后应看到 `CharaPicker/xxx` 的结构。
- 发布包中应包含运行所需的程序文件、依赖资源和必要说明。
- 发布包中不应包含源码开发缓存、测试缓存、临时文件或无关日志。

推荐输出形态：

```text
release/
└── CharaPicker-vX.Y.Z-windows.zip
    └── CharaPicker/
        ├── CharaPicker.exe
        ├── ...
        └── README.md
```

## 13. 当前实现优先级

优先级从高到低：

1. 先把 PyQt6 + qfluentwidgets 社区版 UI 架构搭稳。
2. 建立 i18n 机制，让 UI 可见文本走语系字串。
3. 实现项目配置、素材导入、预览按钮和 InsightStreamPanel。
4. 打通 `extractor -> signal -> gui` 的洞察事件流。
5. 增加每个主要目录的 `ARCHITECTURE.md`。
6. 完善 `README.md` 和 `doc/` 多语言文档结构。
7. 接入真实媒体解析、AI 推理、知识库写入。
8. 完善 PyInstaller 文件夹式打包和 zip 发布流程。
9. 最后完善多格式导出、角色卡模板和成本评估。

## 14. 给 AI 助手的开发提醒

- 默认在 `CharaPicker` conda 环境中运行命令。
- 改 UI 时保持 Fluent Design 风格，优先使用 qfluentwidgets 社区版已有组件。
- 改 UI 颜色时先更新 `res/colors.py`，不要在界面代码中直接写 RGB、RGBA 或 Hex。
- 新增图片、图标、贴图等运行时素材时放入 `res/`，并同步维护 `res/ARCHITECTURE.md`。
- UI 可见文本必须走 i18n。
- 不要把普通调试日志伪装成洞察流。
- `InsightStreamPanel` 只展示用户真正关心的关键发现。
- 修改业务逻辑时遵守 `extractor`、`compiler`、`generator` 的职责边界。
- 生成或修改 Prompt 时，要兼顾多目标并行、结构化输出和简短洞察摘要。
- 增加目录或模块时，同步更新对应的架构说明文档。
- 修改打包逻辑时，确保最终 zip 解压后是 `CharaPicker/xxx` 结构。
- 提交 commit 时必须遵循 Conventional Commits 约定式提交规范，并且必须带 `-s` 签名。

## 15. 全局用户数据与配置存储

当前全局用户数据和配置选项统一通过 `utils/global_store.py` 管理。

设计边界：

- 全局用户偏好、软件级配置、云端模型预设等，不应直接散落在 UI 或业务模块中读写。
- 默认存储文件为根目录 `config.yaml`。
- `config.yaml` 可能包含 API Key、模型服务地址、用户偏好和其他隐私信息，必须显式加入 `.gitignore`，不得提交到版本库。
- 项目级配置仍使用 `projects/{project_id}/config.json`，不并入全局配置。
- `global_store.py` 提供 `GlobalStore` 抽象和 `YamlFileGlobalStore` 默认实现，后续迁移到其他存储方式时，应优先替换存储适配层，而不是重写各 UI 或业务调用点。
- 新增全局配置项时，应通过 `get_global_value()` / `set_global_value()` 或基于 `GlobalStore` 的封装函数读写。
- 全局配置读写保持 UTF-8 和结构化 YAML；项目配置读写保持 UTF-8 和结构化 JSON。

当前已接入全局存储中间件的配置：

- `utils/i18n.py`：界面语言偏好。
- `utils/theme.py`：外观主题偏好。
- `utils/cloud_model_presets.py`：OpenAI-compatible 云端模型配置预设。
