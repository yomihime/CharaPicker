# 角色卡最终编译与角色卡页面计划

状态：草案，等待用户检查。

本文只记录本任务特有的产品决策、边界和里程碑。通用开发规则、代码优先级、文档优先级、i18n、依赖、日志、worker/thread 等要求不在本文重复，执行时以根目录 `AGENTS.md`、当前代码和相关 `ARCHITECTURE.md` 为准。

本文不代表功能已经实现。后续每个里程碑实施前都必须重新核对当前代码。

## 1. 固定决策

- 主页只负责项目、素材处理和素材信息提取，不参与角色卡编译。
- 主页不再设置目标角色。
- 角色卡编译、重编译、预览、导入、导出和元数据管理都放到角色卡页面。
- 角色卡页面使用海报墙管理当前项目的角色卡，并提供搜索/过滤。
- 角色卡包含角色名、别名、备注、封面图片、编译状态、CharaPicker 标准 JSON 和导出信息。
- 封面图片导入需要提供 9:16 固定比例裁剪，带蒙版，裁剪结果作为 cover 使用。
- 默认编译产物是 CharaPicker 标准 JSON。
- Markdown、HTML 展示页和外部复制辅助内容都从 CharaPicker JSON 通过代码转换生成，不要求 LLM 直接输出这些格式。
- HTML 是 CharaPicker 的漂亮展示/验收产物，不替代 Markdown；Markdown 继续用于轻量审阅、复制、diff 和归档。
- 支持导入 CharaPicker 格式人物卡。
- 首批顺手兼容 Character Card V2 JSON 导出，作为 SillyTavern / RisuAI / Agnai / Chub 等生态的通用入口；首版只做纯 JSON，不做 PNG 元数据嵌入。
- 非预览角色卡的 `card_id` 采用“角色名 slug + 随机 UUID 短段”形式，保证唯一性且便于用户在文件夹中识别；角色名后续修改不改变既有 `card_id` 或目录。
- 导入 CharaPicker JSON 时，非预览卡始终按当前项目规则生成新的 `card_id`，并把导入来源 ID 记录到元数据或 `source_context`，避免覆盖已有卡。
- 预览使用弹窗；HTML 可作为默认展示视图，Markdown 要保留渲染和源码查看入口，JSON 要默认展示为人类友好的结构化视图，不直接把原始花括号文本作为默认视图。
- 首版支持硬删除正式角色卡，删除前必须二次确认；删除只移除 `knowledge_base/character_cards/{card_id}/`，不自动清理已经导出的 `output/character_cards/` 文件。
- 当前“输出”导航改名为“角色卡”，不新增单独输出页。
- 角色卡落盘结构采用 `character_cards/{card_id}/card.json`。
- 主页素材预览提取只生成预览知识库和洞察流，不自动生成角色卡；角色卡页面发起“角色卡预览”时，才生成项目级唯一固定 ID 的预览草稿角色卡。
- 角色卡预览草稿仅用于验证，不加入正式角色卡扫描；角色卡预览完成后弹窗默认展示 CharaPicker HTML 或等价渲染视图，并保留 Markdown/JSON 切换。
- 预览草稿不应给用户留档，不应被当作可用角色卡；每次预览覆盖同一个预览草稿 ID。
- 角色卡别名只给用户查看和管理使用，不参与编译证据匹配。
- 角色卡目录放在各自项目目录中，不做跨项目全局角色卡库。
- 裁剪导入功能开发阶段先保存原图副本；整个流程开发、bug 修复和用户验收完成后，收尾处理需要删除项目内原图副本，只保留裁剪后的图片。
- 首个外部适配目标是 AstrBot 手动复制工作流，而不是 AstrBot 可导入 JSON。
- AstrBot 首版只提供可供用户一条条复制到 AstrBot 的内容：名称、系统提示词、可选自定义报错回复信息、预设对话；工具、MCP 工具和 Skills 暂不纳入 CharaPicker 输出范围。
- 如果 PR #4532 或等价改动已合并，且 AstrBot 官方本体提供稳定人格导入/导出格式，本计划应改为适配官方导入/导出格式，而不是继续只做手动复制辅助。

## 2. 待确认取舍

- AstrBot demo 到位后，确认“自定义报错回复信息（可选）”在界面中的最终名称和填写限制。
- 实施 M47 前重新检查 PR #4532 或等价官方改动是否已合并；如果已合并，先更新本计划中的 AstrBot 里程碑和提交分组。

## 3. AstrBot 官方资料记录

最近核对日期：2026-05-16。

- 官方配置文档：`https://docs.astrbot.app/dev/astrbot-config.html`
- 官方开发文档：`https://docs.astrbot.app/dev/star/guides/ai.html`
- 参考 PR：`https://github.com/AstrBotDevs/AstrBot/pull/4532`
- 当前 AstrBot v4 文档说明 `persona` 配置项已废弃，应使用 WebUI 配置人格。
- 旧版人格字段包含 `id`、`name`、`description`、`system_prompt`。
- 开发文档中的 Persona 模型包含 `persona_id`、`system_prompt`、`begin_dialogs`、`tools` 等字段。
- PR #4532 当前仍处于 open / 未合并状态，导入/导出功能和字段名在合并前可能变化。
- PR #4532 的候选导出结构为 `{"version":"1.0","persona":[{"name": "...","prompt": "...","begin_dialogs":[{"user":"...","assistant":"..."}]}]}`。
- PR #4532 的导入逻辑会把 `persona[0].name` 转为 `persona_id`，`persona[0].prompt` 转为 `system_prompt`，并把每组 `{user, assistant}` 展平成 AstrBot 内部的 `begin_dialogs` 列表。
- 用户提供的 demo 截图还展示了“自定义报错回复信息（可选）”，但该字段需要等待 demo JSON 或后续 PR 字段确认后再写入正式映射。
- 工具 / MCP 工具选择和 Skills 选择当前与 CharaPicker 角色卡输出无关，首版不生成这些字段。
- 本计划当前不以 PR #4532 的导入 JSON 为实现标准；首版只做 AstrBot 手动复制辅助。PR #4532 和用户 demo 只作为字段理解参考。
- 若 PR #4532 或等价官方实现合并，应重新核对官方最终 schema，并优先实现 CharaPicker JSON 到官方人格导入 JSON 的导出路径。

## 4. 目标边界

主页：

- 负责项目选择、素材导入、素材处理、预览提取、正式提取、洞察流和进度展示。
- 不保存或编辑目标角色。
- 不自动生成角色卡。

角色卡页面：

- 负责角色卡海报墙、搜索/过滤、选择、创建、编辑、封面裁剪、预览、编译、重编译、导入和导出。
- 不直接解析素材文件。
- 不直接写入 chunk、episode、season 提取产物。

核心链路：

```text
正式知识库
-> compiler
-> CharaPicker Card JSON
-> Markdown / HTML renderers
-> AstrBot 手动复制视图
```

推荐项目数据方向：

```text
projects/{project_id}/knowledge_base/
├── seasons/
└── character_cards/
    └── {card_id}/
        ├── card.json
        ├── cover.png
        └── original_cover.{ext}

projects/{project_id}/knowledge_base/
└── preview_character_cards/
    └── preview_card/
        └── card.json

projects/{project_id}/output/
└── character_cards/
    ├── {card_id}.md
    ├── {card_id}.html
    ├── {card_id}.json
    ├── {card_id}.character-card-v2.json
    └── {card_id}.astrbot-copy.md
```

正式角色卡扫描只读取 `knowledge_base/character_cards/`。预览草稿角色卡放在隔离目录，或使用等价隔离机制，不能混入正式角色卡海报墙。预览草稿使用项目级唯一固定 ID，例如 `preview_card`，每次预览覆盖它。

## 5. CharaPicker 卡格式草案

CharaPicker JSON 是本程序的主格式，不直接等同于 SillyTavern / Character Card V2、Character.AI、Agnai 或 AstrBot 的格式。它的目标是“信息尽量完整、证据可追溯、导出可降级”：内部保留丰富结构，导出到外部软件时再按目标软件能力裁剪和格式化。

格式参考：

