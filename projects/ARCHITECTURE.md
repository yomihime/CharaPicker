# projects 架构说明

## 负责什么

- 保存本地用户工程数据。
- 按 `project_id` 隔离项目配置、原始素材、缓存、知识库和输出结果。
- 作为 Extract Once 流程的落盘位置。

## 不负责什么

- 不保存源码模块。
- 不保存应用依赖或外部二进制工具。
- 不保存本地大模型文件。
- 不把用户项目数据默认提交到 Git。

## 关键文件和目录

- `.gitkeep`：保留空目录。
- `{project_id}/config.json`：项目配置，包含目标角色、提取模式和素材路径等。
- `{project_id}/raw/`：原始素材。
- `{project_id}/cache/`：切片、预览和临时处理文件。
- `{project_id}/knowledge_base/facts.json`：客观事实记录。
- `{project_id}/knowledge_base/targeted_insights.json`：面向目标角色或世界观的定向洞察。
- `{project_id}/output/`：导出的角色卡和资料。

## 与其他目录的关系

- `utils/paths.py` 定义本目录的标准项目结构。
- `utils/state_manager.py` 保存和读取 `config.json`。
- `core` 后续应读取素材并写入 `knowledge_base/`。
- `gui` 通过项目页展示和编辑项目配置。

## 维护注意事项

- 项目目录结构应由 `utils.paths.ensure_project_tree()` 统一创建。
- 用户素材、缓存、知识库和输出结果默认不应进入版本控制。
- 写入 JSON 时保持 UTF-8 和结构化格式。
- 后续新增项目子目录时，同步更新本说明和路径工具。
