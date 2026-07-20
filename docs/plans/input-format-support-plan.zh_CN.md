# 更多输入格式支持执行计划（zh_CN）

> 本文档是执行计划，不代表实现状态。

最近整理日期：2026-07-20。

计划状态：执行中，M01-M09 已完成；下一阶段为 M10“RAR 格式支持与流程验证”。

适用阶段：在路线 01、路线 02、路线 03 已完成并归档后，补齐真实素材暴露出的输入格式与输入容器缺口。本文档只覆盖 `.zip`、`.cbz`、`.epub`、`.pdf`、`.7z`、`.rar` 和 `.cbr` 的受控导入、预处理、来源追踪和验收策略。

执行闸门：实现代码前必须先确认本文档的范围、格式顺序和非目标。M02-M04 只建立共同协议与安全边界，不得提前把候选格式暴露为可用；每个格式仅在前一个格式完成流程验证和统一回归后开始。PDF、7z、RAR、CBR 的解析或解包后端仍必须在各自里程碑开始前单独确认。未确认前只允许维护计划文档，不落地业务代码。

当前分支：`input-format-support-plan`。

## 1. 目的

CharaPicker 当前已经支持把视频、文本、字幕、音频、静态图片和漫画图片目录映射进 `FormalExtractionRunPlan`，并通过 `video`、`image`、`audio`、`text` 四种顶层媒体类型进入预览、正式提取、知识库聚合和角色卡证据链路。

真实素材验收暴露出的剩余缺口是输入格式：用户手里常见的是 EPUB 小说、漫画 ZIP/CBZ/7z、PDF 设定集或文档，而当前应用要求用户先手工抽取为 TXT 或图片目录。这会破坏 Extract Once 的体验，也会丢失原容器到派生素材的来源追踪。

本计划目标是把“输入容器/复杂文档”变成受控预处理阶段：原容器仍保存在 `raw/`，应用在 `materials/` 生成现有提取链路能消费的 TXT、Markdown、图片目录或其它支持格式，并把原容器、容器内路径、派生文件和后续 evidence 关联起来。

## 2. 范围

本计划覆盖：

- 标准库 ZIP 工具链：`.zip`、`.cbz`、`.epub`。ZIP 安全展开已支持的叶子素材；CBZ 作为仅图片页的漫画 profile；EPUB 只抽取正文、章节结构和标题。
- PDF 工具链：`.pdf`。首版只处理可提取文字的文档；在该工具链开始前完成 PDF backend 决策、接入和验证。
- Archive 工具链：`.7z`、`.rar`、`.cbr`。7z/RAR 展开受支持素材；CBR 作为仅图片页的 RAR 漫画 profile；三种格式复用同一个已确认的 archive backend。
- 受控预处理 manifest：记录原始容器、容器内 entry、派生材料路径、计数、大小、warning 和失败原因。
- GUI 素材整理流程：用户仍通过项目页添加素材并点击“开始整理”，耗时预处理在 worker 中执行，页面只展示进度和结果。
- 逐格式离线验证和真实素材验收：每个格式均覆盖安全边界、格式识别、派生路径、扫描结果、run plan 来源 metadata、重整/清理和统一回归。

## 3. 非目标

- 不新增顶层媒体类型。代码层仍只允许 `video`、`image`、`audio`、`text`。
- 不把 EPUB、PDF、ZIP、7z 作为新的正式提取 handler；它们是输入预处理来源，不直接进入模型请求。
- 不破解 DRM、密码保护、加密 PDF、加密压缩包或受版权保护的访问限制。
- 不在首版实现 OCR、漫画对白识别、PDF 页面视觉理解或复杂版面重建。
- 不支持第三批或其它非常规输入格式：不接受用户直接导入 `.html/.xhtml`、`.docx`、`.odt`、`.mobi`、`.azw3`、`.fb2`、`.tar` 或其它归档/电子书格式；`.xhtml` 只作为 EPUB 容器内部成员解析，不构成独立输入格式。
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
- `.zip`、`.cbz`、`.epub` 使用标准库 ZIP 工具链连续实现；完成该组前不引入 PDF 或 archive backend。
- PDF 和 7z/RAR/CBR 不使用临时硬编码方案；必须先确认使用外部工具、可选依赖或后置策略。
- PDF 工具链唯一 backend 为 `pypdf>=6.14.2,<7`；只提取文本页，不安装 crypto extra，加密 PDF 统一拒绝，大版本升级必须单独验证。
- 容器文件本身不得作为普通可提取素材链接到 `materials/` 根目录；`materials/` 只保存当前扫描器可消费的派生 TXT/图片目录或已支持素材。
- 格式启用顺序固定为 `.zip`、`.cbz`、`.epub`、`.pdf`、`.7z`、`.rar`、`.cbr`；后一个格式不得与前一个格式并行实现或跳过其验收。
- 工具链切换顺序固定为“标准库 ZIP -> PDF -> Archive”：一个工具链内的全部格式、通用验证和提交完成前，不得开始下一工具链，也不得在后续里程碑回头扩展已完成工具链。
- `InputFormatProfile` 的 `enabled` 仅表示该格式的受控工作流已完成并获验收；它不等同于运行时 backend 可用。PDF 与 Archive 工具链的 enabled 格式在本机 backend 缺失、不可执行或 capability probe 失败时仍可被选择，但整理流程必须返回明确 warning，不能回退到普通导入或静默失败。
- 每个格式的支持都必须通过同一套端到端流程验证：文件选择/状态识别、导入 `raw/`、预处理与 manifest、`materials/` 扫描、run plan 来源追踪、重新整理和移除/清理 raw，以及格式特有失败路径。通过后才允许启用其文件过滤器和进入下一格式。
- 逐格式验证使用可复现的离线构造样本；用户提供的真实素材仅用于本地补充验收，绝不提交到仓库。
- `.zip` 只展开后缀白名单内的已支持叶子文件，不递归分派或展开嵌套 ZIP、CBZ、EPUB、7z、RAR、CBR 和 PDF；嵌套容器一律记录 warning。
- EPUB 首版只派生正文 TXT 或 Markdown；封面和内嵌插图不进入 `materials/` 或正式图片提取，最多保留为 manifest entry 摘要。
- 首版安全上限固定为最多 4096 个 entry、单 entry 512 MiB、总展开 4 GiB、压缩比 200；暂不暴露为用户设置，后续只能基于真实验收数据在独立变更中调整。