- SillyTavern / Character Card V2 常见核心字段：`name`、`description`、`personality`、`scenario`、`first_mes`、`mes_example`、`creator_notes`、`system_prompt`、`post_history_instructions`、`alternate_greetings`、`character_book`、`tags`、`creator`、`character_version`、`extensions`。
- SillyTavern 角色编辑还强调头像、收藏/标签、token 统计、世界书/角色书、主提示词覆盖、后历史指令、角色注释、对话示例、群聊触发概率等。
- Character.AI 常见人格信息包括 `name`、头像、tagline / short description、long description、greeting、suggested starters、categories、visibility、example conversations、definition；其中 `definition` 是大段自由文本，可包含结构化说明和对话示例。
- Agnai 常见人格信息包括 `name`、personality、description / creator notes、appearance prompt、scenario、greeting / alternate greeting、sample conversation、system prompt、post-history instructions、author note、character book、creator、character version。
- RisuAI / Character Card V2 / V3 生态中的 lorebook / character book 提醒我们：角色卡需要能携带触发式知识条目、插入顺序、token 预算、启用状态和扩展字段。
- AstrBot 首版只作为“手动复制目标”参考：名称、系统提示词、自定义报错回复信息、任意组数预设对话。工具、MCP 工具和 Skills 暂不进入 CharaPicker 首版导出目标。

参考资料链接：

- `https://github.com/malfoyslastname/character-card-spec-v2/blob/main/spec_v2.md`
- `https://docs.sillytavern.app/usage/core-concepts/characterdesign/`
- `https://docs.sillytavern.app/usage/characters/`
- `https://agnai.guide/docs/creating-a-character/`
- `https://book.character.ai/character-book/how-to-quick-creation`
- `https://book.character.ai/character-book/character-attributes/definition`
- `https://book.character.ai/character-book/character-attributes/greeting`
- `https://github.com/kwaroran/RisuAI/wiki/Lorebook`
- `https://github.com/kwaroran/character-card-spec-v3/blob/main/SPEC_V3.md`

### 5.1 顶层结构

```json
{
  "format": "charapicker.card",
  "schema_version": 1,
  "card_id": "",
  "card_kind": "official",
  "project_id": "",
  "created_at": "",
  "updated_at": "",
  "compiled_at": "",
  "revision": 1,
  "compile_status": "empty",
  "compile_source": "manual",
  "identity": {},
  "assets": {},
  "user_metadata": {},
  "source_context": {},
  "profile": {},
  "prompt_surfaces": {},
  "dialogue": {},
  "character_book": {},
  "relationships": [],
  "timeline": [],
  "evidence": {},
  "quality": {},
  "export_profiles": {},
  "extensions": {}
}
```

顶层字段约定：

- `format`：固定为 `charapicker.card`，用于和外部导入格式区分。
- `schema_version`：整数版本；后续迁移按版本处理，不用外部格式版本替代。
- `card_id`：项目内正式角色卡唯一 ID。非预览角色卡采用“角色名 slug + 随机 UUID 短段”形式生成；预览草稿固定为 `preview_card`，并放入隔离目录。
- `card_kind`：`official` / `preview` / `imported` / `template`。正式扫描只接受 `official`。
- `project_id`：所属项目 ID。角色卡不做全局库。
- `created_at`、`updated_at`、`compiled_at`：ISO 8601 字符串。
- `revision`：本卡保存修订号，元数据编辑也递增。
- `compile_status`：`empty` / `draft` / `preview` / `compiled` / `stale` / `failed`。
- `compile_source`：`manual` / `knowledge_base` / `preview` / `imported_charapicker` / `imported_external`。
- `extensions`：为未来外部格式或实验字段保留；导入未知字段时尽量保留，不随意丢弃。

`card_id` 规则：

- 新建和导入的非预览角色卡都必须生成项目内唯一 `card_id`，推荐格式为 `{character_name_slug}-{uuid8}`。
- `character_name_slug` 只用于文件夹可读性，不作为身份唯一来源。
- 修改角色名或显示名不重命名既有 `card_id` 或目录。
- 导入非预览卡时始终生成新 `card_id`，并在 `source_context.imported_card_id` 或等价元数据中记录原 ID。
- `preview_card` 是保留 ID，不能被正式角色卡或导入卡使用。

状态不变量：

- 正式角色卡扫描只接受 `card_kind = "official"`，且不能读取 `preview_character_cards/`。
- `card_kind = "preview"` 必须同时满足 `compile_source = "preview"` 和 `compile_status = "preview"`，并固定使用 `card_id = "preview_card"`。
- `compile_status = "compiled"` 只用于正式知识库编译成功的卡片，通常对应 `compile_source = "knowledge_base"`。
- `compile_status = "draft"` 可对应 `compile_source = "manual"`、`imported_charapicker` 或 `imported_external`。
- `compile_status = "stale"` 只用于曾经有可用正式结果、但关键字段或编译来源变化后的正式角色卡。
- `compile_status = "failed"` 必须保留失败原因或 warnings，不应覆盖上一份可用正式内容。

### 5.2 identity

角色身份字段保留“用户显示”和“编译语义”的区别：

- `character_name`：角色正式名，编译时跟随项目与知识库角色识别结果。
- `display_name`：角色卡展示名，可与正式名不同。
- `aliases`：用户可见别名，只用于展示、搜索、导出时可选附注；不参与编译证据匹配。
- `original_names`：原文名、日文名、中文译名等来源名称列表。
- `romanized_names`：罗马音或其他转写。
- `source_work`：作品或素材集合名。
- `source_work_aliases`：作品别名。
- `role_titles`：身份称谓、头衔、职业、阵营标签。
- `species`、`gender`、`pronouns`、`age_text`：仅在素材中有依据或用户手填时记录；未知则留空。
- `visibility_label`：导出或展示用短标签，对应 Character.AI tagline / short description 一类用途。

### 5.3 assets

角色卡图片与裁剪信息：

- `cover_path`：正式封面，首版约定为同目录 `cover.png`。
- `cover_aspect_ratio`：固定记录为 `9:16`。
- `original_cover_path`：开发阶段可记录原图副本；验收后清理流程删除原图副本时同步清空。
- `crop`：记录 `source_width`、`source_height`、`x`、`y`、`width`、`height`、`scale`，便于后续重新裁剪或排查。
- `image_prompt`：如果未来支持生成图，可记录图像生成提示；首版不需要生成图片。
- `credits`：图片来源、作者或用户备注。
- `external_assets`：保留头像、背景、表情、语音、Live2D 等未来扩展入口；首版只使用封面。

### 5.4 user_metadata

这些字段由用户管理，不应被重新编译轻易覆盖：

- `notes`：角色卡备注。
- `tags`：海报墙过滤标签。
- `favorite`：收藏状态。
- `folder`：未来如果支持分组，可用于虚拟文件夹。
- `manual_reviewed`：用户是否确认过本卡内容。
- `locked_fields`：用户锁定字段列表；后续重编译时避免覆盖。
- `creator`：卡片创建者；本地默认可为空。
- `character_version`：用户可见角色卡版本，不等同于 `schema_version`。

### 5.5 source_context

记录本卡从哪个项目知识库编译而来，保证可追溯：

- `source_project_id`
- `knowledge_base_ref`
- `source_runs`
- `included_seasons`
- `included_episodes`
- `included_chunks`
- `excluded_materials`
- `compiler_version`
- `prompt_profile_id`
- `model_profile_id`
- `compiled_from_preview`：正式卡必须为 `false`；预览草稿为 `true`。

路径记录规则：

- 可导出的 CharaPicker JSON 只能记录项目相对路径、素材 ID、season / episode / chunk ID 或 artifact ref。
- `knowledge_base_ref` 表示项目内知识库引用，不记录本机绝对路径。
- 本机绝对路径只能作为本地调试信息放入非导出缓存或运行日志，不能写入可导出的角色卡 JSON。

### 5.6 profile

`profile` 是 CharaPicker 的核心角色资料，不是直接塞进外部软件的 prompt 字符串。字段尽量结构化，方便导出器按目标格式重组。

- `summary`：短摘要。
- `long_description`：较完整的角色说明，可映射到 Character.AI long description 或外部 description。
- `appearance`：外貌、服装、标志性物件、视觉变化。
- `personality`：核心性格。
- `personality_traits`：结构化性格标签或条目。
- `values_and_beliefs`：价值观、信念、底线。
- `goals_and_motivations`：目标、欲望、动机。
- `fears_and_weaknesses`：恐惧、弱点、限制。
- `likes`、`dislikes`：喜好与厌恶。
- `abilities`：能力、技能、特长。
- `limitations`：不能做、做不到、设定限制。
- `speech_style`：口癖、语气、句式、称呼方式、常用词。
- `behavior_patterns`：行动习惯、社交方式、压力反应。
- `emotional_range`：常见情绪、触发条件、表达方式。
- `relationships_summary`：关系总述，详细关系放入 `relationships`。
- `backstory`：背景经历。
- `current_state`：当前阶段状态。
- `growth_arc`：成长、堕落、转变或阶段变化。
- `scenario_default`：默认互动场景。
- `world_context`：世界观中与该角色密切相关的设定。
- `canon_constraints`：必须保持的原作约束。
- `uncertainties`：证据不足或互相冲突的信息。
- `safety_notes`：导出到外部软件时需要提醒用户的敏感边界或行为限制。

