# 角色卡质量后续执行计划（zh_CN）

> 本文是 TODO P1 第 3、4 项的待执行专项计划，不代表已经实现。实施前必须重新核对当前代码和知识库样例。

最近整理日期：2026-06-05。

阶段：待执行专项计划。

可用性：可作为后续开发入口。实施前需复核 `core/character_card_compiler.py`、`core/compiler.py`、`core/models.py`、`core/knowledge_base.py`、`res/default_prompts.json`、`gui/workers/character_card_workers.py`、`gui/pages/character_card_page.py`、`docs/reference/extraction-workflow.zh_CN.md` 和当前正式知识库样例。

## 1. 范围

本计划覆盖当前 TODO P1 的两项角色卡质量后续：

- 角色卡编译上下文分层：在直接证据之外，拆出提及证据、因果上下文和季级背景，避免角色未出现但与其行动动机相关的 episode 被完全丢掉。
- 角色卡冲突消解与质量评估强化：保留冲突证据，给出质量警告和 `needs_review` 判断，让角色卡输出更可解释。

本计划只处理正式角色卡编译链路。预览卡可以复用一部分 helper，但不得把预览产物作为正式角色卡编译事实来源。

## 2. 非目标

- 不回退为重新分析原始视频、字幕、图片或文本素材。
- 不恢复 `ProjectConfig.target_characters` 作为新编译入口。
- 不改变角色卡母本仍以 `knowledge_base/character_cards/{card_id}/card.json` 为唯一事实来源的规则。
- 不在本计划中重做素材提取、快速提取、洁净提取或完整提取主流程。
- 不把外部导出格式作为事实来源；Markdown、HTML、Character Card V2 和 AstrBot 清单仍是派生产物。
- 不引入新的模型后端或绕过 `utils.ai_model_middleware`。
- 不在第一版增加用户可配置的质量阈值界面，除非后续验收明确要求。

## 3. 执行前事实核对

开始实现前，执行者必须先核对以下事实是否仍成立；如代码已变化，应先更新本计划或在实现说明中标注偏差：

- `compile_card_from_knowledge_base()` 从正式 `episode_content.json` 收集知识库内容，不读取预览产物。
- 角色卡本地阶段仍通过 `compile_character_state_by_season_episode()` 生成 timeline。
- `_episode_targets_character()` 对 `targets` 缺失或为空的 episode 返回可参与匹配，避免历史数据缺字段时直接丢上下文。
- 找不到 timeline 时，正式编译仍失败并提示 `character was not found in the formal knowledge base`。
- `_build_ai_knowledge_summary()` 仍向 `character_card_compile` prompt 传入扁平 `episodes` 摘要，而不是分层证据包。
- `CharacterCardEvidence` 仍只有 `evidence_count`、`refs`、`warnings`、`conflicts`；`CharacterCardQuality` 仍只有 `warnings`、`needs_review`、`last_error`。
- 角色卡编译失败时，GUI 仍会将卡片标记为 `FAILED`，设置 `quality.needs_review = True` 并保存 `quality.last_error`。
- `character_card_compile` 和 `character_alias_resolve` prompt 仍维护在 `res/default_prompts.json`。

## 4. 当前默认取舍

以下取舍作为第一版默认方案。若用户或维护者后续明确推翻，应同步更新本节、里程碑和验收标准：

- 新增证据分层与质量细节第一版写入 `CharacterCard.extensions["charapicker"]`，不立即提升 `CharacterCard.schema_version`。
- `needs_review` 第一版使用确定性规则设置，不做 UI 可配置阈值。
- 角色完全没有 direct 证据时，正式角色卡编译继续失败；mention 和 causal 只用于补充已有角色证据，不生成“未直接出场资料卡”。
- 冲突不默认等于错误。可解释为伪装、误解、黑化、成长、关系转折或时间推进的信息，应作为动态变化候选保留。
- prompt 修改只维护 `res/default_prompts.json` 和用户 prompt override 机制，不把长 prompt 硬编码进业务代码。

## 5. 当前状态与缺口

当前正式角色卡编译已经具备基础链路：

