# AstrBot 官方人格 JSON 导出适配计划

> 本文档是执行计划，不代表实现状态。实施前最后复核日期：2026-09-04。

## 1. 目的与范围

AstrBot 官方 PR [#4532](https://github.com/AstrBotDevs/AstrBot/pull/4532) 已于 2026-07-13 合并，WebUI 现已支持单个人格 JSON 的导入和导出。CharaPicker 当前仍只生成 AstrBot 手动复制清单，本计划将其升级为可被 AstrBot 官方 WebUI 直接导入的人格 JSON，同时保留手动复制助手以承载官方导入格式没有覆盖的字段。

范围包括：

- 从 CharaPicker JSON 母本生成 AstrBot 官方人格 JSON。
- 新增独立导出目标和稳定文件名。
- 在角色卡预览、批量导出和编译后可选导出中接入官方 JSON。
- 保留现有 AstrBot 手动复制弹窗与复制清单。
- 同步四语 i18n、README、稳定工作流说明和架构说明。
- 增加纯映射、导出原子性和目标集合回归测试。

## 2. 非目标

- 不把 Character Card V2 JSON 冒充为 AstrBot 人格文件。
- 不修改 CharaPicker JSON 母本、角色卡知识库结构或编译证据规则。
- 不调用 AstrBot API，也不自动写入 AstrBot 数据目录。
- 不导出或推断 AstrBot 工具、MCP 工具、Skills、文件夹等本地运行配置。
- 不删除现有 AstrBot 手动复制功能。
- 不新增依赖。

## 3. 已确认决策

- AstrBot 官方最终导入契约以合并后的 `dashboard/src/views/persona/PersonaManager.vue` 和 `PersonaCard.vue` 为准，不采用旧计划记录的 PR 早期 `version/persona[]` 草案。
- 官方人格 JSON 只生成顶层 `persona_id`、`system_prompt`、`begin_dialogs`。
- `persona_id` 优先使用角色显示名，其次使用角色名，最后回退 `card_id`；截断到 AstrBot Persona 数据模型允许的 255 字符以内。
- `system_prompt` 复用现有 AstrBot 映射语义，包括 persona prompt 回退和用户额外编译要求。
- `begin_dialogs` 是 user/assistant 交替排列的扁平字符串数组，只输出完整对话对；不完整对话跳过并产生 warning。
- 当没有可用预设对话但存在 first message 时，沿用现有默认问候回退，保证输出偶数长度的对话列表。
- `custom_error_reply` 不写入官方 JSON，因为 AstrBot 当前官方导入器会忽略该字段；手动复制助手继续提供它。
- 新导出文件名固定为 `{card_id}.astrbot-persona.json`；现有 `{card_id}.astrbot-copy.md` 保持不变。
- 批量导出同时包含官方 JSON 和手动复制清单；“编译后同时生成 AstrBot”选项改为生成官方 JSON，手动复制仍由独立助手提供。

## 4. 当前状态与目标状态

当前：

- `core.character_card_formats` 只生成 AstrBot 复制分区和 Markdown。
- `CharacterCardExportTarget` 只有 `ASTRBOT_COPY`。
- 批量导出写入 `.astrbot-copy.md`，编译后可选导出也写入复制清单。
- 预览弹窗的 AstrBot 页签展示复制 Markdown。

目标：

- core 提供稳定、可测试的 AstrBot 官方 JSON 映射。
- exporter 原子写入 `.astrbot-persona.json`。
- 预览弹窗展示并可复制官方 JSON。
- 批量导出同时保留官方 JSON 和复制清单。
- 编译后 AstrBot 选项生成可直接导入文件。

## 5. 外部格式映射

| AstrBot 字段 | CharaPicker 来源 | 规则 |
| --- | --- | --- |
| `persona_id` | `identity.display_name` / `identity.character_name` / `card_id` | 去除首尾空白，按优先级回退，最多 255 字符 |
| `system_prompt` | `prompt_surfaces.system_prompt` / `persona_prompt` / profile 回退 | 沿用现有 AstrBot system prompt 构造，并附加未包含的 compile requirements |
| `begin_dialogs` | `dialogue.preset_dialogues` / `example_dialogues` | 每组取第一条 user 和第一条 assistant，按 user、assistant 顺序展平；缺一侧则跳过并 warning |

官方导入行为说明：

- 只接受 JSON 文件。
- 缺少 `system_prompt` 时拒绝导入。
- 缺少 `persona_id` 时使用 `imported_persona`；CharaPicker 始终显式生成。
- 重复 ID 由 AstrBot 导入器自动重命名。
- 工具和 Skills 不随人格文件导入，AstrBot 导入后按其当前规则使用默认配置并提示用户手动调整。

## 6. 模块边界

- `core/models.py`：只新增导出目标枚举，不引入 AstrBot 运行时模型。
- `core/character_card_formats.py`：承担全部字段映射、对话规整和 warning 生成。
- `core/character_card_exporter.py`：只负责 JSON 序列化、稳定路径和原子发布。
- `gui/widgets/character_card_preview_dialog.py`：只展示 core 生成的 JSON，不自行映射字段。
- `gui/widgets/astrbot_copy_dialog.py`：继续承担官方 JSON 未覆盖字段的手动复制入口。
- `gui/pages/character_card_page.py`：只选择导出目标和展示结果，不拼接输出路径或 JSON。

## 7. 里程碑

### M01：官方格式纯映射与导出目标

交付：

- 新增 `ASTRBOT_PERSONA_JSON` 导出目标。
- 新增 AstrBot 官方人格 payload 纯函数。
- 提取并复用 system prompt、对话对映射 helper，避免 JSON 与手动清单语义分叉。
- 新增 `.astrbot-persona.json` 原子导出函数并接入通用 exporter。

验收：

- payload 只包含三个官方字段。
- `begin_dialogs` 长度为偶数且顺序正确。
- 不完整对话不会产生错位角色。
- JSON 使用 UTF-8、保留非 ASCII 字符并带稳定缩进。

边界：

- 不修改角色卡母本。
- 不写入工具、Skills 或 custom error 字段。

### M02：GUI 工作流接入

交付：

- 角色卡预览的 AstrBot 页签展示官方 JSON。
- 批量导出加入官方 JSON，同时保留手动复制 Markdown。
- 编译后 AstrBot 选项改为生成官方 JSON。
- 手动复制助手的说明明确其补充用途。

验收：

- 用户能从预览页复制与落盘文件一致的 JSON。
- 批量导出结果包含两个不同的 AstrBot 派生产物。
- 编译后选项不再生成被误认为可导入文件的复制清单。

边界：

- GUI 不构造 payload。
- 不新增耗时任务或网络调用。

### M03：文案、文档与回归

交付：

- 四个 i18n JSON 同步更新 AstrBot 导出和复制助手文案。
- 四语 README、稳定提取工作流、根/core/gui 架构说明同步当前能力。
- 新增映射和导出测试，运行 i18n、Ruff 与统一离线回归。
- 完成整体代码自审查；发现问题时修复并从验证、自审查步骤重新开始。

验收：

- i18n key 集合一致且无重复 key。
- 相关单测、Ruff 和统一离线回归通过。
- 文档不再把 AstrBot 能力只描述为手动复制清单。

## 8. 验证与自审查

实现后依次执行：

1. `uv run --locked python -m unittest tests.test_character_card_exporter`
2. `uv run --locked python scripts/validate_i18n_keys.py`
3. `uv run --locked ruff check .`
4. `uv run --locked python scripts/validate_multi_material_regression.py`

整体自审查必须检查：

- 映射是否严格符合 AstrBot 合并后的官方实现。
- JSON 和手动复制是否复用同一 system prompt 与对话提取规则。
- 导出目标、文件名、GUI 标签和文档命名是否一致。
- warning 是否会导致成功导出被错误判定为失败。
- 是否存在 UI 内字段映射、重复逻辑、死代码或旧误导文案。
- 是否保持原子写入、用户数据安全和 CharaPicker JSON 母本不变。
- 是否遗漏四语 i18n 和多语言 README/工作流说明。

若任一检查发现问题，修复后重新运行全部四项验证，并重新进行整体自审查；只有全部通过才允许提交、开 PR 和合并。

## 9. 提交分组

### Commit 1：官方格式映射与导出

- 覆盖 M01 和对应测试。
- 建议提交信息：`feat: add astrbot persona json export`
- 提交前运行目标单测和 Ruff。

### Commit 2：GUI 与文档接入

- 覆盖 M02-M03、四语文案、文档和计划完成记录。
- 建议提交信息：`docs: document astrbot persona export workflow`；如果 GUI 变更占主导，则使用 `feat: expose astrbot persona export in ui`。
- 提交前运行全部验证与整体自审查。

## 10. 合并流程

- 在 `codex/astrbot-persona-json` 分支完成实现和自审查。
- 推送分支并创建 PR，PR 正文写明官方格式依据、映射边界、验证结果和保留的手动复制能力。
- 检查 PR diff 和 CI；发现问题则继续在同一分支修复，并从全部验证和整体自审查重新开始。
- 所有检查通过后合并 PR。

## 11. 完成后收尾

- 将本计划移入 `docs/archive/` 并加 `.completed` 标识，记录完成日期、验证结果和 PR。
- 更新 `docs/README.md`、`docs/ARCHITECTURE.md` 与 `docs/archive/README.md` 的计划入口。
- 若没有独立残项，不向 `docs/plans/TODO.zh_CN.md` 增加长期待办。
- 不修改 `AGENTS.md`：本次变化属于已有角色卡外部格式职责内的功能演进，没有产生新的长期开发约束。