## 5. 当前状态与目标状态

### 5.1 当前事实

- `utils.media_types` 已集中定义视频、图片、音频、文本、timed text 和漫画压缩包后缀。
- 当前 `SUPPORTED_SOURCE_SUFFIXES` 只允许直接可处理的四媒体文件进入导入链路；`.epub` 为 unknown，`.zip/.cbz/.rar/.7z/.cbr` 当前不支持导入。
- `utils.source_importer` 负责把外部素材复制进 `raw/`，再把 raw 素材链接或物化到 `materials/`。
- `utils.material_processing_middleware` 是项目页触发素材整理的中间层，已把长耗时任务放进 GUI worker。
- `core.material_unit_scanner` 已能扫描 `materials/` 中的 TXT/MD/JSON、SRT/ASS、音频、静态图片和图片目录，并把图片目录识别为 `image_set` / `manga` 候选。
- 统一离线回归入口是 `scripts/validate_multi_material_regression.py`。
- `requirements.txt` 已声明文本型 PDF 预处理使用的 `pypdf>=6.14.2,<7`；当前没有 7z 或 RAR 专用解析依赖。

### 5.2 目标状态

- 用户只能在对应 profile 通过单格式流程验证并被标记为 enabled 后，把 `.zip`、`.cbz`、`.epub`、`.pdf`、`.7z`、`.rar`、`.cbr` 加入项目素材列表。
- 点击“开始整理”后，应用把可预处理格式安全转换为当前提取链路已支持的 TXT/MD 或图片目录。
- `materials/` 中的派生材料能被现有扫描器识别，不需要新增媒体类型。
- run plan、chunk、episode、season 和角色卡证据能追溯到原始容器与容器内 entry。
- 不支持、加密、过大、疑似解压炸弹、路径穿越、格式损坏或依赖缺失都能给出可解释 warning，不阻断其它可处理素材。
- 先依次完成标准库 ZIP 工具链中的 `.zip`、`.cbz`、`.epub`，再完成 PDF 工具链中的 `.pdf`，最后连续完成 Archive 工具链中的 `.7z`、`.rar`、`.cbr`。任何格式未通过单格式流程验证时，后续格式与下一工具链均不开始。

### 5.3 现有代码约束

- `utils.source_importer._expand_source_paths()` 当前只收集 `is_import_supported_source()` 为 true 的文件；扩展输入格式时需要区分“直接可导入”和“需预处理后导入”。
- `utils.material_processing_middleware.process_source_request()` 当前把 `raw_sources` 直接交给 `link_raw_sources_to_materials()` 或 `process_raw_sources_with_ffmpeg()`；实现时必须先拆分 direct sources、preprocessable containers 和 unsupported sources。
- `utils.ffmpeg_tool.process_raw_sources_with_ffmpeg()` 会把非视频 raw source 链接到 `materials/`。容器源不得落入这个兜底分支，否则 `.epub/.zip/.pdf/.7z` 会被错误链接为可扫描材料。
- `utils.source_importer.remove_project_sources()` 和 `remove_raw_sources()` 当前只按 raw 相对路径删除同名 materials 目标；新增派生目录后，删除源容器时必须同步删除对应 `derived_inputs/{safe_stem}_{source_hash}/` 和 cache manifest。
- `utils.source_importer.clean_raw_sources()` 当前会在删除 raw 前尝试把 raw materialize 到同名 `materials/` 目标；对容器源必须改为确认派生材料已存在并保留 manifest，而不是把原容器复制到 `materials/`。
- `core.material_unit_scanner` 当前只扫描 `materials/` 下文件系统内容；manifest 放在 `cache/` 后，需要通过派生输出路径反查 metadata，而不是让 scanner 递归扫描 cache。

