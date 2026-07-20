# 更多输入格式支持执行计划（zh_CN）

> 本文档是执行计划，不代表实现状态。

最近整理日期：2026-07-20。

计划状态：草案，等待用户确认后进入实现。

适用阶段：在路线 01、路线 02、路线 03 已完成并归档后，补齐真实素材暴露出的输入格式与输入容器缺口。本文档覆盖 EPUB、ZIP/CBZ、7z、PDF 等更多输入格式的受控导入、预处理、来源追踪和验收策略。

执行闸门：实现代码前必须先确认本文档的范围、依赖策略和 PDF/7z 处理方案。未确认前只允许维护计划文档，不落地业务代码。

当前分支：`input-format-support-plan`。

## 1. 目的

CharaPicker 当前已经支持把视频、文本、字幕、音频、静态图片和漫画图片目录映射进 `FormalExtractionRunPlan`，并通过 `video`、`image`、`audio`、`text` 四种顶层媒体类型进入预览、正式提取、知识库聚合和角色卡证据链路。

真实素材验收暴露出的剩余缺口是输入格式：用户手里常见的是 EPUB 小说、漫画 ZIP/CBZ/7z、PDF 设定集或文档，而当前应用要求用户先手工抽取为 TXT 或图片目录。这会破坏 Extract Once 的体验，也会丢失原容器到派生素材的来源追踪。

本计划目标是把“输入容器/复杂文档”变成受控预处理阶段：原容器仍保存在 `raw/`，应用在 `materials/` 生成现有提取链路能消费的 TXT、Markdown、图片目录或其它支持格式，并把原容器、容器内路径、派生文件和后续 evidence 关联起来。

## 2. 范围

本计划覆盖：

- EPUB 小说或轻小说：抽取正文、章节结构、标题、可用插图，派生为文本章节和可选图片素材。
- ZIP/CBZ 漫画包：安全解包图片页，按目录和自然排序形成漫画/图集目录。
- 7z 漫画包或资料包：在确认外部工具或依赖策略后接入，首版不得静默失败或假装支持。
- PDF 文档或设定集：在确认 PDF 解析方案后抽取文本页，必要时后续再扩展图片页或页面截图。
- 受控预处理 manifest：记录原始容器、容器内 entry、派生材料路径、计数、大小、warning 和失败原因。
- GUI 素材整理流程：用户仍通过项目页添加素材并点击“开始整理”，耗时预处理在 worker 中执行，页面只展示进度和结果。
- 离线验证和真实素材验收：覆盖安全边界、格式识别、派生路径、扫描结果、来源 metadata 和统一回归。

## 3. 非目标

- 不新增顶层媒体类型。代码层仍只允许 `video`、`image`、`audio`、`text`。
- 不把 EPUB、PDF、ZIP、7z 作为新的正式提取 handler；它们是输入预处理来源，不直接进入模型请求。
- 不破解 DRM、密码保护、加密 PDF、加密压缩包或受版权保护的访问限制。
- 不在首版实现 OCR、漫画对白识别、PDF 页面视觉理解或复杂版面重建。
- 不在 GUI 层直接解包、解析 PDF/EPUB、拼接 `materials/` 路径或写入知识库。
- 不默认引入新依赖。确需新增依赖或捆绑外部工具时，必须先说明用途、替代方案、影响范围和更新位置，并取得用户确认。
- 不把解包后的临时文件、测试素材或用户原始素材提交到仓库。
- 不联网拉取格式说明、元数据、番剧数据库、书籍数据库或封面资源。

## 4. 已确认决策

- 本阶段先写计划，未确认前不做业务代码实现。
- 新分支为 `input-format-support-plan`。
- 支持更多输入格式时保持四媒体类型边界：`video`、`image`、`audio`、`text`。
- 原容器保存在 `raw/`，预处理产物写入 `materials/`，后续正式提取继续从 `materials/` 扫描。
- 预处理必须保留原容器到派生 TXT/图片目录的来源追踪。
- PDF 和 7z 不使用临时硬编码方案；必须先确认使用外部工具、可选依赖或后置策略。

## 5. 当前状态与目标状态

### 5.1 当前事实