### 5.7 prompt_surfaces

这些字段是从 `profile`、`relationships`、`character_book` 和 `dialogue` 生成的“可投喂/可复制内容”。它们可以被缓存，但应始终能从结构化资料重新生成。

- `system_prompt`：角色扮演总指令，可映射到 SillyTavern system prompt、Agnai system prompt、AstrBot 系统提示词。
- `persona_prompt`：角色人格主体，可映射到 SillyTavern description / personality、Agnai personality、Character.AI definition 的一部分。
- `scenario`：默认互动场景。
- `first_message`：主开场白，对应 `first_mes` / greeting。
- `alternate_greetings`：备用开场白数组。
- `suggested_starters`：用户侧开场建议，对应 Character.AI Suggested Starters 一类功能。
- `example_messages_text`：面向 Character Card V2 `mes_example` 的文本形式。
- `post_history_instructions`：后历史指令 / 强约束。
- `author_note`：可插入到上下文固定深度的角色注释。
- `creator_notes`：不参与 prompt 的创作者备注，可用于导出说明。
- `custom_error_reply`：为 AstrBot 手动复制视图保留的可选字段。
- `markdown_card`：CharaPicker Markdown 渲染缓存；必须可由结构化 JSON 重新生成。
- `html_card`：CharaPicker HTML 展示缓存；必须可由结构化 JSON 重新生成，不能作为事实来源。

### 5.8 dialogue

对话字段要同时满足“展示说话风格”和“AstrBot 预设对话复制”：

- `first_message`
- `alternate_greetings`
- `example_dialogues`：任意组数，每组包含 `turns`。
- `preset_dialogues`：更适合外部软件导入/复制的问答对，可由 `example_dialogues` 精简生成。
- `style_examples`：只展示角色说话方式、不一定是完整对话的片段。

对话 turn 建议结构：

```json
{
  "role": "user",
  "name": "{{user}}",
  "content": "",
  "source_ref_ids": [],
  "purpose": "style"
}
```

`role` 允许 `user`、`assistant`、`system`、`narration`。导出到 AstrBot 手动复制视图时，只使用可明确转为“用户消息 / AI 回答”的 turn；无法映射的叙述性片段放入说明或忽略，并给出 warning。

### 5.9 character_book

首版可以先生成空结构或少量高置信条目，但格式需要预留：

- `name`
- `description`
- `scan_depth`
- `token_budget`
- `recursive_scanning`
- `entries`

entry 建议字段：

- `entry_id`
- `keys`
- `secondary_keys`
- `content`
- `enabled`
- `constant`
- `priority`
- `insertion_order`
- `position`
- `case_sensitive`
- `source_ref_ids`
- `comment`

导出到不支持 lorebook 的目标时，将高优先级常驻条目折叠进 `persona_prompt` 或 `scenario`，并在 `quality.warnings` 中记录降级。

### 5.10 relationships

关系字段独立出来，避免把大量关系塞进一段 description：

- `target_name`
- `target_aliases`
- `relationship_type`
- `summary`
- `attitude`
- `history`
- `current_status`
- `source_ref_ids`
- `confidence`

导出时可按目标软件限制折叠为 `relationships_summary`、`character_book` 条目或 Markdown 章节。

### 5.11 timeline

为本项目“从素材提取角色状态变化”的特点保留阶段状态：

- `stage_id`
- `label`
- `season_id`
- `episode_id`
- `chunk_range`
- `state_summary`
- `appearance_delta`
- `personality_delta`
- `relationship_deltas`
- `knowledge_delta`
- `source_ref_ids`

如果目标格式只能表达静态人格，默认导出 `current_state`，并可在 Markdown 中附带时间线。

### 5.12 evidence

证据字段是 CharaPicker 区别于普通角色卡编辑器的关键。所有编译生成的重要结论都应尽量能追溯。

- `refs`：证据引用列表。
- `by_field`：字段到证据 ID 的映射。
- `conflicts`：冲突证据与处理结果。
- `coverage`：素材覆盖情况。
- `confidence_summary`：整体置信度摘要。

证据引用建议结构：

```json
{
  "ref_id": "",
  "source_type": "chunk",
  "season_id": "",
  "episode_id": "",
  "chunk_id": "",
  "material_ref": "",
  "quote": "",
  "summary": "",
  "confidence": 0.0
}
```

`material_ref` 使用项目相对引用或素材 ID，不记录本机绝对路径。`quote` 应保持短摘录或摘要，避免把大段原始素材复制进角色卡。

### 5.13 quality

用于 UI 提示、导出前检查和后续调试：

- `warnings`
- `validation_errors`
- `missing_recommended_fields`
- `conflict_count`
- `evidence_count`
- `token_estimates`
- `stale_reasons`
- `last_validation_at`

JSON 预览必须按这些结构分组展示，不能直接丢一整坨花括号给用户。

### 5.14 export_profiles

记录由 CharaPicker JSON 派生出的外部输出，不作为事实来源：

- `charapicker_markdown`
- `charapicker_html`
- `charapicker_json`
- `character_card_v2_json`
- `astrbot_copy`
- `sillytavern_candidate`
- `character_ai_copy_candidate`

每个 profile 至少记录：

- `target`
- `generated_at`
- `status`
- `warnings`
- `output_path`
- `field_mapping`

首版正式支持 `charapicker_json`、`charapicker_markdown`、`charapicker_html`、`character_card_v2_json`、`astrbot_copy`。其他候选只作为字段设计兼容目标，不在本次实现里声明可用。

### 5.15 外部格式映射原则

- CharaPicker 内部永远优先保存结构化资料和证据；外部导出是派生产物。
- Markdown 由代码模板格式化生成，不依赖 LLM 直接生成最终 Markdown。
- HTML 由代码模板格式化生成，不依赖 LLM；它用于漂亮预览、展示和验收报告，不替代 Markdown，也不作为事实来源。
- HTML 首版应优先做离线可用的本地单文件或相对资源文件，不拉 CDN，不执行外部脚本，不引入 QWebEngine 或新依赖；用户文本必须转义，避免把角色内容当作 HTML 注入。
- AstrBot 首版导出为“手动复制清单”，字段来自 `identity.character_name`、`prompt_surfaces.system_prompt`、`prompt_surfaces.custom_error_reply`、`dialogue.preset_dialogues`。
- Character Card V2 首版导出纯 JSON，不做 PNG metadata 嵌入；输出应固定包含 `spec = "chara_card_v2"`、`spec_version = "2.0"`、`data`，并把 CharaPicker 字段映射到 `name`、`description`、`personality`、`scenario`、`first_mes`、`mes_example`、`creator_notes`、`system_prompt`、`post_history_instructions`、`alternate_greetings`、`character_book`、`tags`、`creator`、`character_version`、`extensions`。
- Character Card V2 / SillyTavern 映射时，`profile.long_description`、`profile.personality`、`profile.scenario_default`、`dialogue.first_message`、`dialogue.example_dialogues` 分别降级到对应文本字段；无法映射的证据、时间线和质量信息放入 `extensions.charapicker` 或导出 warnings。
- Character.AI 映射时，`visibility_label` 可对应 short description，`long_description` 对应 long description，`first_message` 对应 greeting，`suggested_starters` 对应 Suggested Starters，`persona_prompt` 与 `example_dialogues` 可组合成 definition。
- 如果目标格式没有证据、时间线、关系或 character book 的承载位置，导出器必须给出 warnings，而不是静默丢弃。

## 6. 代码结构设计

本节提前约定后续实现的模块边界。目标是让角色卡功能成为清晰的项目内业务模块，而不是把编译、导入、导出、预览和文件读写堆进页面层或 `main_window.py`。

### 6.1 当前代码结论

- `gui/pages/output_page.py` 当前只是 Markdown 预览页，后续应被“角色卡页面”接收职责。
- `gui/main_window.py` 当前在预览成功后读取 `ProjectConfig.target_characters` 并调用 `core.compiler` / `core.generator` 生成一次简化输出；该链路需要移除或改为只提示预览知识库已生成。
- `core/compiler.py` 当前负责从知识库聚合简化 `CharacterState`，可作为新角色卡编译的底层过渡能力，但不应继续承担导出格式、UI 预览或文件落盘职责。
- `core/generator.py` 当前只有 `render_profile_markdown()`，后续不再作为所有角色卡渲染逻辑的堆放点；新 Markdown/HTML/AstrBot/Character Card V2 渲染应有独立模块。
- `core/knowledge_base.py` 已经是知识库路径和 JSON 读写集中点，适合补充窄路径 helper；角色卡业务规则不应塞入其中。
- `gui/pages/project_page.py` 当前拥有项目选择与配置收集能力，但缺少专门给其他页面订阅的项目切换信号；角色卡页面需要稳定拿到当前 `project_id`。