## 6. 输入格式与工具链顺序

共享预处理协议和素材生命周期完成后，先连续完成同一工具链内的全部格式，再切换下一工具链。后面的候选格式可以被 `utils.media_types` 识别为“待支持/需后端”，但在本行验收通过前不得出现在项目页的可选文件过滤器中。

| 顺序 | 输入格式 | 工具链 | 首版输出到 `materials/` | 后端策略 | 格式边界 |
| --- | --- | --- | --- | --- | --- |
| 1 | `.zip` | 标准库 ZIP | 图片目录、文本文件或其它已支持素材目录 | 标准库 `zipfile` | 只展开白名单内的叶子 entry；嵌套容器只产生 warning |
| 2 | `.cbz` | 标准库 ZIP | 图片目录 | 复用 ZIP 读取与安全校验 | 仅图片页漫画包；不能因 ZIP 支持而跳过 CBZ profile 验证 |
| 3 | `.epub` | 标准库 ZIP | 文本章节 | 标准库 `zipfile` + 内部 OPF/spine/XHTML 解析 | 不处理 DRM；只保留可用正文与稳定章节顺序，插图不进入正式提取 |
| 4 | `.pdf` | PDF | 按页或逻辑章节的文本 | 在 PDF 工具链开始前确认一个 backend | 只处理文本型 PDF；扫描版、加密或空文本页只给 warning |
| 5 | `.7z` | Archive | 图片目录、文本文件或其它已支持素材目录 | 在 Archive 工具链开始前确认一个 backend | backend 策略未确认时保持 blocked；实现验收后本机 backend 缺失时返回 warning |
| 6 | `.rar` | Archive | 图片目录、文本文件或其它已支持素材目录 | 复用已确认的 Archive backend | 即使复用 7z 后端也要单独验证 RAR 错误和安全路径 |
| 7 | `.cbr` | Archive | 图片目录 | 复用已确认的 Archive backend | 仅图片页漫画包；不能因 RAR 支持而跳过 CBR profile 验证 |

### 6.1 工具链切换规则

- 标准库 ZIP 工具链只使用 Python 标准库与内部解析；M05-M07 完成前不得为 PDF 或 Archive 引入依赖、外部可执行文件或适配器。
- PDF 工具链在 M08 开始时一次性确认、接入并验证一个 PDF backend；M08 完成后不再变更 PDF backend 或扩展 PDF 功能范围。
- Archive 工具链在 M09 开始时一次性确认、接入并验证一个 archive backend；M10 和 M11 只新增 `.rar`、`.cbr` profile 与其验证，不得替换 backend 或复制新的解包路径。
- 任何工具链的 backend 选型、许可证、安装/打包影响、fake adapter 和真实 capability probe 都在该工具链首个里程碑内完成并固化；发现不满足条件时停止当前工具链，不跳到下一组绕开问题。

### 6.2 单格式流程验证闸门

每个格式在启用前必须有一个独立的格式 profile 验收用例，并按以下流程全部通过。对于需要外部 backend 的格式，第 1 步的 enabled 与第 3 步的 runtime capability 是两个独立状态：

1. 该后缀被识别为当前格式 profile，而非新的 `MediaType`；未启用时文件选择器不展示它。
2. 选择文件后，容器副本只写入 `raw/`，不会被普通 link 或 FFmpeg 兜底写入 `materials/`。
3. 预处理通过安全检查后产生完整 manifest 和可消费的派生材料；取消或失败不留下半成品。
4. `core.material_unit_scanner` 只扫描派生材料，能得到既有四媒体类型与合理 `ContentForm`。
5. `FormalExtractionRunPlan` 能引用派生材料，并保留压缩后的原容器与 entry 来源 metadata；验证不依赖真实模型调用。
6. 同一 raw 内容重新整理可复用正确产物；移除源和清理 raw 按 manifest 处理派生材料；该格式的损坏、加密/密码保护或 backend 缺失路径有明确 warning。

M05-M11 每完成一项，必须运行该格式 profile 用例、此前所有 profile 用例和统一离线回归。工具链内最后一个格式通过后，还必须完成该工具链的专属架构与 capability 复核，才能切换到下一工具链。

## 7. 数据与持久化

### 7.1 路径规则

- `raw/` 保存用户选择的原始容器文件，不在导入时破坏原文件。
- `materials/` 保存预处理后的可消费材料，不保存等待预处理的原容器副本。建议使用稳定派生根目录，例如：

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
- 派生输出根目录必须由 raw 相对路径和内容 hash 共同决定，避免两个同名外部文件互相覆盖。

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
- `entry_summaries`（需保留容器内非派生成员时使用，例如 EPUB 内嵌图片）
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

