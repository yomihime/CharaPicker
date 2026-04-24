# core 架构说明

## 负责什么

- 承载核心业务模型和处理流程。
- 定义项目配置、洞察事件、角色状态和项目路径等结构化数据。
- 产出提取阶段的洞察事件。
- 承载角色状态编译和输出渲染的核心接口。

## 不负责什么

- 不负责创建 Qt 页面、控件布局或导航。
- 不负责保存用户偏好和界面状态。
- 不直接读取或写入 i18n 文案文件。
- 不直接管理运行时颜色、图标或图片资源。

## 关键文件

- `models.py`：定义 `ProjectConfig`、`InsightEvent`、`CharacterState`、`ProjectPaths` 等 Pydantic 模型。
- `extractor.py`：定义 `Extractor`，当前负责预览阶段的占位洞察事件和进度信号。
- `compiler.py`：定义 `compile_character_state()`，当前返回占位角色状态。
- `generator.py`：定义 `render_profile_markdown()`，当前将角色状态渲染为 Markdown。
- `__init__.py`：标记 `core` 为 Python 包。

## 与其他目录的关系

- 从 `utils.i18n` 读取本地化文案，用于占位摘要和洞察描述。
- 向 `gui` 通过 Qt Signal 传递可序列化的洞察事件 `dict`。
- 被 `utils.state_manager` 引用，用于项目配置的序列化和反序列化。
- 后续应向 `projects/{project_id}/knowledge_base/` 写入结构化提取结果。

## 维护注意事项

- 新增业务数据结构时优先放在 `models.py`，保持 Type Hints。
- `extractor` 只做素材解析、事实提取和洞察产出。
- `compiler` 只做角色状态迭代、长文本阅读和冲突处理。
- `generator` 只做编译调度后的格式组织和输出渲染。
- 不要在 `core` 中引入界面布局逻辑。