### 6.2 核心模块边界

建议新增或改造下列核心模块。文件名可在实施时按现有代码风格微调，但职责边界不应改变。

`core/models.py`

- 放置角色卡 Pydantic 模型和枚举；若实现时模型过多导致 `models.py` 过度膨胀，可拆出 `core/character_card_models.py`，再由 `core.models` 做兼容导出或集中引用。
- 只定义数据结构、默认值和轻量校验，不做文件读写、不做 UI 展示、不做导出格式拼接。
- 首批建议新增：`CharacterCard`、`CharacterCardSummary`、`CharacterCardIdentity`、`CharacterCardAssets`、`CharacterCardUserMetadata`、`CharacterCardSourceContext`、`CharacterCardProfile`、`CharacterCardPromptSurfaces`、`CharacterCardDialogue`、`CharacterCardBook`、`CharacterCardEvidence`、`CharacterCardQuality`、`CharacterCardExportProfiles`。
- 首批建议新增枚举：`CharacterCardKind`、`CharacterCardStatus`、`CharacterCardCompileSource`、`DialogueRole`、`CharacterCardExportTarget`、`CharacterCardExportStatus`。

`core/knowledge_base.py`

- 只补充角色卡路径 helper，不放业务逻辑。
- 建议 helper：`character_cards_root_path()`、`character_card_dir_path()`、`character_card_json_path()`、`preview_character_cards_root_path()`、`preview_character_card_dir_path()`、`preview_character_card_json_path()`。
- 路径 helper 必须由后续 store/导出器复用，页面层不直接拼接 `knowledge_base/character_cards/...`。

`core/character_card_store.py`

- 负责角色卡仓库语义：创建、读取、保存、列表、状态更新、硬删除、预览草稿写入和封面路径登记。
- 对外返回模型对象或轻量 summary，不返回未校验的原始 dict。
- 处理损坏卡跳过、未知字段保留、旧 schema 兼容和 UTF-8 缩进写入。
- 不调用 LLM、不创建 Qt 控件、不渲染 Markdown/HTML。
- 建议接口：`create_empty_card()`、`generate_card_id()`、`load_card()`、`save_card()`、`delete_card()`、`list_card_summaries()`、`load_preview_card()`、`save_preview_card()`、`mark_card_stale()`、`resolve_cover_paths()`、`clear_original_cover_reference()`。

`core/character_card_compiler.py`

- 负责从正式知识库或预览知识库生成 `CharacterCard`。
- 可复用 `core.compiler` 的阶段状态聚合能力，但新模块负责把聚合结果映射进 CharaPicker card schema。
- 不写 UI，不直接展示弹窗；是否保存由调用方或 store 处理。
- 不读取原始素材，不读取主页目标角色配置。
- 建议接口：`compile_card_from_knowledge_base()`、`compile_preview_card_from_preview_knowledge_base()`、`build_compile_target()`、`collect_compile_warnings()`。

`core/character_card_renderers.py`

- 负责从 `CharacterCard` 生成展示内容。
- 函数应尽量是纯函数，方便测试。
- 建议接口：`render_card_markdown()`、`render_card_html()`、`build_human_json_sections()`。
- HTML 渲染必须集中在这里转义用户文本；页面层不手写 HTML 拼接。
- Markdown 和 HTML 都只读 CharaPicker JSON 模型，不互相作为输入。

`core/character_card_formats.py`

- 负责外部格式映射，不负责写文件。
- 建议接口：`to_character_card_v2_json()`、`to_astrbot_copy_sections()`、`to_astrbot_copy_markdown()`。
- 无法映射字段时返回 warnings，不静默丢弃。
- Character Card V2 的 `extensions.charapicker` 在这里统一生成，避免导出器和页面各写一套映射。

`core/character_card_exporter.py`

- 负责把 CharaPicker card 派生产物写入 `projects/{project_id}/output/character_cards/`。
- 调用 renderers 和 formats，但不包含字段映射细节。
- 建议接口：`export_charapicker_json()`、`export_markdown()`、`export_html()`、`export_character_card_v2_json()`、`export_astrbot_copy_markdown()`、`export_selected_targets()`。
- 返回 `CharacterCardExportResult` 或等价结构，包含输出路径、warnings 和失败原因。

`core/character_card_importer.py`

- 负责导入 CharaPicker JSON 的校验、schema 迁移和冲突策略。
- 不弹文件选择器，不写 UI 文案；错误用结构化异常或结果对象表达。
- 首版只导入 CharaPicker JSON；Character Card V2 反向导入可作为后续能力。

### 6.3 GUI 模块边界

`gui/pages/character_card_page.py`

- 接收原 `output_page.py` 的导航职责，成为角色卡页面。
- 负责海报墙、搜索过滤、当前卡选择、元数据编辑、删除确认、操作按钮状态、预览弹窗触发和用户反馈。
- 不直接编译角色卡、不直接拼接知识库路径、不直接序列化 JSON。
- 只通过核心 store/compiler/exporter/importer 接口和 worker 交互。

`gui/pages/output_page.py`

- 实施完成后不再作为主导航页面。
- 可在过渡提交中保留为兼容 shim，但最终不应保留一套与角色卡页面重复的输出逻辑。

`gui/widgets/character_card_gallery.py`

- 海报墙组件，只消费 `CharacterCardSummary` 或等价轻量数据。
- 只负责卡片布局、选中态、空状态和搜索结果展示。
- 不读取文件，不调用编译器。

`gui/widgets/character_card_detail_panel.py`

- 当前角色卡的别名、备注、封面、状态和操作区。
- 编辑动作向页面发出结构化变更，不直接落盘。
- 删除按钮只发出删除请求，由页面弹二次确认后调用 store。
- 重编译 stale 提示在这里展示，但状态判断来自核心模型或页面状态。

`gui/widgets/character_card_preview_dialog.py`

- 角色卡预览弹窗，提供 HTML、Markdown、JSON、AstrBot、Character Card V2 等视图切换。
- JSON 视图使用人类友好分组，不默认展示原始花括号文本。
- 只展示已经由 core 生成的内容；不在弹窗内重新编译或导出。

`gui/widgets/human_json_view.py`

- 可复用的结构化 JSON 展示组件。
- 输入是 `build_human_json_sections()` 这类分组数据，不直接理解 CharaPicker 业务。

`gui/widgets/cover_crop_dialog.py`

- 只负责 9:16 裁剪交互、蒙版和裁剪参数确认。
- 不自行决定角色卡目录；保存前必须由 core store 提供或确认目标路径。
- 若裁剪操作需要 Qt 图像能力，图像处理可以留在 GUI 层，但路径安全和元数据更新必须通过 store。

`gui/workers/character_card_workers.py`

- 放置角色卡编译、导入、导出等耗时操作的 Qt worker。
- worker 只桥接 Qt Signal 和 core 调用，不包含业务规则。
- 结果通过可序列化 dict 或 Pydantic dump 传回页面。

### 6.4 主窗口和项目切换

- `gui/main_window.py` 只负责创建页面、导航和跨页面信号连接。
- 主窗口应从 `OutputPage` 切换为 `CharacterCardPage`，导航文案使用 `app.nav.characterCards` 或等价 i18n key。
- `ProjectPage` 应新增项目切换信号，例如 `projectChanged = pyqtSignal(object)`，在新建、删除、切换、保存后向角色卡页面同步当前项目。
- `CharacterCardPage.set_project(config_or_none)` 只接收项目上下文并刷新角色卡列表，不向项目页反向读取控件状态。
- 预览提取成功后，主窗口不再根据 `target_characters` 生成输出页内容；只提示预览知识库已更新，并可引导用户到角色卡页生成预览草稿。

### 6.5 数据流

正式角色卡编译：

```text
CharacterCardPage
-> CharacterCardCompileWorker
-> core.character_card_compiler.compile_card_from_knowledge_base()
-> core.character_card_store.save_card()
-> CharacterCardPage.refresh_gallery()
-> CharacterCardPreviewDialog
```

预览草稿：

```text
CharacterCardPage preview action
-> CharacterCardPreviewWorker
-> core.character_card_compiler.compile_preview_card_from_preview_knowledge_base()
-> core.character_card_store.save_preview_card()
-> CharacterCardPreviewDialog
```

主页素材预览提取成功只负责更新预览知识库，不触发上述预览草稿流程。

