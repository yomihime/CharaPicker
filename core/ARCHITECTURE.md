# core 架构说明

## 负责什么

- 承载核心业务模型和处理流程。
- 定义项目配置、洞察事件、角色状态和项目路径等结构化数据。
- 产出提取阶段的知识库 JSON、洞察事件、进度和 token 用量。
- 承载角色状态编译、季/集聚合和输出渲染的核心接口。

## 不负责什么

- 不负责创建 Qt 页面、控件布局或导航。
- 不负责保存用户偏好和界面状态。
- 不直接读取或写入 i18n 文案文件。
- 不直接管理运行时颜色、图标或图片资源。

## 关键文件

- `models.py`：定义 `ProjectConfig`、`SourceProcessingConfig`、`InsightEvent`、`CharacterState`、`ChunkExtractionResult`、`ProjectPaths` 等 Pydantic 模型。
- `extractor.py`：定义 `Extractor`，负责素材目录扫描、`source_manifest.json` 生成、知识库分层初始化、chunk/episode/season 内容合并，以及流式预览提取。
- `compiler.py`：定义 `build_character_compile_request()`、`compile_character_state()`、`compile_character_state_by_season_episode()`、`write_character_stage_states()` 和 `final_polish_character_state()`，负责从知识库聚合角色阶段状态。
- `generator.py`：定义 `render_profile_markdown()`，当前将角色状态渲染为 Markdown。
- `__init__.py`：标记 `core` 为 Python 包。

## 与其他目录的关系

- 从 `utils.i18n` 读取本地化文案，用于提取流程、编译流程、摘要和洞察描述。
- 通过 `utils.ai_model_middleware` 构造和执行模型请求；不直接访问具体模型后端。
- 向 `gui` 通过 Qt Signal 传递可序列化的洞察事件 `dict`。
- 向 `gui` 通过回调传递预览进度和 token 用量。
- 被 `utils.state_manager` 引用，用于项目配置的序列化和反序列化。
- 被 `utils.paths` 引用，用于描述包含 `raw/`、`materials/`、`cache/`、`knowledge_base/` 和 `output/` 的项目路径。
- 向 `projects/{project_id}/knowledge_base/` 写入 `source_manifest.json`、`seasons/*/episodes/*/chunks/*.json`、`episode_content.json`、`episode_summary.json`、`season_content.json` 和阶段性角色状态。

## 维护注意事项

- 新增业务数据结构时优先放在 `models.py`，保持 Type Hints。
- 素材处理配置只描述用户选择和项目状态；文件复制、链接、清理等副作用放在 `utils/source_importer.py`。
- `extractor` 只做素材解析、事实提取和洞察产出。
- `compiler` 只做角色状态迭代、长文本阅读和冲突处理。
- `generator` 只做编译调度后的格式组织和输出渲染。
- 不要在 `core` 中引入界面布局逻辑。
- 写入知识库时保持 UTF-8 和结构化 JSON，路径结构要与 `projects/ARCHITECTURE.md` 保持一致。