### 7.4 素材生命周期

- 导入：可预处理容器允许进入 `raw/`，但不直接进入正式扫描。
- 整理：`material_processing_middleware` 先执行容器预处理，再处理或链接直接支持的素材；失败容器只产生 warning，不阻断其它素材。
- 重新整理：同一 raw 容器内容 hash 未变化时可复用派生产物；hash 变化时旧派生目录标记 stale 或被替换，不能混入新 run。
- 移除：删除 raw 容器时同步删除对应派生目录和 preprocessing manifest。
- 清理 raw：只有派生材料完整可用时才允许把容器 raw 标记为 cleaned；清理后无法重新生成派生材料，UI 文案必须直说。
- 洁净正式提取：`knowledge_base` 的 clean 只清理可再生提取产物，不删除 `materials/derived_inputs/` 或 preprocessing manifest。

## 8. 安全与失败策略

### 8.1 解包安全

所有容器预处理必须先经过安全检查：

- 禁止绝对路径、盘符路径、`..` 路径穿越和空文件名。
- 忽略或拒绝 symlink、hardlink、设备文件、目录伪装和平台危险路径。
- 限制 entry 总数、单文件大小、解包总大小和压缩比。
- 只允许进入白名单后缀；未知后缀进入 warning，不写入可扫描材料目录。
- 先解到 `cache` 下临时目录，完成校验后再原子移动或复制到 `materials/`。
- 取消任务时清理临时目录，不留下半截材料。
- 外部工具后端必须使用 `subprocess` 参数列表调用，不拼接 shell 字符串；执行前先 list/test archive，按白名单逐项抽取或在抽取后再次校验目标路径。
- Windows 保留名、尾随点/空格、大小写碰撞和 Unicode 归一化碰撞必须进入安全校验，避免不同 entry 覆盖同一派生文件。

### 8.2 格式失败

- 损坏 `.zip`、`.cbz`、`.epub`、`.pdf`、`.7z`、`.rar`、`.cbr` 不阻断其它素材。
- 加密、密码保护、DRM 或依赖缺失返回明确 warning。
- 部分 entry 失败时记录 failed entry 摘要，已成功的派生材料仍可进入扫描。
- 日志只记录文件名、项目内相对路径、计数和脱敏错误摘要，不输出完整正文或大段原始内容。

## 9. UI 与用户工作流

- 项目页文件过滤器只显示已经通过单格式流程验证的 enabled profile；候选、blocked 和尚未轮到的格式不得显示为可选择输入。格式启用后补充其四语格式名、整理进度、warning 和失败文案，并明确它需要先整理后提取。
- 素材列表状态可继续复用现有 `new/processed/stale/rawCleaned`，但 tooltip 或整理结果需要显示预处理 warning。
- “开始整理”继续走 `SourceProcessingWorker`，页面不直接处理文件。
- 处理进度需要覆盖复制、预处理、FFmpeg 处理和链接阶段，避免用户看到长时间无反馈。
- 处理完成 InfoBar 应显示材料数量，并在有 warning 时提示用户查看洞察流、日志或整理结果摘要。
- UI 可见文案必须同步维护 `i18n/zh_CN.json`、`zh_TW.json`、`en_US.json`、`ja_JP.json`。

## 10. 代码结构边界

建议新增或调整的边界：