导出：

```text
CharacterCardPage selected card
-> CharacterCardExportWorker
-> core.character_card_exporter.export_selected_targets()
-> output/character_cards/
-> UI success path + warnings
```

导入：

```text
CharacterCardPage file picker
-> CharacterCardImportWorker
-> core.character_card_importer.import_charapicker_card()
-> core.character_card_store.save_card()
-> CharacterCardPage.refresh_gallery()
```

封面裁剪：

```text
CharacterCardPage select image
-> CoverCropDialog returns crop result / PNG bytes / crop metadata
-> core.character_card_store.resolve_cover_paths()
-> core asset/store helper writes cropped cover to approved cover path
-> core.character_card_store.save_card() updates assets metadata
```

### 6.6 旧模块处理

- `core.compiler` 保留为正式知识库聚合与阶段状态过渡模块；不要把导出器、HTML、JSON 预览塞进去。
- `core.generator` 可短期保留旧函数，迁移完成后要么改成调用 `character_card_renderers` 的薄兼容层，要么在确认无引用后删除。
- `gui/pages/output_page.py` 可短期保留，最终导航不再引用；若保留文件，必须没有并行业务逻辑。
- `ProjectConfig.target_characters` 可为旧项目兼容保留字段，但新角色卡编译链路不得读取它。

### 6.7 测试和验证结构

- 若仓库仍无正式测试目录，首批可用轻量脚本或后续新增 `tests/` 针对纯 core 函数做验证。
- 优先覆盖纯函数：schema 校验、store 损坏卡跳过、Markdown/HTML 渲染、Character Card V2 映射、AstrBot copy section 生成。
- GUI 验证以 `python -m compileall core gui utils`、可用时的 `ruff check`、以及人工启动应用为主。
- HTML 渲染至少验证文本转义、无外部资源、封面相对路径和空字段展示。

## 7. 代码自审查与架构清洁约束

本节是后续实现时的强制自审查要求。它不要求为了“整洁”做无关大重构；只处理本次任务引入或直接触及的结构问题、冗余代码和逻辑风险。发现历史遗留但不属于本次范围的问题时，记录为后续事项，不混入当前阶段。

每个提交分组完成后都必须先完成一次局部自审查，再进入提交或下一阶段。所有开发提交完成后、进入用户验收前，必须再做一次整体自审查。

局部自审查清单：

- 页面职责：角色卡页面只负责交互、状态展示和触发 worker；不直接解析素材、不直接编译 prompt、不直接操作底层知识库细节。
- 核心职责：角色卡编译、格式转换、导出映射和校验逻辑有明确归属；同一规则不在 `gui`、`core`、`utils` 多处各写一份。
- 数据来源：正式角色卡只从正式知识库和角色卡目录读取；预览草稿、正式卡和导出产物路径不混用。
- 母本约束：CharaPicker JSON 是事实来源；Markdown、HTML、Character Card V2 JSON、AstrBot 复制清单都只能作为派生产物。
- 状态机：`empty`、`draft`、`preview`、`compiled`、`stale`、`failed` 等状态切换有单一判断入口，UI 不靠零散布尔值拼状态。
- 冗余代码：删除本阶段引入的未使用 import、未使用变量、死分支、重复 helper、重复字段映射和过期 TODO。
- 命名一致：同一概念只保留一组命名，例如 `card_id`、`character_name`、`display_name`、`cover_path`，避免 UI、模型和导出器各自起名。
- 错误处理：用户可恢复的问题给 UI 反馈；开发排查信息进日志；不吞异常，不把失败伪装成空结果。
- 导出映射：每个外部格式都有清楚的字段映射和 warnings；无法映射的信息不静默丢弃。
- 兼容策略：旧项目字段、旧输出入口和导入未知字段有明确处理策略，不靠偶然容错。
- 安全边界：HTML 渲染必须转义用户文本；本地路径、封面和导出文件不拼接不可信路径片段。
- 代码体积：新增抽象必须减少真实重复或隔离清晰职责；不为单次调用制造空壳抽象。

整体自审查清单：

- 从主页到角色卡页面的分页责任已经干净分离，没有残留“主页目标角色驱动编译”的新路径。
- 角色卡落盘、扫描、预览草稿、导出目录之间没有交叉污染。
- CharaPicker JSON schema、导入校验、渲染器、导出器使用同一套字段理解。
- Markdown 和 HTML 都能从同一张 CharaPicker JSON 重新生成，不保存互相依赖的派生状态。
- Character Card V2 与 AstrBot 复制辅助都只读取 CharaPicker JSON，不绕过母本读取 UI 状态。
- 操作按钮、worker、错误反馈和日志之间没有重复状态判断。
- 本次新增代码没有明显重复模块、过时注释、临时调试输出或未完成占位逻辑。
- 可运行的验证命令已经执行；无法运行的验证要说明原因和残余风险。

自审查发现的问题处理原则：

- 本阶段新引入的问题必须在本阶段修复后再提交。
- 跨阶段暴露但属于本任务范围的问题，放入最近的相关提交修复，必要时经用户确认拆分一次提交。
- 与本任务无关的历史问题只记录，不擅自大改。
- 若发现计划本身导致架构变脏，先更新计划并向用户说明，再继续实现。

## 8. 里程碑

### M01：核对当前实现入口

交付：

- 只记录当前代码中与项目页目标角色、输出页、编译器、生成器和知识库角色卡相关的实际入口。

验收：

- 明确哪些文件需要在后续里程碑修改。
- 明确当前是否仍存在 `ProjectConfig.target_characters` 的调用点。
- 不改代码。

### M02：将输出导航改名为角色卡

交付：

- 当前“输出”导航改名为“角色卡”。

验收：

- 主导航显示“角色卡”。
- 不新增并列的独立输出页。
- 原输出页职责被角色卡页面接收。

### M03：移除主页目标角色输入控件

交付：

- 主页不再显示目标角色输入框。

验收：

- 新建或切换项目时，主页不出现目标角色字段。
- 主页布局没有明显空洞或错位。

### M04：保留旧项目配置兼容

交付：

- 旧项目中的 `target_characters` 仍可读取，但主页不再编辑它。

验收：

- 含旧字段的 `config.json` 能打开。
- 保存项目不会因为旧字段缺失或存在而失败。

### M05：清理主页配置收集逻辑

交付：

- 主页生成当前配置时不再从 UI 收集目标角色。

验收：

- 预览和正式提取仍可启动。
- 提取入口不要求目标角色。

### M06：清理提取启动日志与洞察文案中的目标角色语义

交付：

- 提取启动反馈不再显示“目标角色：...”。

验收：

- 预览和正式提取的用户可见文案不暗示按目标角色筛选。
- 普通日志也不再把目标角色数量作为提取关键参数。

### M07：取消预览完成后的自动角色卡生成

交付：

- 预览成功后只提示知识库预览结果已生成，不自动把某个角色写入输出/角色卡页。

验收：

- 预览完成不会调用第一个目标角色生成角色卡。
- 用户下一步被引导到角色卡页面创建或编译角色卡。
- 本里程碑不禁止角色卡页面后续根据预览知识库生成隔离预览草稿；两者是不同入口。

### M08：建立正式角色卡路径 helper

交付：

- 为 `knowledge_base/character_cards/{card_id}/card.json` 建立路径、列表和基础读写 helper。

验收：

- 页面或编译器不直接拼接角色卡文件路径。
- helper 不影响现有 `seasons/` 知识库路径。
- 正式角色卡扫描只读取 `character_cards/`。

### M09：建立项目级唯一预览草稿隔离路径

交付：

- 为项目级唯一固定 ID 的预览草稿角色卡建立隔离路径。

验收：

- 预览草稿不会被正式角色卡列表扫描到。
- 每次预览覆盖或更新同一个预览草稿 ID，不产生新的正式卡片。
- 预览草稿明确带 `card_kind = "preview"`、`compile_source = "preview"`、`compile_status = "preview"` 或等价标记。
- 预览草稿不作为用户可管理角色卡展示。

### M10：定义 CharaPicker 角色卡模型

交付：

- 在核心模型中定义首版 CharaPicker 角色卡结构。

验收：

- 模型包含角色名、显示名、别名、备注、cover、编译状态、profile、evidence、warnings 和导出信息。
- `schema_version` 明确。

### M11：定义角色卡状态枚举

交付：

- 明确 `empty`、`draft`、`compiled`、`stale`、`failed` 等状态。

验收：

- UI 和保存数据使用同一套状态值。
- 状态能表达未编译、已编译、需重编译和失败。

### M12：实现角色卡创建保存读取

交付：

