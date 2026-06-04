# 角色卡质量后续临时计划（zh_CN）

> 本文是 TODO P1 第 3、4 项的临时执行计划，不代表已经实现。实施前必须重新核对当前代码。

最近整理日期：2026-06-04。

阶段：待执行临时计划。

可用性：可作为后续开发入口；实施前需复核 `core/character_card_compiler.py`、`core/compiler.py`、`core/models.py`、`res/default_prompts.json`、`gui/workers/character_card_workers.py`、`docs/reference/extraction-workflow.zh_CN.md` 和当前知识库样例。

## 1. 范围

本计划覆盖当前 TODO P1 的两项角色卡质量后续：

- 角色卡编译上下文分层：在直接证据之外，拆出提及证据、因果上下文和季级背景，避免角色未出现但与其行动动机相关的 episode 被丢掉。
- 角色卡冲突消解与质量评估强化：保留冲突证据，给出质量警告和 `needs_review` 判断，让角色卡输出更可解释。

## 2. 非目标

- 不回退为重新分析原始视频、字幕或图片素材。
- 不恢复 `ProjectConfig.target_characters` 作为新编译入口。
- 不改变角色卡母本仍以 `knowledge_base/character_cards/{card_id}/card.json` 为唯一事实来源的规则。
- 不在本计划中重做素材提取、快速提取或洁净提取主流程。
- 不把外部导出格式作为事实来源；Markdown、HTML、Character Card V2 和 AstrBot 清单仍是派生产物。

## 3. 当前状态

当前正式角色卡编译已经具备基础链路：

- `core.character_card_compiler.compile_card_from_knowledge_base()` 从正式 `episode_content.json` 收集知识库内容，不读取预览产物。
- 本地阶段通过 `core.compiler.compile_character_state_by_season_episode()` 生成 `CharacterState timeline`。
- 直接匹配失败时，会用 AI 从 `episode_content.targets` 候选中解析别名；AI 返回的别名必须存在于知识库候选中。
- 找不到直接证据时，编译会失败并提示 `character was not found in the formal knowledge base`。
- `CharacterCardEvidence` 已有 `evidence_count`、`refs`、`warnings`、`conflicts`；`CharacterCardQuality` 已有 `warnings`、`needs_review`、`last_error`。

当前主要缺口：

- `_episode_targets_character()` 仍把 `targets` 为空的 episode 视为可参与匹配，避免历史数据缺字段时丢失上下文；但角色卡编译尚未把相关 episode 分成直接证据、提及证据、因果上下文和季级背景。
- `_build_ai_knowledge_summary()` 目前主要按匹配名从 episode 字段中提取相关条目，角色未出现但解释其后续行动的 episode 只能薄弱地进入摘要。
- `conflicts` 会进入 `card.evidence.conflicts` 和 `card.quality.warnings`，但缺少稳定的严重度、来源、是否阻断和 `needs_review` 规则。

## 4. 目标状态

角色卡编译应形成分层上下文包，再交给 AI 复核：

- `direct_evidence_episodes`：角色直接出现、被明确点名或通过已解析别名命中的 episode。
- `mention_evidence_episodes`：角色未直接参与当前事件，但被其他角色、旁白、字幕或知识库条目明确提及的 episode。
- `causal_context_episodes`：角色没有出现或只被弱提及，但 episode 解释其后续行动动机、关系变化、误解来源、任务约束或冲突背景。
- `season_context`：季级长摘要和角色阶段状态，用作低优先级背景，不覆盖当前 episode 证据。

AI 复核应明确知道各层证据的优先级：

1. 直接证据优先。
2. 提及证据可补充别人如何理解角色，但不能替代角色实际行动。
3. 因果上下文用于解释动机和关系链，不能凭空生成角色行为。
4. 季级背景只用于连续性，不得覆盖当前正式知识库的新事实。

质量评估应给出可追踪结果：

- 证据不足、冲突未解决、别名低置信度、跳过片段、过度依赖摘要、AI 复核 JSON 修复等情况要形成 warnings。
- `needs_review = True` 应有明确规则，而不是只由模型自由判断。
- 冲突应保留为角色的动态变化候选，例如伪装、误解、黑化、成长、关系转折或知识库不一致。

## 5. 数据与持久化

第一版优先在 `CharacterCard.extensions["charapicker"]` 中保存新增质量与证据结构，避免立刻提高 `schema_version`：

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

只有当 UI、导出格式或跨版本迁移都需要稳定读取这些字段时，才考虑提升 `CharacterCard.schema_version` 并迁移到正式模型字段。

## 6. 模块边界

