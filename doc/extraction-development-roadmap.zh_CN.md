# 提取与角色成长编译开发路线（zh_CN）

本文面向项目开发者，用于拆分后续实现任务。开发时保持现有架构，不引入新技术栈，每次只实现一个小功能。

## 1. 开发原则

- `extractor` 负责素材解析、chunk 提取、集级合并、季级合并和摘要生成。
- `compiler` 负责按季、按集更新 `CharacterState`，处理成长、冲突和关系变化。
- `generator` 负责最终格式组织，不重新提取素材，不承担角色状态推理。
- `utils/ai_model_middleware.py` 继续作为唯一模型调用入口。
- 所有知识库产物写入 `projects/{project_id}/knowledge_base/`。
- 所有结构化结果使用 UTF-8 JSON。

## 2. 输入目录扫描

第一阶段规则：

- 用户选择素材根目录。
- 根目录下一级文件夹识别为季。
- 每季文件夹内的视频文件识别为集。
- 季和集均按名称排序。

开发要求：

- 内部 ID 使用稳定格式：`season_001`、`episode_001`、`chunk_0001`。
- 原始文件夹名和文件名只作为展示与追溯信息。
- 扫描结果写入 `source_manifest.json`。
- 先实现简单排序，后续再增加 UI 手动调整顺序。

`source_manifest.json` 建议结构：

```json
{
  "source_root": "",
  "seasons": [
    {
      "season_id": "season_001",
      "source_folder": "",
      "display_title": "",
      "sort_key": "",
      "episodes": [
        {
          "episode_id": "episode_001",
          "source_file": "",
          "display_title": "",
          "sort_key": ""
        }
      ]
    }
  ]
}
```

## 3. knowledge_base 目录结构

必须按季、集、chunk 分层落盘。

```text
knowledge_base/
├── source_manifest.json
├── seasons/
│   ├── season_001/
│   │   ├── season_content.json
│   │   ├── season_summary.json
│   │   ├── character_stage_states.json
│   │   └── episodes/
│   │       ├── episode_001/
│   │       │   ├── episode_content.json
│   │       │   ├── episode_summary.json
│   │       │   └── chunks/
│   │       │       ├── chunk_0001.json
│   │       │       └── chunk_0002.json
│   │       └── episode_002/
│   │           ├── episode_content.json
│   │           ├── episode_summary.json
│   │           └── chunks/
│   │               └── chunk_0001.json
│   └── season_002/
│       ├── season_content.json
│       ├── season_summary.json
│       ├── character_stage_states.json
│       └── episodes/
└── character_cards/
    └── {character_id}.json
```

落盘要求：

- 每个 chunk 完成后写入对应 `chunks/chunk_xxxx.json`。
- 每集完成后写入 `episode_content.json` 和 `episode_summary.json`。
- 每季完成后写入 `season_content.json` 和 `season_summary.json`。
- 每季角色阶段状态写入 `character_stage_states.json`。
- 最终角色卡写入 `character_cards/{character_id}.json`。

## 4. 数据产物结构

chunk 结果建议字段：

```json
{
  "season_id": "season_001",
  "episode_id": "episode_001",
  "chunk_id": "chunk_0001",
  "targets": [],
  "facts": [],
  "behavior_traits": [],
  "dialogue_style": [],
  "relationship_interactions": [],
  "conflicts": [],
  "character_state_changes": [],
  "insight_summary": "",
  "evidence_refs": []
}
```

集级完整内容建议字段：

```json
{
  "season_id": "season_001",
  "episode_id": "episode_001",
  "targets": [],
  "chunk_results": [],
  "facts": [],
  "behavior_traits": [],
  "dialogue_style": [],
  "relationship_interactions": [],
  "conflicts": [],
  "character_state_changes": [],
  "evidence_refs": []
}
```

集级摘要建议字段：

```json
{
  "season_id": "season_001",
  "episode_id": "episode_001",
  "character_summaries": [],
  "relationship_changes": [],
  "major_events": [],
  "open_conflicts": [],
  "growth_signals": [],
  "insight_summary": ""
}
```

季级摘要建议字段：

```json
{
  "season_id": "season_001",
  "final_character_states": [],
  "relationship_baseline": [],
  "major_conflicts": [],
  "unresolved_threads": [],
  "growth_trajectory": [],
  "background_summary": ""
}
```

## 5. 提取上下文规则

提取当前 chunk 时，证据优先级必须固定：

```text
CURRENT_CHUNK
> CURRENT_EPISODE_EXTRACTED_CHUNKS
> CURRENT_SEASON_EPISODE_SUMMARIES
> PREVIOUS_SEASON_BACKGROUND
```

开发要求：

- `CURRENT_CHUNK` 使用当前 chunk 原文或当前 chunk 多模态解析结果。
- `CURRENT_EPISODE_EXTRACTED_CHUNKS` 默认注入本集已完成 chunk 的完整结构化结果。
- 不注入已完成 chunk 的原文全文。
- 同集上下文超预算时，保留最近 chunk 的完整结构化结果，把更早结果合并为集内滚动摘要。
- `PREVIOUS_SEASON_BACKGROUND` 是低优先级背景，不能覆盖当前素材的新事实。

## 6. Prompt 指示

提取类 prompt 必须要求：

- 一次调用面向所有目标角色。
- 只根据输入素材和结构化上下文输出。
- 当前 chunk 新事实优先于历史摘要。
- 不编造输入中不存在的剧情或设定。
- 输出结构化 JSON。

编译类 prompt 必须要求：

- 输入是按时间顺序排列的集级完整内容。
- 更新而不是重写 `CharacterState`。
- 显式记录冲突、伪装、成长和关系变化。
- 保留证据来源。
- 输出结构化 JSON。

## 7. 实现顺序

每次只实现一个小功能，建议顺序如下：

1. 实现素材目录扫描，按一级文件夹识别季，按文件名排序识别集。
2. 生成 `source_manifest.json`。
3. 建立 `knowledge_base/seasons/season_xxx/episodes/episode_xxx/chunks/` 目录结构。
4. 定义 chunk 结构化结果模型。
5. 提取请求支持同集已完成 chunk 的完整结构化结果注入。
6. 实现 chunk 结果落盘到对应 `chunk_xxxx.json`。
7. 实现集级完整内容合并。
8. 实现集级压缩摘要生成。
9. 实现同季历史集摘要注入。
10. 实现季级完整内容合并。
11. 实现季级压缩摘要生成。
12. 实现前一季季级背景摘要注入和配置开关。
13. 实现按季、按集步进式角色状态编译。
14. 实现季级角色阶段总结。
15. 实现最终角色卡生成前的 `Final Polish`。

## 8. 验收标准

- 输入素材根目录能按“文件夹 = 季、文件 = 集”生成稳定 `source_manifest.json`。
- `knowledge_base` 按季、集、chunk 层级落盘，结构清晰可恢复。
- 同集后续 chunk 能利用前面 chunk 的完整结构化结果。
- 单集完成后能得到可追溯的集级完整内容。
- 后续集能读取当前季已完成集摘要并保持连续性。
- 新一季能继承上一季关键状态，但不会把上一季状态误判为当前事实。
- 角色卡生成以每集为步进单位，能体现角色成长路线。
- chunk、集、季、角色状态每层都有可复用、可恢复的结构化产物。