- `utils.media_types` 已集中定义视频、图片、音频、文本、timed text 和漫画压缩包后缀。
- 当前 `SUPPORTED_SOURCE_SUFFIXES` 只允许直接可处理的四媒体文件进入导入链路；`.epub` 为 unknown，`.zip/.cbz/.rar/.7z/.cbr` 当前不支持导入。
- `utils.source_importer` 负责把外部素材复制进 `raw/`，再把 raw 素材链接或物化到 `materials/`。
- `utils.material_processing_middleware` 是项目页触发素材整理的中间层，已把长耗时任务放进 GUI worker。
- `core.material_unit_scanner` 已能扫描 `materials/` 中的 TXT/MD/JSON、SRT/ASS、音频、静态图片和图片目录，并把图片目录识别为 `image_set` / `manga` 候选。
- 统一离线回归入口是 `scripts/validate_multi_material_regression.py`。
- `requirements.txt` 当前没有 PDF、EPUB、7z 或 RAR 专用解析依赖。

### 5.2 目标状态

- 用户可以把 EPUB、ZIP/CBZ、PDF 和经确认的 7z 等素材加入项目素材列表。
- 点击“开始整理”后，应用把可预处理格式安全转换为当前提取链路已支持的 TXT/MD 或图片目录。
- `materials/` 中的派生材料能被现有扫描器识别，不需要新增媒体类型。
- run plan、chunk、episode、season 和角色卡证据能追溯到原始容器与容器内 entry。
- 不支持、加密、过大、疑似解压炸弹、路径穿越、格式损坏或依赖缺失都能给出可解释 warning，不阻断其它可处理素材。
- EPUB/ZIP/CBZ 的基础能力优先落地；PDF/7z 按确认后的依赖或工具策略进入后续里程碑。

## 6. 输入格式分层

| 输入格式 | 首版目标 | 输出到 `materials/` | 依赖策略 | 备注 |
| --- | --- | --- | --- | --- |
| `.epub` | 受控抽取正文和可用图片 | 文本章节、图片目录 | 标准库 `zipfile` + 内部 XHTML/OPF 解析优先 | 不处理 DRM；复杂样式只保留纯文本和基础章节顺序 |
| `.zip` | 按内容识别漫画包或通用资料包 | 图片目录、文本文件或已支持素材目录 | 标准库 `zipfile` | 必须做路径、大小、数量和后缀白名单校验 |
| `.cbz` | 漫画包 | 图片目录 | 标准库 `zipfile` | 作为 ZIP profile 处理 |
| `.7z` | 漫画包或资料包 | 图片目录或支持素材目录 | 待确认：外部 `7z` 工具或新增依赖 | 标准库不支持；无工具时提示依赖缺失 |
| `.rar/.cbr` | 后置或通过 7z 后端处理 | 图片目录 | 待确认 | 不优先于 EPUB/ZIP/PDF |
| `.pdf` | 文本型 PDF 首版抽取 | 按页或章节文本 | 待确认：纯 Python 依赖、外部工具或后置 | 不承诺扫描版 PDF OCR |
| `.html/.xhtml` | 可作为 EPUB 内部解析格式 | 文本章节 | 标准库 HTML 解析辅助 | 是否允许用户直接导入 HTML 可后续确认 |
| `.docx`、`.mobi`、`.azw3` | 不进入首批实现 | 无 | 后续评估 | 避免一次性扩展过宽 |

## 7. 数据与持久化

### 7.1 路径规则

- `raw/` 保存用户选择的原始容器文件，不在导入时破坏原文件。
- `materials/` 保存预处理后的可消费材料。建议使用稳定派生根目录，例如：

```text
materials/
└── derived_inputs/
    └── {safe_stem}_{source_hash}/
        ├── text/
        │   ├── chapter_001.txt
        │   └── chapter_002.txt
        └── images/
            ├── 001.jpg
            └── 002.png
```

- 预处理 manifest 不直接放在会被扫描成文本 unit 的普通材料目录中。建议写入：

```text
cache/
└── material_preprocessing/
    └── {source_hash}.json
```

- 如果确需在 `materials/` 放 sidecar，必须同步让 scanner 忽略 `.charapicker/` 或等价保留目录，避免 manifest 被当成用户素材。

### 7.2 Manifest 最小字段