- 能创建空角色卡草稿并保存为 CharaPicker JSON。

验收：

- 重新打开项目后能列出并读取该角色卡。
- 角色卡 JSON 保持 UTF-8 和可读缩进。

### M13：实现角色卡列表读取

交付：

- 能读取当前项目下所有正式角色卡元数据。

验收：

- 损坏的单张角色卡不会阻断其他角色卡显示。
- 损坏项有可诊断的警告。
- 预览草稿角色卡不出现在正式列表中。

### M14：建立角色卡图片目录规则

交付：

- 明确 cover、原图副本、临时裁剪文件的项目内位置。

验收：

- 图片不写入 `res/`。
- 外部图片导入后，角色卡不依赖原始外部路径才能显示 cover。
- 初始保留复制到项目目录的原图副本。

### M15：实现角色卡页面空壳

交付：

- 创建角色卡页面或改造输出页为角色卡页面。

验收：

- 页面能随当前项目切换刷新。
- 无项目时显示禁用或空状态。

### M16：实现海报墙数据模型

交付：

- 海报墙使用可扩展的数据模型承载角色卡列表。

验收：

- 支持至少名称、别名、状态、cover、更新时间字段。
- 后续可接入 model/delegate 或分页，避免大量 QWidget 堆叠成为固定设计。

### M17：实现海报墙卡片展示

交付：

- 角色卡以海报墙样式展示。

验收：

- 卡片显示 cover、显示名、状态。
- 无 cover 时有稳定占位。
- 亮暗主题下文本可读。

### M18：实现搜索与过滤

交付：

- 支持按角色名、显示名、别名、备注和状态搜索/过滤。

验收：

- 搜索结果实时更新或明确触发更新。
- 无结果时有清楚空状态。

### M19：实现角色卡选择状态

交付：

- 用户可选中一张角色卡作为当前角色卡。

验收：

- 选中状态在海报墙上清晰可见。
- 右侧详情或操作区随选中角色卡刷新。

### M20：实现新建角色卡入口

交付：

- 角色卡页面提供新建角色卡入口。

验收：

- 新建时至少要求角色名。
- 新建后生成稳定且项目内唯一的 `card_id`，推荐格式为 `{character_name_slug}-{uuid8}`。
- 角色名后续修改不改变既有 `card_id` 或目录。
- 新卡以草稿状态出现。

### M20A：实现角色卡硬删除

交付：

- 角色卡页面提供删除当前正式角色卡的入口。

验收：

- 删除前必须二次确认，确认文案明确说明会删除 `knowledge_base/character_cards/{card_id}/`。
- 删除只移除当前项目内对应角色卡目录，不删除正式知识库 `seasons/`，不自动删除 `output/character_cards/` 已导出的文件。
- 预览草稿不通过正式角色卡删除入口管理。
- 删除后海报墙、详情面板和当前选中状态刷新正确。

### M21：实现角色名编辑

交付：

- 支持修改角色名。

验收：

- 修改角色名后保存成功。
- 已编译角色卡被标记为 `stale`，或提示需要重编译。

### M22：实现别名编辑

交付：

- 支持添加、删除、修改别名。

验收：

- 别名保存后能用于搜索。
- 别名不参与编译证据匹配。
- 修改别名不应触发必须重编译。

### M23：实现备注编辑

交付：

- 支持编辑用户备注。

验收：

- 备注可保存、读取和搜索。
- 备注不会被写入提取事实或编译证据。

### M24：实现图片选择与复制

交付：

- 支持从本地选择角色卡图片，并复制到项目角色卡目录。

验收：

- 原始外部图片删除后，项目内角色卡仍可显示已导入图片。
- 不支持的图片格式给出明确反馈。
- 项目内保留原图副本，供后续重新裁剪。

### M25：实现 9:16 裁剪弹窗

交付：

- 选择图片后打开固定 9:16 蒙版裁剪弹窗。

验收：

- 支持拖拽、缩放、重置和确认。
- 蒙版区域始终保持 9:16。
- 小图、大图、横图、竖图都能处理。

### M26：保存裁剪后的 cover

交付：

- 裁剪结果保存为项目内 `cover.png` 或等价固定文件。

验收：

- 海报墙使用裁剪后的 cover。
- 重新打开项目后 cover 正常显示。

### M27：实现封面替换与清除

交付：

- 支持替换和清除角色卡封面。

验收：

- 清除后回到占位封面。
- 替换不会留下 UI 仍显示旧图的缓存问题。

### M28：实现操作按钮启用规则

交付：

- 当前角色卡的预览、编译、重编译、导出、导入、删除等按钮有明确启用/禁用规则。

验收：

- 未选择角色卡时不可误触依赖选中项的操作。
- 无正式知识库时编译按钮给出明确不可用原因。
- 删除按钮只对正式角色卡可用，不对预览草稿可用。

### M29：实现预览弹窗外壳

交付：

- 预览按钮打开角色卡预览弹窗。

验收：

- 弹窗能切换 CharaPicker HTML、Markdown、JSON 和已支持外部格式。
- 没有对应内容时显示清楚空状态。

### M30：实现人类友好 JSON 预览

交付：

- JSON 预览默认使用结构化展示。

验收：

- 默认不是原始 JSON 花括号文本。
- 字段按基础信息、封面、编译信息、profile、证据、警告、导出信息分组。
- 列表内容分块展示。
- 提供复制格式化 JSON 的入口。

### M31：实现 Markdown / HTML 渲染预览

交付：

- Markdown 预览显示渲染结果。
- HTML 预览显示更适合角色卡验收的展示版内容。

验收：

- 标题、段落、列表、图片引用至少能清楚呈现。
- 提供查看或复制 Markdown 源码的入口。
- HTML 由 CharaPicker JSON 生成，不调用 LLM。
- HTML 预览不拉 CDN，不执行外部脚本，用户文本经过转义。

### M32：定义编译目标对象

交付：

- 编译入口使用角色卡目标对象，而不是项目配置目标角色。

验收：

- 目标对象包含角色名、card_id 和编译来源。
- 别名不作为证据匹配输入。
- 编译器不读取 `ProjectConfig.target_characters`。

### M33：检测正式知识库可用性

交付：

- 编译前检查正式 `episode_content.json` 或后续正式阶段状态是否可用。

验收：

- 没有正式知识库时不伪造正式结果。
- 错误反馈区分“无知识库”“只有预览产物”“结构损坏”。

### M34：实现角色卡编译 worker

交付：

- 编译和重编译在后台 worker/thread 中运行。

验收：

- UI 不冻结。
- 成功、失败、进度和取消状态能回到页面。

### M35：实现按正式知识库编译 CharaPicker JSON

交付：

- 从正式知识库编译生成 CharaPicker 标准 JSON。

验收：

- 不重新读取原始素材。
- 不消费 preview 或 legacy 产物作为正式结果。
- 结果写入当前角色卡 `card.json`。

### M36：写入角色卡内阶段状态

交付：

- 编译时优先把阶段状态、时间线和证据链写入当前角色卡 `card.json` 的 `timeline` / `evidence`。

验收：

- 阶段状态按季/集顺序可追溯。
- 角色卡编译不反向修改正式知识库中的 `character_stage_states.json`。
- 如后续确需维护共享阶段状态缓存，必须作为独立缓存里程碑设计，不能混入首版角色卡编译。

### M37：记录编译警告

交付：

- 编译结果记录证据不足、角色未匹配、冲突未消解等警告。

验收：

- 警告写入角色卡 JSON。
- 角色卡页面能展示警告摘要。

### M38：实现 stale 状态

交付：

- 角色名或关键编译配置变化后，已编译角色卡进入 `stale` 或等价状态；别名只用于用户查看和搜索，不触发必须重编译。

验收：

- stale 卡片在海报墙和详情中可见。
- 重编译后恢复为 compiled 或 failed。

### M39：实现重编译

交付：

- 对已有角色卡重新运行编译。

验收：

- 重编译覆盖当前 CharaPicker JSON 前有清楚确认或可恢复策略。
- 失败时保留上一次成功结果，或明确标记已失效。

### M40：实现预览草稿角色卡生成

交付：

- 用户在角色卡页面触发“角色卡预览”时，基于已有预览知识库生成项目级唯一固定 ID 的预览草稿角色卡。

验收：

- 预览草稿只使用 preview 产物。
- 主页素材预览提取完成不会自动生成预览草稿角色卡。
- 预览草稿不加入正式角色卡扫描。
- 每次预览更新同一个固定 ID。
- 预览草稿不进入海报墙，不提供正式导出入口。

### M41：预览完成弹出 CharaPicker 角色卡展示

交付：