- `utils.media_types`：保留现有 `SourceSupportProfile`、`SUPPORTED_SOURCE_SUFFIXES` 和四媒体类型的“直接可处理素材”语义；新增独立的 `InputFormatProfile`（或等价命名）集中声明容器格式、固定启用顺序、`candidate/blocked/enabled` 状态和 preprocessor key。它是模块内静态映射，不引入动态注册或插件机制。新增 `input_format_profile()`、`is_preprocessable_source()` 等 helper，但不让容器后缀返回 `MediaType`、进入 `SUPPORTED_SOURCE_SUFFIXES` 或被标成可直接正式提取。任何其它模块不得自行维护后缀集合或跳过 profile 状态。
- `utils.source_importer`：继续把 `is_import_supported_source()` 解释为直接素材导入；通过 `is_project_input_supported_source()`（或等价组合 helper）接纳 direct source 或 enabled `InputFormatProfile` 到 `raw/`，并计算 raw 目标。移除和 raw 清理路径必须通过预处理 manifest 处理派生材料。
- `utils.material_preprocessing.py` 或等价模块：承载 ZIP、CBZ、EPUB、PDF、7z、RAR、CBR 的预处理分派、安全检查、manifest 写入和取消检查；建议定义 `PreprocessingRequest`、`PreprocessingResult`、`DerivedMaterialRecord` 和 `PreprocessingWarning`。格式 handler 只能消费该模块提供的已校验 entry，不能自行解包、拼派生路径或写 manifest。
- PDF 与 Archive 工具链的 backend 通过 `utils.material_preprocessing` 内部的窄适配协议接入：适配器只报告 capability、列举/测试、读取或抽取的结果，公共层统一执行路径、大小、后缀和 manifest 校验。适配器不得泄漏到 `gui`、`core` 或 `source_importer`。
- 适配器必须可在验证中替换为确定性 fake；真实 backend 另有 capability probe 和本地集成验证。缺失 backend 的 warning 用例属于常规离线回归，不能只靠人工测试。
- `utils.material_preprocessing.py` 不导入 `core` 或 `gui`；manifest 中的 `media_type`、`content_form_hint` 和 `source_entry_path` 使用普通字符串，避免 utils 反向依赖提取计划模型。
- 预处理 manifest 路径、派生根目录和索引读取 helper 应集中在 `utils.material_preprocessing.py` 或等价 helper 中，避免 `source_importer`、`source_status`、`material_processing_middleware` 和 `core.material_unit_scanner` 各自拼路径。
- `utils.material_processing_middleware`：在 source import 后拆分 direct sources 与 preprocessable containers；原始模式下 link direct sources 并 preprocess containers，非原始模式下只把视频交给 FFmpeg、把直接非视频素材链接、把容器交给预处理。它只根据格式 profile 调度，不承载某一种格式的解析细节。
- `utils.source_status`：识别受控容器源的 raw/materials 状态和派生材料状态。
- `core.material_unit_scanner`：通过派生材料相对路径读取预处理 manifest，把派生材料的原容器 metadata 写入 unit；不得扫描 cache 或把 manifest 当文本 unit；写入 run plan 的 metadata 应使用压缩摘要，完整 entry 明细继续留在 preprocessing manifest。
- `gui.pages.project_page`：只从格式 profile 构建当前已启用的文件过滤器，展示进度和结果文案，不承载格式解析，也不提前展示候选或 blocked 格式。
- `scripts/validate_input_format_preprocessing.py`：新增离线验证入口，为每个已启用格式保留独立 profile 用例，并由统一回归脚本自动调用。

## 11. 里程碑

### M01：计划确认与当前基线复核

交付：

- 确认本计划范围、固定格式顺序和非目标。
- 明确 `.zip`、`.cbz`、`.epub` 使用标准库先行；`.pdf`、`.7z`、`.rar`、`.cbr` 进入独立后端闸门。
- 运行现有统一离线回归，记录当前基线。

验收：

- `scripts/validate_multi_material_regression.py` 通过。
- 用户确认只能依次执行 M02-M04、标准库 ZIP 工具链 M05-M07、PDF 工具链 M08 和 Archive 工具链 M09-M11；每次工具链切换均受 6.1 约束。

边界：

- 不改业务代码。

### M02：输入格式支持档位与预处理协议

交付：

- 在 `utils.media_types` 中新增独立于 `SourceSupportProfile` 的 `.zip`、`.cbz`、`.epub`、`.pdf`、`.7z`、`.rar`、`.cbr` `InputFormatProfile`，集中定义固定顺序、`candidate/blocked/enabled` 状态和 preprocessor key。
- 定义预处理结果模型、warning reason、manifest schema、派生路径规则和默认安全上限。
- 更新媒体类型验证脚本，锁定七种候选格式都不会被误判为正式 `MediaType`，不会进入 `SUPPORTED_SOURCE_SUFFIXES` 或现有 `SourceSupportProfile` 的 direct-import 路径；M02 完成时所有格式仍为 candidate 或 blocked，不开放用户导入。

验收：

- 七种候选格式不会被误当成 `video/image/audio/text` 正式 unit。
- source importer/source status 可查询“需预处理”“候选未启用”和“blocked/依赖缺失”状态。

边界：

- 不新增顶层 `MediaType`。
- 不把任何候选格式伪装成已可提取或提前显示在文件选择器中。

### M03：安全预处理核心

交付：

- 新增预处理分派模块和内部数据模型。
- 建立临时目录、取消检查、路径穿越防护、大小/数量限制、后缀白名单、文件名碰撞检查和 manifest 写入。
- 完成 ZIP 类容器的 list/validate/extract 基础能力和格式无关的 manifest 写入，但不接入 GUI 工作流，也不把 `.zip` 标为 enabled。

验收：

- 恶意路径、超限文件、未知后缀、损坏容器均返回结构化 warning。
- 取消任务后不保留半成品材料。
- 所有解包输出路径经校验后仍位于临时目录或目标派生目录内。

边界：

- GUI 不直接调用预处理内部函数。
- 不改正式提取 handler。

### M04：素材生命周期与处理中间件接线

交付：