- `core.character_card_compiler.compile_card_from_knowledge_base()` 从正式知识库收集 episode 内容。
- 本地阶段生成 `CharacterState timeline`，并把最终状态写入角色卡草稿。
- 直接匹配失败时，会用 AI 从 `episode_content.targets` 候选中解析别名；AI 返回的别名必须存在于知识库候选中。
- 找不到直接证据时，正式编译会失败，避免把没有证据的角色硬编出来。
- `conflicts` 会进入 `card.evidence.conflicts` 和 `card.quality.warnings`。

当前主要缺口：

- episode 只按“是否可参与角色状态编译”粗筛，尚未分成 direct、mention、causal、season 四层。
- AI 复核输入是扁平 `knowledge_summary.episodes`，无法稳定表达证据优先级。
- `targets` 为空的兼容策略能避免丢历史数据，但也需要新的分类规则防止无关 episode 混入角色证据。
- 冲突缺少结构化分组、严重度、来源、可能解释和是否触发人工复核的规则。
- `needs_review` 仍缺少清晰、可追踪的原因列表。
- UI 最小闭环只展示成功或失败，不足以解释“编译成功但需要复核”的原因。

## 6. 目标状态

角色卡编译应形成分层上下文包，再交给 AI 复核：

- `direct_evidence_episodes`：角色直接出现、被明确点名，或通过已解析别名命中的 episode。
- `mention_evidence_episodes`：角色未直接参与当前事件，但被其他角色、旁白、字幕或知识库条目明确提及的 episode。
- `causal_context_episodes`：角色没有出现或只被弱提及，但 episode 解释其后续行动动机、关系变化、误解来源、任务约束或冲突背景。
- `season_context`：季级长摘要、季级冲突和角色阶段状态，用作低优先级背景，不覆盖当前 episode 证据。

AI 复核必须知道各层证据优先级：

1. 直接证据优先。
2. 提及证据可补充别人如何理解角色，但不能替代角色实际行动。
3. 因果上下文用于解释动机和关系链，不能凭空生成角色行为。
4. 季级背景只用于连续性，不得覆盖当前正式知识库的新事实。

质量评估应给出可追踪结果：

- 证据不足、冲突未解决、别名低置信度、跳过片段、过度依赖摘要、AI 复核 JSON 修复或解析降级等情况要形成 warnings。
- `needs_review = True` 必须能追溯到 `needs_review_reasons`。
- 冲突应保留为带来源的候选，不应被静默覆盖或只合并成不可追踪字符串。

## 7. 数据与持久化

第一版新增结构写入 `CharacterCard.extensions["charapicker"]`：

```json
{
  "compile_evidence_layers": {
    "direct_evidence_episodes": [],
    "mention_evidence_episodes": [],
    "causal_context_episodes": [],
    "season_context": []
  },
  "quality_checks": {
    "needs_review_reasons": [],
    "conflict_groups": [],
    "alias_resolution": {}
  }
}
```

建议 episode 条目至少包含：

```json
{
  "season_id": "season_001",
  "episode_id": "episode_001",
  "layer": "direct",
  "match_terms": [],
  "classification_reason": "",
  "source_fields": [],
  "evidence_summary": "",
  "refs": [],
  "warnings": []
}
```

建议 `conflict_groups` 至少包含：

```json
{
  "description": "",
  "severity": "info|review|blocking",
  "source_episodes": [],
  "candidate_explanations": [],
  "needs_review": false
}
```

只有当 UI、导出格式或跨版本迁移都需要稳定读取这些字段时，才考虑提升 `CharacterCard.schema_version` 并迁移到正式模型字段。

## 8. 模块边界

- `core/compiler.py`：负责本地角色状态聚合和可复用的 episode 角色相关性辅助；不拼 UI 文案，不写角色卡。
- `core/character_card_compiler.py`：负责构建证据分层包、调用 AI 复核、应用质量规则、写入角色卡扩展字段。
- `core/models.py`：第一版不强制扩展正式模型字段；只有字段成为稳定协议时才新增 Pydantic 模型。
- `core/knowledge_base.py`：继续作为知识库路径和 JSON 读写入口；页面层不得绕过它拼接知识库路径。
- `res/default_prompts.json`：维护 `character_card_compile` prompt 中的证据层级说明和输出约束。
- `gui/workers/character_card_workers.py`：继续只桥接 Qt Signal 与 core 调用，不写业务逻辑。
- `gui/pages/character_card_page.py` 与相关组件：只展示结果、warnings、复核状态和冲突摘要，不直接扫描知识库路径。
- `i18n/*.json`：任何新增 UI 文案必须四语种同步。