- 预览草稿生成后弹出 CharaPicker HTML 展示预览，并可切换到 Markdown 和 JSON。

验收：

- 弹窗默认展示的是渲染后的展示视图，不是原始 JSON。
- Markdown 渲染结果仍可查看和复制。
- 弹窗明确标记该内容仅用于验证，不是正式角色卡。

### M42：实现 CharaPicker JSON 导入校验

交付：

- 导入 CharaPicker 格式人物卡时进行 schema 校验。

验收：

- 缺少必要字段时给出明确错误。
- 未知字段策略明确：保留、忽略或放入扩展字段。

### M43：实现 CharaPicker JSON 导入落盘

交付：

- 校验通过的 CharaPicker JSON 可导入当前项目角色卡目录。

验收：

- 导入后出现在海报墙。
- 导入时生成项目内唯一 `card_id`，并记录原始导入 ID，避免覆盖当前项目已有角色卡。
- 图片引用缺失时仍能导入并提示。

### M44：实现 CharaPicker JSON 到 Markdown 渲染器

交付：

- 由代码规则生成 Markdown。

验收：

- 不调用 LLM。
- Markdown 包含角色名、别名、备注、cover 引用、摘要、冲突/警告和证据统计。

### M45：实现 CharaPicker JSON 到 HTML 渲染器

交付：

- 由代码规则生成 CharaPicker HTML 展示页。

验收：

- 不调用 LLM。
- HTML 包含封面、身份信息、摘要、人格模块、关系、时间线、证据统计、警告和导出字段提示。
- HTML 不依赖外部网络资源。
- 用户文本经过 HTML 转义。

### M46：实现 CharaPicker JSON / Markdown / HTML / Character Card V2 JSON 导出

交付：

- 当前角色卡可导出 CharaPicker JSON。
- 当前角色卡可导出 Markdown 到 `output/character_cards/`。
- 当前角色卡可导出 HTML 到 `output/character_cards/`。
- 当前角色卡可导出 Character Card V2 JSON 到 `output/character_cards/`。

验收：

- 导出的 JSON 可再次导入。
- 导出不修改知识库原始角色卡。
- Markdown 和 HTML 文件名稳定。
- Character Card V2 JSON 文件名稳定，建议为 `{card_id}.character-card-v2.json`。
- Character Card V2 JSON 包含 `spec = "chara_card_v2"`、`spec_version = "2.0"`、`data`。
- Character Card V2 导出不声明为 PNG 角色卡，不写入 PNG metadata。
- 无法映射的 CharaPicker 字段进入 `extensions.charapicker` 或导出 warnings。
- 覆盖策略明确。
- 导出后能从 UI 看到成功路径。

### M47：补充 AstrBot 手动复制字段说明

交付：

- 参考 AstrBot 官方文档、PR #4532、用户截图和后续 demo，在计划或专门文档中记录 AstrBot 手动复制字段说明。

验收：

- 明确首版目标不是生成 AstrBot 可导入 JSON，而是提供可逐项复制到 AstrBot 的内容。
- 明确需要展示和复制的字段：名称、系统提示词、自定义报错回复信息、预设对话。
- 明确预设对话支持任意组数，每组包含用户消息和 AI 回复。
- 明确 demo 中“自定义报错回复信息（可选）”的生成策略和缺省策略。
- 明确 CharaPicker 字段如何生成 AstrBot 复制内容。
- 明确无法生成字段的处理方式。
- 明确工具 / MCP 工具和 Skills 不在首版导出范围。
- 引用官方文档、PR #4532，并标注仍需 demo 校验的部分。
- 第三方插件消费格式不混入本里程碑。
- 如果实施时 PR #4532 或等价官方导入/导出功能已经合并，本里程碑需先改为“补充 AstrBot 官方导入/导出字段映射说明”。

### M48：实现 AstrBot 手动复制视图

交付：

- 从 CharaPicker JSON 生成 AstrBot 手动复制视图。

验收：

- 不直接读取 episode、chunk 或原始素材。
- 每个字段都有独立复制按钮或等价复制入口。
- 预设对话按组展示，每组用户消息和 AI 回复可分别复制。
- 不生成工具 / MCP 工具和 Skills 字段。
- 不声称生成结果可直接导入 AstrBot。
- 如果实施时 AstrBot 已提供官方稳定导入格式，本里程碑应改为实现官方导入 JSON 生成和预览。

### M49：实现 AstrBot 复制内容预览

交付：

- 预览弹窗能展示 AstrBot 手动复制内容。

验收：

- 清楚标注这是“复制到 AstrBot”的辅助视图。
- 系统提示词、自定义报错回复信息和预设对话分区展示。
- 不展示工具 / MCP 工具和 Skills。

### M50：实现 AstrBot 复制清单导出

交付：

- 当前角色卡可导出 AstrBot 复制清单，例如 Markdown 文档。

验收：

- 导出文件命名和覆盖策略明确。
- 导出内容来自 CharaPicker JSON。
- 导出内容用于人工复制，不声明为 AstrBot 可导入 JSON。

### M51：实现编译后可选生成 AstrBot 复制清单

交付：

- 编译或重编译时，用户可选择同时生成 AstrBot 复制清单。

验收：

- 即使复制清单生成失败，CharaPicker 主产物仍保留。
- UI 明确展示主编译成功但复制清单生成失败的部分成功状态。

### M52：补齐角色卡页面状态反馈

交付：

- 页面能展示空、草稿、已编译、需重编译、失败、只有预览等状态。

验收：

- 每种状态都有清晰用户反馈。
- 高风险操作有确认或撤销策略。

### M53：更新架构文档

交付：

- 更新 `core/ARCHITECTURE.md`、`gui/ARCHITECTURE.md`、`projects/ARCHITECTURE.md` 中过期职责。

验收：

- 文档不再说项目页收集目标角色。
- 文档说明角色卡页面、CharaPicker JSON 和 `character_cards/`。
- 文档说明本计划新增的角色卡核心模块、GUI 组件和 worker 边界。
- 文档不把实际实现细节写错。

### M54：更新用户入口文档

交付：

- 更新根 README、`docs/README.md` 和相关用户说明。

验收：

- 用户文档能解释主页提取与角色卡编译的分离。
- 用户文档能解释角色卡页面、预览、编译、导入和导出。
- 不把尚未完成的能力写成已完成。

### M55：更新 TODO 状态

交付：

- 根据实际完成情况更新 `docs/TODO.zh_CN.md` 第 3、4 项。

验收：

- 若只完成部分能力，TODO 中保留剩余项。
- 不提前标记整体完成。

## 9. 验收后收尾工作

收尾工作不属于开发里程碑。它只能在 M01-M55 全部完成、用户完成检查确认、所有已知 bug 修正完成、必要 UI 布局调整完成之后执行。若用户验收阶段提出新的 bug、布局问题或功能缺口，应回到对应里程碑或提交分组修复；不得把修 bug、UI 调整或文档同步混入收尾。

收尾完成并由用户确认后，下一步就是分支合并；收尾之后不再继续追加开发步骤。

### C01：最终整体自审查与验证

交付：

- 在所有用户验收修正完成后，执行一次最终整体自审查。
- 运行可用验证命令，至少覆盖 `compileall`、可用时的 Ruff、核心 JSON/导出格式轻量验证和应用手动启动检查。

验收：

- 没有明显冗余代码、死代码、临时调试输出或架构越界。
- 分页责任、角色卡母本、导出派生产物和预览隔离仍然清晰。
- 无法运行的验证有明确原因和残余风险说明。

### C02：清理开发桥接与临时残留

交付：

- 清理开发过程中为方便联调、迁移或临时验证而加入的桥接程序、兼容转接层、调试入口、临时 feature flag、临时日志输出和未被正式架构接纳的辅助函数。
- 删除或折叠已经没有正式调用方的旧输出页转接、临时命名别名、重复渲染路径和重复格式化逻辑；若某个兼容层仍承担旧项目数据迁移责任，必须保留并写清楚保留原因，不把用户数据兼容误删。
- 清理开发过程中产生的临时测试项目、预览卡残留、手工导出样例、日志、缓存、截图和未纳入文档的实验文件，确保不会被提交或混入发布包。
- 删除项目内裁剪前原图副本，只保留裁剪后的 `cover.png` 或等价正式封面文件；这是开发残留清理的一部分，不单独作为开发里程碑。
- 清理未使用的 import、死代码、重复常量、过时 TODO、临时 print/debug 语句、无调用方的 UI 小部件、未使用 i18n key、未使用颜色常量和未引用资源。

验收：