- `source_importer` 允许已启用的可预处理容器进入 `raw/`；candidate 和 blocked 格式不得绕过 profile 状态进入导入。
- `material_processing_middleware` 拆分 direct sources、preprocessable containers 和 unsupported sources。
- 原始模式和非原始模式都能正确处理容器：容器走预处理，视频按配置走 FFmpeg，直接非视频素材走 link/materialize。
- 移除源、清理 raw、重新导入和 stale 状态都能处理派生目录和 manifest。
- `core.material_unit_scanner` 能通过派生材料路径反查 manifest，并把压缩来源摘要写入 `MaterialRef.metadata`；项目页只从 enabled profile 构建文件过滤器与状态文案。

验收：

- 任何已启用容器都不会被 link 到 `materials/` 根目录；candidate 或 blocked 格式无法通过 UI 或 importer 进入 raw。
- 删除一个 raw 容器会删除对应派生目录和 cache manifest。
- raw 清理不会把原容器复制到 `materials/`。
- 取消或失败时不会破坏已有可用派生成果。
- 基于构造 manifest 的 scanner/run plan 验证能保留 `preprocessed_from_raw` 和 `source_entry_path`，且 scanner 不扫描 `cache/`。

边界：

- 不改变 `projects/{project_id}` 根目录职责。
- 不删除用户未选择的其它素材或派生产物。
- M04 不启用任何格式；第一个可用文件过滤器只能在 M05 `.zip` 通过单格式流程验证后开放。

### M05：`.zip` 格式支持与流程验证

开始条件：M02-M04 全部通过。

交付：

- 只启用 `.zip` profile，安全展开白名单内的图片、文本和其它已支持素材；不递归处理嵌套归档。
- 生成稳定的派生目录、entry 映射和 manifest，并在项目页开放 `.zip` 文件过滤器与对应四语文案。
- 为 `.zip` 增加独立的构造样本和端到端 profile 验证。

验收：

- 通过 6.2 的六步流程验证，派生图片目录能被扫描为 `image_set` / `manga` 候选，文本仍进入既有 text 链路。
- zip bomb、路径穿越、文件名碰撞、损坏包、未知 entry 和取消操作都有离线验证；不支持的图片如 GIF/BMP 仍保留当前 warning。
- `.zip` profile、此前通用验证和 `validate_multi_material_regression.py` 全部通过后，才能进入 M06。

边界：

- 不把 `.cbz`、`.epub` 或 ZIP 工具链之外的后缀与 `.zip` 一并开放。
- 不跨目录自动合并章节，不把嵌套压缩包作为普通 entry 解开。

### M06：`.cbz` 格式支持与流程验证

开始条件：M05 的所有验收通过。

交付：

- 只启用 `.cbz` profile，复用已经验证的 ZIP 安全读取能力，但限制为漫画图片页。
- 以自然排序输出单一图片目录，并为每一页写入原 entry 映射；在项目页开放 `.cbz` 文件过滤器与对应四语文案。
- 新增 `.cbz` 构造样本和独立 profile 验证，不以 `.zip` 的通过结果替代它。

验收：

- 通过 6.2 的六步流程验证；图片页顺序、空包、夹杂非图片 entry、损坏包和路径安全都有覆盖。
- `.zip` 与 `.cbz` profile、统一离线回归全部通过后，才能进入 M07。

边界：

- 不把 `.cbz` 当作通用混合资料包，不允许文本或嵌套归档作为漫画页进入 materials。

### M07：`.epub` 格式支持与流程验证

开始条件：M06 的所有验收通过。

交付：

- 只启用 `.epub` profile，作为 ZIP 容器读取 OPF、spine 和 XHTML 正文，派生章节 TXT 或 Markdown。
- 在 manifest 中保留章节和内嵌图片 entry 摘要，但只把正文派生到 `materials/`；在项目页开放 `.epub` 文件过滤器与对应四语文案。
- 新增 `.epub` 构造样本和独立 profile 验证。

验收：

- 通过 6.2 的六步流程验证；派生文本被扫描为 `text` 与合理的小说 content form，章节顺序稳定，run plan 具有 spine/entry 来源摘要。
- 缺失 OPF/spine、损坏 XHTML、DRM/加密提示、复杂 HTML 标签、ruby、脚注和图片 alt 均有保守降级或 warning 验证；内嵌图片不会被扫描为正式 image unit。
- `.zip`、`.cbz`、`.epub` profile、标准库 ZIP 工具链复核与统一离线回归全部通过后，才允许切换到 PDF 工具链。

边界：

- 不支持用户直接导入 `.html/.xhtml`，不处理 DRM，不承诺保留原书排版。

### M08：`.pdf` 格式支持与流程验证

开始条件：M07 的所有验收通过，且用户已确认 PDF backend、依赖或外部工具的来源、用途、替代方案和打包影响。

交付：