- `core/compiler.py`：只负责从知识库 episode 生成本地角色状态或证据分类辅助，不直接拼 UI 文案。
- `core/character_card_compiler.py`：负责构建证据分层包、调用 AI 复核、应用质量规则和写入角色卡。
- `core/models.py`：仅在需要稳定模型字段时扩展；临时结构优先放入 `extensions`。
- `res/default_prompts.json`：维护 AI 复核 prompt，不把 prompt 硬编码进业务代码。
- `gui/workers/character_card_workers.py`：继续只桥接 Qt Signal 与 core 调用，不写业务逻辑。
- `gui/pages/character_cards_page.py` 及相关组件：只展示结果、warnings 和复核状态，不直接扫描知识库路径。
- `i18n/*.json`：任何新增 UI 文案必须四语种同步。

## 7. 里程碑

### M01：定义证据分层规则

交付：

- 明确 direct、mention、causal、season 四层的分类条件和优先级。
- 形成本地分类 helper 的输入输出设计，说明如何处理 `targets` 为空、别名未解析、episode 缺字段和跳过片段 warnings。

验收：

- 计划中的 4 层证据可以覆盖“角色出现、被提到、因果相关、完全无关”四类 episode。
- 不会因为 `targets` 缺失而直接丢掉潜在上下文，也不会把完全无关 episode 当成角色证据。

### M02：构建本地证据分类包

交付：

- 在 core 层收集 episode 时生成 `direct_evidence_episodes`、`mention_evidence_episodes`、`causal_context_episodes` 和 `season_context`。
- 每个条目保留 `season_id`、`episode_id`、命中理由、来源字段、证据摘要和 refs。

验收：

- 角色直接出现的 episode 进入 direct。
- 只被提到的 episode 进入 mention。
- 未出现但解释后续行动动机的 episode 进入 causal。
- 完全无关 episode 不进入前三层，必要时只通过 season 背景间接存在。

### M03：调整 AI 复核输入

交付：

- `_build_ai_knowledge_summary()` 或其替代函数向 `character_card_compile` prompt 传入分层证据。
- prompt 明确四层证据的使用边界，避免把因果背景写成角色亲历事实。

验收：

- AI 请求变量中能看到分层结构。
- 直接证据缺少时仍保持当前失败保护，不硬编不存在的角色。
- 有 direct 证据时，mention 和 causal 能帮助补全动机、关系和误解来源。

### M04：冲突分组与质量规则

交付：

- 将冲突拆成来源明确的 `conflict_groups`，至少记录冲突描述、涉及 episode、可能解释和严重度。
- 形成 `needs_review_reasons`，并由确定性规则设置 `card.quality.needs_review`。

验收：

- 证据不足、重大冲突、别名低置信度、跳过片段、AI JSON 修复或解析降级均能触发可解释 warning。
- 一般的角色成长或关系转折不会被错误当成 bug；应被记录为动态变化候选。

### M05：UI 展示最小闭环

交付：

- 角色卡页面能展示 `needs_review`、warnings 和主要冲突摘要。
- UI 文案四语种同步，避免把内部字段名直接暴露给普通用户。

验收：

- 编译成功但需复核时，用户能看到复核原因。
- 编译失败、证据不足、别名解析失败和正式知识库缺失的反馈保持清晰。

### M06：回归验证样例

交付：

- 增加最小可重复验证，覆盖直接出现、只被提到、因果相关、无关 episode 的分类。
- 覆盖冲突保留、`needs_review`、stale 卡重新编译后 warning 清理。

验收：

- 静态检查通过。
- 手动或脚本验证能证明 P1 的两条 TODO 不再只停留在文档层。

### M07：文档和 TODO 收尾

交付：

- 更新 `docs/reference/extraction-workflow.*` 中的角色卡编译限制。
- TODO P1 第 3、4 项完成后迁入已完成区或归档本计划。

验收：

- 当前计划不再与代码事实冲突。
- 未完成残项继续留在 TODO，不伪装成已完成。

## 8. 提交分组建议

- `feat: classify character card evidence context`：覆盖 M01-M03。
- `feat: add character card quality review signals`：覆盖 M04-M05。
- `test: cover character card evidence layering`：覆盖 M06。
- `docs: refresh character card quality follow-up status`：覆盖 M07。

## 9. 自审清单

- 是否仍通过 `utils.ai_model_middleware` 调用模型。
- 是否没有把预览产物混入正式角色卡编译。
- 是否没有恢复读取 `ProjectConfig.target_characters`。
- 是否保留用户素材、知识库来源和证据 refs 的可追溯性。
- 是否新增 UI 文案并同步四个 `i18n/*.json`。
- 是否避免在日志中输出完整模型请求、响应正文或大段素材内容。

## 10. 待确认问题

- `compile_evidence_layers` 第一版是否只进入 `extensions["charapicker"]`，还是需要直接进入 `CharacterCardEvidence` 正式字段。
- `needs_review` 的严重度阈值是否需要 UI 可配置，还是第一版固定规则即可。
- 角色完全没有 direct 证据但有大量 mention/causal 时，是否仍保持失败，还是允许生成“未直接出场资料卡”。当前建议保持失败，避免硬编角色。