- 清理不删除 `cover.png`。
- 清理只在用户确认功能可用后的明确收尾动作中执行。
- 清理后角色卡仍能正常显示封面。
- 项目目录中不再同时保留同一封面的裁剪前副本和裁剪后图片。
- 正式保留的兼容层都有明确用途；临时桥接、实验入口和重复路径已移除或合并。
- 仓库状态中没有误加入的 `projects/` 用户数据、预览草稿、导出产物、日志、缓存、截图或本地实验文件。
- 若清理发现会影响用户可见行为的问题，停止收尾并回到对应开发里程碑或验收修正阶段处理。

### C03：升级合并版本号到 v0.3.0-alpha

交付：

- 按发布规范将本次功能阶段版本升级为 `v0.3.0-alpha`；这是分支合并前的收尾动作。
- 同步更新构建元数据、项目元数据、用户可见版本文案和多语言文档中的当前版本号。实现时至少核对 `build.bat`、`pyproject.toml`、`scripts/build_meta.py` 默认版本、`README.md`、`docs/README.*.md`、`i18n/*` 的 about 版本文案，以及仍在硬编码版本号的 User-Agent 常量。
- 若发布规范文档中的示例命令被用作当前推荐命令，同步改为 `v0.3.0-alpha`；若只是历史示例，保持示例性质但避免让用户误读为当前版本。
- 版本升级提交建议使用 `chore: prepare v0.3.0-alpha release`。

验收：

- 应用关于页、README、构建脚本和包元数据展示的版本一致。
- `build.bat --tag=v0.3.0-alpha` 或等价构建元数据解析能得到 `version=0.3.0`、`stage=alpha`。
- 不再残留会让用户误以为当前版本是 `v0.2.0-alpha.1` 的当前版本文案。
- 是否创建 Git tag 由最终发布流程决定；收尾计划只要求合并前代码与文档版本号一致。

### C04：最终仓库状态与发布包预检查

交付：

- 在清理和版本升级后重新运行最终验证，确认清理没有破坏角色卡页面、导出格式、预览弹窗、图片裁剪和旧项目打开流程。
- 检查发布包排除项，确保 `projects/`、`log/`、缓存、临时导出、预览草稿和原图中间副本不会进入发布包。
- 复核 `git status`、关键 `rg` 检索和构建元数据，确认没有残留临时代码、未处理冲突标记、意外大文件或本地私有数据。

验收：

- 工作区只包含计划内的收尾提交内容。
- 版本、文档、i18n、构建元数据和发布排除项一致。
- 没有把 bug 修复、UI 调整或新增功能混进收尾；若发现必须修改功能行为，回到验收修正阶段。

### C05：分支合并准备

交付：

- 确认收尾完成后工作区干净。
- 整理分支合并前说明。

验收：

- 用户确认收尾结果后即可进入分支合并。
- 合并前说明明确本分支目标版本为 `v0.3.0-alpha`。

## 10. 提交分组

细里程碑用于降低实现出错概率；提交不按单个里程碑逐个提交。实际开发时按下列阶段提交，默认 10 次开发提交。若某阶段实现中发现风险过大，可以在用户确认后再拆分一次，但不要把无关阶段合并。

每个提交分组提交前，都必须完成第 7 节的局部自审查；最后一个开发提交完成后、进入用户验收前，必须完成第 7 节的整体自审查。自审查修复应优先并入对应功能提交，不把明显冗余、死代码、文档同步或架构越界留到收尾。验收后收尾工作按第 9 节执行，不作为开发里程碑提交分组。

### Commit 1：主页职责收敛

覆盖里程碑：

- M01-M07

提交主题：

- 从主页移除目标角色入口。
- 保留旧配置兼容。
- 取消预览完成后自动生成正式角色卡。

建议提交信息：

- `refactor: separate extraction page from character targets`

提交前检查：

- 预览和正式提取入口仍能启动。
- 旧项目配置仍能打开。

### Commit 2：角色卡数据边界

覆盖里程碑：

- M08-M14

提交主题：

- 建立正式角色卡和预览草稿角色卡的路径边界。
- 定义 CharaPicker 卡模型、状态和图片目录规则。

建议提交信息：

- `feat: add character card storage model`

提交前检查：

- 正式角色卡扫描不读取预览草稿。
- 角色卡读写不影响现有 `seasons/` 知识库。

### Commit 3：角色卡页面基础与海报墙

覆盖里程碑：

- M15-M20A

提交主题：

- 将输出导航改为角色卡页面。
- 建立海报墙、搜索、选择、新建和删除角色卡入口。

建议提交信息：

- `feat: add character card gallery page`

提交前检查：

- 无项目、无角色卡、有角色卡三种状态都可显示。
- 角色卡选择状态稳定。
- 删除正式角色卡必须二次确认，不清理已导出文件。

### Commit 4：角色卡元数据与封面裁剪

覆盖里程碑：

- M21-M28

提交主题：

- 支持角色名、别名、备注编辑。
- 支持图片选择、复制、9:16 裁剪、cover 保存、替换和清除。
- 完成操作按钮启用规则。

建议提交信息：

- `feat: edit character card metadata and cover`

提交前检查：

- 别名不参与编译匹配。
- 裁剪后重新打开项目仍能显示 cover。

### Commit 5：预览弹窗与渲染视图

覆盖里程碑：

- M29-M31

提交主题：

- 建立预览弹窗。
- 实现人类友好 JSON 预览、Markdown 渲染预览和 CharaPicker HTML 展示预览。

建议提交信息：

- `feat: add character card preview dialog`

提交前检查：

- JSON 默认不是原始花括号文本。
- Markdown 预览是渲染结果。
- HTML 预览由 JSON 模板生成，不调用 LLM，不拉外部资源。

### Commit 6：正式编译为 CharaPicker JSON

覆盖里程碑：

- M32-M39

提交主题：

- 定义编译目标。
- 检测正式知识库。
- 后台编译 CharaPicker JSON。
- 写入卡内阶段状态、警告、stale 和重编译流程。

建议提交信息：

- `feat: compile character cards from knowledge base`

提交前检查：

- 编译不读取原始素材。
- 没有正式知识库时不伪造结果。
- 重编译失败不误删上一次可用结果。

### Commit 7：预览草稿角色卡

覆盖里程碑：

- M40-M41

提交主题：

- 角色卡页触发角色卡预览时生成项目级唯一固定 ID 的预览草稿角色卡。
- 预览完成弹出 CharaPicker HTML 展示结果，并保留 Markdown/JSON 切换。

建议提交信息：

- `feat: generate isolated preview character card`

提交前检查：

- 预览草稿不进入海报墙。
- 每次预览覆盖同一个预览草稿。
- 主页素材预览提取不会自动触发预览草稿生成。

### Commit 8：CharaPicker 导入与 Markdown/HTML/JSON/Character Card V2 导出

覆盖里程碑：

- M42-M46

提交主题：

- 导入 CharaPicker JSON。
- 从 CharaPicker JSON 渲染 Markdown 和 HTML。
- 导出 Markdown、HTML、CharaPicker JSON 和 Character Card V2 JSON。

建议提交信息：

- `feat: import and export charapicker cards`

提交前检查：

- 导出的 CharaPicker JSON 可再次导入。
- Markdown 导出不调用 LLM。
- HTML 导出不调用 LLM，不依赖外部网络资源，不引入 QWebEngine 或新依赖。
- Character Card V2 导出不调用 LLM，不写入 PNG metadata。

### Commit 9：AstrBot 手动复制辅助

覆盖里程碑：

- M47-M52

提交主题：

- 补充 AstrBot 手动复制字段说明。
- 实现 AstrBot 手动复制视图、预览、复制清单导出和编译后可选生成复制清单。
- 补齐角色卡页面状态反馈。

建议提交信息：

- `feat: add astrbot persona copy helper`

提交前检查：

- AstrBot 复制内容基于 CharaPicker JSON。
- 不声称生成 AstrBot 可导入 JSON。
- 不生成工具 / MCP 工具和 Skills 字段。
- 复制清单生成失败不破坏 CharaPicker 主产物。
- 执行本提交前必须重新检查 AstrBot 官方导入/导出人格功能是否已合并；若已合并，先更新本提交范围为官方格式导出。

### Commit 10：开发文档同步与 TODO

覆盖里程碑：

- M53-M55

提交主题：

- 更新架构文档、用户入口文档和 TODO 状态。

建议提交信息：

- `docs: update character card workflow documentation`

提交前检查：

- 文档同步属于开发环节，必须在用户验收前完成。
- 文档不把未完成能力写成已完成。
- TODO 状态与实际完成范围一致。
- 完成整体代码自审查，确认分页责任、角色卡母本、导出派生产物和预览隔离没有互相污染。