- 只启用 `.pdf` profile；首版从文本型 PDF 抽取按页或逻辑章节的文本，并保留页码来源。
- 在 `utils.material_preprocessing` 内接入已确认的唯一 PDF backend 与 capability probe，不让 PDF 解析或 backend 配置泄漏到 GUI、core 或 source importer。
- 明确无 backend、加密、扫描版、图片型或空文本页的 warning；在项目页开放 `.pdf` 文件过滤器与对应四语文案。
- 新增 `.pdf` 构造样本、fake adapter 契约用例和独立 profile 验证，包括 backend 可用与缺失两条路径。

验收：

- 通过 6.2 的六步流程验证；文本型 PDF 进入既有 text unit，页码和原容器来源能进入 run plan。
- 已有标准库 ZIP 工具链 profile、`.pdf` profile、PDF backend 可用/缺失路径、PDF 工具链复核和统一离线回归全部通过后，才能切换到 Archive 工具链 M09。

边界：

- 未确认 backend 前不得实现临时 parser；首版不做 OCR、页面视觉理解或复杂版面重建。

### M09：`.7z` 格式支持与流程验证

开始条件：M08 的所有验收通过，且用户已确认 archive backend 的来源、用途、替代方案和打包影响。

交付：

- 只启用 `.7z` profile，通过已确认 backend 安全列举并展开白名单 entry。
- 在 `utils.material_preprocessing` 内完成 Archive backend 的唯一适配器、配置读取与 capability probe；M10/M11 只能复用该适配器。
- 复用统一的安全校验、派生路径和 manifest；在项目页开放 `.7z` 文件过滤器与对应四语文案。
- 新增 `.7z` 构造样本、fake adapter 契约用例和独立 profile 验证，包括 backend 缺失、密码保护和损坏归档路径。

验收：

- 通过 6.2 的六步流程验证；`.7z` 派生材料能进入已有图片或文本扫描链路，完整 archive 明细仍只保存在 manifest；真实 backend 的 capability probe 和集成验证独立通过。
- 已有所有 profile、`.7z` profile、archive backend 可用/缺失路径和统一离线回归全部通过后，才能进入 M10。

边界：

- 不捆绑来源不明的二进制，不绕过外部工具 list/test、路径或大小安全检查。

### M10：`.rar` 格式支持与流程验证

开始条件：M09 的所有验收通过，且已确认 archive backend 对 RAR 的许可、能力和运行时可用性。

交付：

- 只启用 `.rar` profile，可复用已确认 archive backend，但必须独立处理其 list、密码保护和错误语义。
- 复用统一的安全校验、派生路径和 manifest；在项目页开放 `.rar` 文件过滤器与对应四语文案。
- 新增 `.rar` 构造样本、基于 M09 fake adapter 的 RAR 专属契约用例和独立 profile 验证。

验收：

- 通过 6.2 的六步流程验证；RAR 特有的 backend 不可用、密码保护、损坏包和 entry 安全路径都有稳定 warning，真实 backend 的 capability probe 和集成验证独立通过。
- 已有所有 profile、`.rar` profile 和统一离线回归全部通过后，才能进入 M11。

边界：

- 不因 `.7z` 已通过就跳过 RAR 的 capability probe、许可检查或端到端验证。
- 不替换 Archive backend、适配器或配置路径；这些只允许在 M09 的工具链入口完成。

### M11：`.cbr` 格式支持与流程验证

开始条件：M10 的所有验收通过，且 RAR/archive backend 对 CBR 的行为已通过 capability probe。

交付：

- 只启用 `.cbr` profile，复用已验证的 archive backend，但限制为漫画图片页并写入页顺序与 entry 映射。
- 在项目页开放 `.cbr` 文件过滤器与对应四语文案。
- 新增 `.cbr` 构造样本、基于 M09 fake adapter 的 CBR 专属契约用例和独立 profile 验证，不以 `.rar` 的通过结果替代它。

验收：

- 通过 6.2 的六步流程验证；漫画页自然排序、夹杂非图片 entry、密码保护、损坏包和移除/清理生命周期都有覆盖，真实 backend 的 capability probe 和集成验证独立通过。
- 所有七种 profile 与统一离线回归全部通过后，才能进入 M12。

边界：

- 不把 `.cbr` 当作通用 RAR 资料包，不支持嵌套归档或非图片漫画页。
- 不替换 Archive backend、适配器或配置路径；这些只允许在 M09 的工具链入口完成。

### M12：全量回归、真实素材验收与文档同步

开始条件：M05-M11 全部完成。

交付：

- `validate_input_format_preprocessing.py` 覆盖七个独立 profile，并由 `validate_multi_material_regression.py` 调用。
- 逐项使用用户提供的 EPUB、ZIP/CBZ、PDF、7z/RAR/CBR 样本进行本地补充验收，记录每个格式的输入、派生产物、扫描、run plan trace、warning 和清理结果；样本与输出均不提交。
- 更新 `docs/reference/extraction-workflow.zh_CN.md`、相关 `ARCHITECTURE.md`、当前 TODO 和用户文档，只记录实际已启用的七种格式。