预处理 manifest 至少包含：

- `schema_version`
- `source_raw_path`
- `source_suffix`
- `source_hash`
- `preprocessor`
- `created_at`
- `output_root`
- `derived_materials`
- `entry_count`
- `input_size_bytes`
- `expanded_size_bytes`
- `warnings`
- `failed_entries`

每个 `derived_materials` entry 至少包含：

- `material_relative_path`
- `source_entry_path`
- `media_type`
- `content_form_hint`
- `page_number` 或 `chapter_index`
- `original_name`
- `size_bytes`
- `fingerprint`

### 7.3 来源追踪接入

- `core.material_unit_scanner` 扫描派生材料时，应能从预处理 manifest 补充 `MaterialRef.metadata`。
- 最小 metadata 包括 `preprocessed_from_raw`、`preprocessor`、`source_entry_path`、`container_format`、`source_hash`。
- 后续 `source_trace.material_refs` 和角色卡 evidence metadata 应继承这些字段的压缩版本。
- 不要求角色卡编译重新打开原 EPUB/PDF/ZIP；它仍只消费正式知识库。

## 8. 安全与失败策略

### 8.1 解包安全

所有容器预处理必须先经过安全检查：

- 禁止绝对路径、盘符路径、`..` 路径穿越和空文件名。
- 忽略或拒绝 symlink、hardlink、设备文件、目录伪装和平台危险路径。
- 限制 entry 总数、单文件大小、解包总大小和压缩比。
- 只允许进入白名单后缀；未知后缀进入 warning，不写入可扫描材料目录。
- 先解到 `cache` 下临时目录，完成校验后再原子移动或复制到 `materials/`。
- 取消任务时清理临时目录，不留下半截材料。

### 8.2 格式失败

- 损坏 EPUB/ZIP/PDF/7z 不阻断其它素材。
- 加密、密码保护、DRM 或依赖缺失返回明确 warning。
- 部分 entry 失败时记录 failed entry 摘要，已成功的派生材料仍可进入扫描。
- 日志只记录文件名、项目内相对路径、计数和脱敏错误摘要，不输出完整正文或大段原始内容。

## 9. UI 与用户工作流

- 项目页“添加素材文件”文件过滤器应包含新增候选格式，但 UI 文案要区分“可直接提取”和“需要整理后提取”。
- 素材列表状态可继续复用现有 `new/processed/stale/rawCleaned`，但 tooltip 或整理结果需要显示预处理 warning。
- “开始整理”继续走 `SourceProcessingWorker`，页面不直接处理文件。
- 处理进度需要覆盖复制、预处理、FFmpeg 处理和链接阶段，避免用户看到长时间无反馈。
- 处理完成 InfoBar 应显示材料数量，并在有 warning 时提示用户查看洞察流、日志或整理结果摘要。
- UI 可见文案必须同步维护 `i18n/zh_CN.json`、`zh_TW.json`、`en_US.json`、`ja_JP.json`。

## 10. 代码结构边界

建议新增或调整的边界：

- `utils.media_types`：增加“可导入但需预处理”的支持档位或 profile，不把它们标成可直接正式提取。
- `utils.source_importer`：允许受控格式进入 `raw/`，并计算 raw 目标。
- `utils.material_preprocessing.py` 或等价模块：承载 EPUB、ZIP/CBZ、PDF、7z 的预处理分派、安全检查、manifest 写入和取消检查。
- `utils.material_processing_middleware`：在 source import 后、materials 链接或 FFmpeg 处理前后串联预处理步骤。
- `utils.source_status`：识别受控容器源的 raw/materials 状态和派生材料状态。
- `core.material_unit_scanner`：读取预处理 manifest，把派生材料的原容器 metadata 写入 unit。
- `gui.pages.project_page`：只调整文件过滤器、进度展示和结果文案，不承载格式解析。
- `scripts/validate_input_format_preprocessing.py`：新增离线验证入口，并由统一回归脚本自动调用。

## 11. 里程碑

### M01：计划确认与当前基线复核

交付：

- 确认本计划范围、首批格式、依赖策略和非目标。
- 运行现有统一离线回归，记录当前基线。

验收：