## 9. 里程碑

### M00：实施前复核

交付：

- 按第 3 节复核当前代码、prompt、UI 和知识库样例。
- 记录是否存在与本计划冲突的代码事实。
- 确认第一版仍采用第 4 节默认取舍。

验收：

- 实现者能指出当前扁平 AI 输入、失败保护和质量字段的具体位置。
- 若有冲突，已在本计划或实现说明中写清楚采用依据。

边界：

- 本阶段不改实现代码，只做事实确认和必要文档校正。

### M01：定义证据分层规则

交付：

- 明确 direct、mention、causal、season 四层的分类条件和优先级。
- 设计本地分类 helper 的输入输出，建议先形成私有 helper，不急于暴露公共 API。
- 写清 `targets` 为空、别名未解析、episode 缺字段、跳过片段和 refs 缺失时的处理方式。

验收：

- 四层证据能覆盖“角色出现、被提到、因果相关、完全无关”四类 episode。
- `targets` 缺失不会直接丢掉潜在上下文。
- 完全无关 episode 不会被当成角色证据。

边界：

- 不修改素材提取输出结构。
- 不把 causal episode 计入 direct evidence 数量。

### M02：构建本地证据分层包

交付：

- 在 core 层收集 episode 时生成 `direct_evidence_episodes`、`mention_evidence_episodes`、`causal_context_episodes` 和 `season_context`。
- 每个条目保留 `season_id`、`episode_id`、命中理由、来源字段、证据摘要、refs 和 warnings。
- 将分层包写入 `card.extensions["charapicker"]["compile_evidence_layers"]`。

验收：

- 角色直接出现的 episode 进入 direct。
- 只被提到的 episode 进入 mention。
- 未出现但解释后续行动动机的 episode 进入 causal。
- 完全无关 episode 不进入前三层，必要时只通过 season 背景间接存在。

边界：

- 不改变正式知识库目录结构。
- 不改变 `CharacterCard.schema_version`。

### M03：调整 AI 复核输入与 prompt

交付：

- `_build_ai_knowledge_summary()` 或替代函数向 `character_card_compile` prompt 传入分层证据。
- prompt 明确四层证据的使用边界，避免把因果背景写成角色亲历事实。
- `current_card`、`extra_requirements` 和编译目标相关变量保持现有机制。

验收：

- AI 请求变量中能看到分层结构。
- 无 direct 证据时仍保持当前失败保护。
- 有 direct 证据时，mention 和 causal 能帮助补全动机、关系和误解来源。

边界：

- 不绕过 `utils.ai_model_middleware`。
- 不在业务代码中硬编码长 prompt。

### M04：冲突分组与质量规则

交付：

- 将冲突拆成来源明确的 `conflict_groups`，至少记录描述、涉及 episode、可能解释、严重度和是否需要复核。
- 形成 `needs_review_reasons`。
- 由确定性规则设置 `card.quality.needs_review`。

验收：

- 证据不足、重大冲突、别名低置信度、跳过片段、AI JSON 修复或解析降级均能触发可解释 warning。
- 一般的角色成长或关系转折不会被错误当成 bug，而是被记录为动态变化候选。
- `card.quality.warnings` 与 `extensions["charapicker"]["quality_checks"]` 不互相矛盾。

边界：

- 第一版不做 UI 可配置阈值。
- 不删除原有 `card.evidence.conflicts`，只增强其可追踪来源。

### M05：编译状态与 stale 清理

交付：

- 成功重新编译时，清理上一轮 stale、失败和质量降级相关 warning。
- 编译失败时，保留现有失败写回行为，并补充可追踪失败原因。
- 明确 AI 解析修复或降级时如何写入 warning 与 `needs_review_reasons`。

验收：

- stale 卡重新编译成功后，不再残留上一轮失败原因。
- AI 复核 JSON 被修复或解析降级时，用户能看到需复核原因。
- `quality.last_error` 只表示最近失败，不被成功编译长期污染。

边界：

- 不隐藏真实失败。
- 不把普通 debug 日志作为洞察流或 UI 质量提示。