验收：

- 七个格式 profile、统一离线回归、i18n key 验证和真实素材验收均通过。
- 角色卡 `source_context.source_runs` 与 evidence metadata 不退化；角色卡编译不直接打开原容器。

边界：

- 不把用户素材、派生材料、验收输出或第三批格式写入仓库或产品承诺。

## 12. 验证与自审查

默认验证命令：

```powershell
conda run -n CharaPicker python scripts\validate_input_format_preprocessing.py
conda run -n CharaPicker python scripts\validate_multi_material_regression.py
```

逐格式执行规则：

- M05-M11 每次只增加当前一个格式 profile；`validate_input_format_preprocessing.py` 必须显式报告当前格式与此前全部 enabled profile 的结果，任一失败均不得启用新后缀。
- 当前格式通过后，运行统一离线回归；PDF 与 Archive 工具链格式还必须覆盖 backend 可用和 backend 缺失/不可用两条路径。
- 每个格式至少使用一个在临时目录生成的正常样本和一个失败样本；真实用户文件只用于本地人工补充验收。

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
- 是否 `utils.material_preprocessing` 没有导入 `core` 或 `gui`，路径 helper 没有散落到多个模块。
- 是否容器源不会被普通 link 或 FFmpeg 非视频兜底路径写入 `materials/`。
- 是否移除源、清理 raw、重新导入和 stale 状态都同步处理派生目录与 manifest。
- 是否 PDF/7z/RAR/CBR 依赖缺失路径有验证，不会阻塞 EPUB/ZIP/CBZ。
- 是否格式 profile 的状态、文件过滤器、source importer 和处理中间件使用同一份集中声明，且只有已验收的后缀为 enabled。
- 是否每一个新增格式都执行了 6.1 的完整流程验证，以及此前所有已启用格式的回归；不得以同一容器 backend 的通过结果替代 `.cbz`、`.cbr` 或其它 profile 的验收。
- 是否 PDF 与 Archive 工具链 backend 的来源、许可、安装/打包影响和 capability probe 已在各自工具链首个里程碑记录并获确认。
- 是否真实素材不会进入 git 变更。

## 13. 提交分组

- `docs: plan input format support`
  - 覆盖计划书、计划索引和 TODO 链接。
  - 提交前检查：`git diff -- docs/plans`。

- `feat: classify preprocessable input formats`
  - 覆盖 M02。
  - 提交前检查：七种候选格式的支持状态与 media type 边界验证。

- `feat: add safe material preprocessing`
  - 覆盖 M03。
  - 提交前检查：安全边界和 format-neutral manifest 验证。

- `feat: integrate preprocessed material lifecycle`
  - 覆盖 M04。
  - 提交前检查：source lifecycle、scanner 来源追踪和 candidate 格式不可见验证。

- `feat: preprocess zip sources`
  - 覆盖 M05。
  - 提交前检查：`.zip` 单格式流程验证、此前用例与统一回归。

- `feat: add cbz comic profile`
  - 覆盖 M06。
  - 提交前检查：`.cbz` 单格式流程验证、`.zip` 回归与统一回归。

- `feat: preprocess epub sources`
  - 覆盖 M07。
  - 提交前检查：`.epub` 单格式流程验证、标准库 ZIP 工具链全部回归与统一回归。

- `feat: add pdf backend and preprocess sources`
  - 覆盖 M08；仅在 PDF backend 策略确认后执行。
  - 提交前检查：`.pdf` 单格式流程验证、backend 可用/缺失双路径和全部前序回归。

- `feat: add archive backend and preprocess 7z sources`
  - 覆盖 M09；仅在 archive backend 策略确认后执行。
  - 提交前检查：`.7z` 单格式流程验证、backend 可用/缺失双路径和全部前序回归。

- `feat: preprocess rar archives`
  - 覆盖 M10；仅在 RAR capability 与许可确认后执行。
  - 提交前检查：`.rar` 单格式流程验证、全部前序回归与统一回归。

- `feat: add cbr comic profile`
  - 覆盖 M11。
  - 提交前检查：`.cbr` 单格式流程验证、全部前序回归与统一回归。

- `feat: surface preprocessed source metadata`
  - 仅用于 M04 后发现来源 metadata 缺失时的独立修复，不作为延后格式验收的替代提交。
  - 提交前检查：scanner、run plan、角色卡 evidence metadata 回归。

- `docs: document input preprocessing workflow`
  - 覆盖 M12 文档同步。
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
- 7z/RAR/CBR 是否允许依赖外部 archive backend；若允许，是只做用户本地路径配置，还是新增受审查的 Python 依赖？不实现应用内下载器。
- 第三批和其它非常规格式已明确不在本计划内；未来如要扩展，必须新开计划并重新评估输入价值、依赖、数据安全和长期维护成本。