- `scripts/validate_multi_material_regression.py` 通过。
- 用户确认 PDF/7z 是否进入首轮实现，以及采用外部工具还是新增依赖。

边界：

- 不改业务代码。

### M02：输入格式支持档位与预处理协议

交付：

- 在 `utils.media_types` 中区分直接支持、需预处理、暂不支持。
- 定义预处理结果模型、warning reason、manifest schema 和派生路径规则。

验收：

- 单独验证新增格式不会被误当成 `video/image/audio/text` 正式 unit。
- `.epub/.zip/.cbz/.pdf/.7z` 的支持状态可被 UI/source status 查询。

边界：

- 不新增顶层 `MediaType`。
- 不把 PDF/7z 伪装成已可提取。

### M03：安全预处理基础设施

交付：

- 新增预处理分派模块。
- 建立临时目录、取消检查、路径穿越防护、大小/数量限制、后缀白名单和 manifest 写入。
- 接入 `process_source_request()`。

验收：

- 恶意路径、超限文件、未知后缀、损坏容器均返回结构化 warning。
- 取消任务后不保留半成品材料。

边界：

- GUI 不直接调用预处理内部函数。

### M04：ZIP/CBZ 漫画包支持

交付：

- `.zip/.cbz` 安全解包图片页。
- 生成按自然排序的图片目录。
- 写入原容器 entry 到图片页的来源映射。

验收：

- 图片目录被 `core.material_unit_scanner` 识别为 `image_set` / `manga` 候选。
- unsupported 图片如 GIF/BMP 仍保留当前 unsupported warning，不静默进入正式图片 handler。
- zip bomb、路径穿越和未知 entry 有离线验证。

边界：

- 不跨目录自动合并章节。

### M05：EPUB 小说支持

交付：

- `.epub` 作为 ZIP 容器读取 OPF/spine。
- 抽取 XHTML 正文为章节 TXT 或 Markdown。
- 可选抽取图片资源到派生 images 目录，并在 manifest 中关联章节或 entry。

验收：

- 派生文本被扫描为 `text` + `novel` 或合理 content form。
- 章节顺序稳定。
- HTML 标签、ruby、脚注、图片 alt 等复杂结构有保守降级策略。

边界：

- 不处理 DRM。
- 不承诺保留原书排版。

### M06：PDF 支持方案与首版落地

交付：

- 根据用户确认选择 PDF backend。
- 首版优先抽取文本型 PDF，按页或逻辑章节输出 TXT。
- 扫描版 PDF、图片型 PDF 或空文本页返回 warning。

验收：

- 无 backend 时 UI/整理结果明确提示依赖缺失。
- 文本型 PDF 能派生为 text unit，并保留页码来源。

边界：

- 未确认依赖或外部工具前不得实现临时 PDF parser。
- 首版不做 OCR。

### M07：7z/RAR/CBR 支持方案与首版落地

交付：

- 根据用户确认选择外部 7z 工具或依赖。
- `.7z` 至少支持漫画图片包安全展开。
- `.rar/.cbr` 是否借用同一 backend 由用户确认。

验收：

- 依赖缺失、密码保护、损坏归档有明确 warning。
- 展开后的图片目录复用 M04 的扫描与来源追踪。

边界：

- 不捆绑来源不明的二进制。
- 不绕过路径与大小安全检查。

### M08：来源追踪贯通 run plan 与角色卡证据

交付：

- scanner 能读取预处理 manifest 并写入 `MaterialRef.metadata`。
- chunk/episode 聚合和角色卡 evidence metadata 保留原容器摘要。

验收：

- 从 ZIP/EPUB/PDF 派生材料生成的 run plan 中能看到 `preprocessed_from_raw` 和 `source_entry_path`。
- 角色卡 `source_context.source_runs` 不退化，evidence source metadata 不丢失媒体类型和 content form。

边界：

- 角色卡编译不直接打开原容器。

### M09：GUI 反馈与四语 i18n

交付：

- 更新文件选择器过滤器。
- 更新素材整理进度、完成、warning 和失败文案。
- 四语 i18n key 补齐并通过验证。

验收：

- `scripts/validate_i18n_keys.py` 通过。
- 项目页不会出现硬编码用户可见文案。

边界：