### M06：UI 展示最小闭环

交付：

- 角色卡页面能展示 `needs_review`、warnings 和主要冲突摘要。
- UI 文案四语种同步。
- 普通用户看到的是“需复核原因”“证据不足”“冲突摘要”等语义，不直接暴露内部字段名。

验收：

- 编译成功但需复核时，用户能看到复核原因。
- 编译失败、证据不足、别名解析失败和正式知识库缺失的反馈保持清晰。
- 角色卡页面不直接拼接知识库路径。

边界：

- 不做复杂质量审计页面。
- 不在 UI 中展示大段模型请求、响应正文或素材原文。

### M07：回归验证样例

交付：

- 增加最小可重复验证，覆盖直接出现、只被提到、因果相关、无关 episode 的分类。
- 覆盖冲突保留、`needs_review`、stale 卡重新编译后 warning 清理。
- 记录无法自动化的手动验证步骤。

验收：

- 静态检查通过。
- 手动或脚本验证能证明 TODO P1 第 3、4 项不再只停留在文档层。
- 验证样例不依赖用户私有 `projects/` 数据。

边界：

- 不把真实用户项目素材提交为测试样例。
- 不要求一次性建立完整测试框架；最小验证优先。

### M08：文档和 TODO 收尾

交付：

- 更新 `docs/reference/extraction-workflow.*` 中的角色卡编译限制。
- TODO P1 第 3、4 项完成后迁入已完成区，或保留未完成残项。
- 本计划完成后移入 `docs/archive/`，或在顶部改为完成记录。

验收：

- 当前计划不再与代码事实冲突。
- 未完成残项继续留在 TODO，不伪装成已完成。
- 文档说明清楚哪些是已实现行为，哪些只是后续建议。

边界：

- 不把临时任务进度写入 `AGENTS.md`。
- 不把 roadmap 当作当前代码事实。

## 10. 验证与自审

建议验证命令：

```powershell
conda run -n CharaPicker python -m compileall core gui utils
```

如当前环境已安装 Ruff，可补充：

```powershell
conda run -n CharaPicker python -m ruff check core gui utils res
```

自审清单：

- 是否仍通过 `utils.ai_model_middleware` 调用模型。
- 是否没有把预览产物混入正式角色卡编译。
- 是否没有恢复读取 `ProjectConfig.target_characters`。
- 是否保留用户素材、知识库来源和证据 refs 的可追溯性。
- 是否新增 UI 文案并同步四个 `i18n/*.json`。
- 是否避免在日志中输出完整模型请求、响应正文或大段素材内容。
- 是否没有把 causal 或 season 背景写成角色亲历事实。
- 是否清理或保留 stale warning 的规则清楚可解释。

## 11. 提交分组建议

- `feat: classify character card evidence context`：覆盖 M00-M03。
- `feat: add character card quality review signals`：覆盖 M04-M06。
- `test: cover character card evidence layering`：覆盖 M07。
- `docs: refresh character card quality follow-up status`：覆盖 M08。

提交前检查：

- 每组提交只覆盖对应里程碑，不夹带 unrelated UI 或提取流程改动。
- 用户可见文案改动必须和四语种 i18n 同步进入同一提交组。
- prompt 改动必须能在提交说明中解释输入变量和安全边界变化。

## 12. 验收后收尾

只有满足以下条件后，才进入收尾：

- M01-M08 的开发与验证已完成。
- 用户已经试用检查关键路径。
- 已知 bug 已修复。
- 必要 UI 布局调整已完成。

收尾内容可以包括：

- 删除临时 helper、调试入口或手动验证残留文件。
- 清理重复兼容路径或过期 warning reason。
- 更新 TODO、reference 文档和归档状态。
- 按发布节奏补充 CHANGELOG 或版本准备材料。

如果收尾时发现行为 bug，应回到对应里程碑修复，不把 bug 修复塞进收尾说明。

## 13. 待确认问题

- causal 分类第一版是否完全使用本地启发式，还是允许在 direct 已存在后增加一次轻量 AI 辅助分类。当前建议先本地启发式，避免增加额外模型成本。
- UI 是否只展示汇总 warning，还是允许用户展开查看 episode 级证据层。当前建议第一版只展示汇总，episode 级证据先保存在 `extensions`。