- 不改变角色卡页面职责。

### M10：回归、真实素材验收与文档同步

交付：

- 新增输入格式预处理验证脚本。
- 接入 `scripts/validate_multi_material_regression.py`。
- 使用用户提供的 EPUB、漫画 ZIP/CBZ、PDF/7z 样本做本地验收，样本不提交。
- 更新 `docs/reference/extraction-workflow.zh_CN.md`、相关 `ARCHITECTURE.md` 和当前 TODO。

验收：

- 统一离线回归通过。
- 真实素材验收记录包含输入、派生产物、扫描结果、warning、知识库结果和角色卡证据检查。

边界：

- 不把用户素材、派生材料或验收输出提交到仓库。

## 12. 验证与自审查

默认验证命令：

```powershell
conda run -n CharaPicker python scripts\validate_input_format_preprocessing.py
conda run -n CharaPicker python scripts\validate_multi_material_regression.py
```

按改动范围补充：

```powershell
conda run -n CharaPicker python scripts\validate_media_type_support.py
conda run -n CharaPicker python scripts\validate_multi_material_scanner.py
conda run -n CharaPicker python scripts\validate_i18n_keys.py
```

代码自审查重点：

- 是否仍只使用四个顶层媒体类型。
- 是否没有把 manifest sidecar 扫描成用户文本素材。
- 是否所有解包路径都被限制在目标目录内。
- 是否有 entry 数量、总大小、单文件大小和未知后缀限制。
- 是否取消后清理临时目录。
- 是否未记录完整正文、完整 PDF 文本或大型素材内容。
- 是否没有新增未确认依赖。
- 是否 GUI 只负责进度和反馈，不承担解析逻辑。
- 是否真实素材不会进入 git 变更。

## 13. 提交分组

- `docs: plan input format support`
  - 覆盖计划书、计划索引和 TODO 链接。
  - 提交前检查：`git diff -- docs/plans`。

- `feat: classify preprocessable input formats`
  - 覆盖 M02。
  - 提交前检查：media type 支持验证。

- `feat: add safe material preprocessing`
  - 覆盖 M03。
  - 提交前检查：安全边界验证。

- `feat: preprocess epub and comic archives`
  - 覆盖 M04、M05。
  - 提交前检查：预处理验证、scanner 验证、统一回归。

- `feat: preprocess pdf and extended archives`
  - 覆盖 M06、M07；仅在依赖策略确认后执行。
  - 提交前检查：依赖可用/缺失双路径验证。

- `feat: surface preprocessed source metadata`
  - 覆盖 M08、M09。
  - 提交前检查：i18n、角色卡 evidence metadata 验证。

- `docs: document input preprocessing workflow`
  - 覆盖 M10 文档同步。
  - 提交前检查：确认没有用户素材或派生产物被暂存。

如用户要求提交，提交信息遵循 Conventional Commits，并使用 `git commit -s`。

## 14. 验收后收尾

验收后才开始收尾。收尾范围包括：

- 删除临时验证入口、临时 feature flag 或调试输出。
- 清理测试期间生成的项目、cache、materials 派生产物和真实素材验收输出。
- 确认 `docs/plans/TODO.zh_CN.md` 中对应 P0 状态更新。
- 若计划完成，按项目规则把本文移动到 `docs/archive/` 并更新 `docs/plans/README.md`。
- 如长期项目事实发生变化，再建议是否更新 `AGENTS.md`，但不擅自修改。

## 15. 待确认问题

- PDF 首版采用哪种方案：新增纯 Python 依赖、调用外部工具，还是先后置只保留 warning？
- 7z/RAR/CBR 是否允许依赖外部 `7z` 可执行文件，是否需要应用内下载器或只做用户本地路径配置？
- EPUB 插图是否在首版进入正式图片提取，还是只作为章节 metadata 和后续增强？
- ZIP 是只按漫画包处理，还是允许作为通用混合资料包并递归分派已支持素材？
- 解包上限的默认值如何设定：entry 数、单文件大小、总展开大小、压缩比阈值是否需要暴露为用户设置？
- 除 EPUB、ZIP/CBZ、PDF、7z 外，下一批优先格式是否包括 HTML、DOCX、MOBI/AZW3 或其它来源？
