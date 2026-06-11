# 第二阶段：多媒体平级接入前重构解耦执行计划（zh_CN）

最近整理日期：2026-06-09

计划状态：正式执行计划，执行前仍需按当前代码复核。

适用阶段：路线 02，在路线 01 提取质量与可观测性计划打磨完成之后、路线 03 多内容形态覆盖实施之前执行。本计划不假设路线 01 的所有实现已经落地；真正执行路线 02 时，必须先重新核对当时的代码、配置、架构文档和路线 01 已完成项。

执行闸门：路线 02 的任何业务代码重构开始前，必须先生成当前真实结构图和预计重构完成后的目标结构图。两张图经用户审核合格后，才能进入 M03 及后续代码重构里程碑。

## 1. 目的

当前提取主线已经能围绕视频素材完成预览和正式提取，并能在正式提取中配合音频转写、视频帧或原生视频能力生成结构化知识库。但是主链路仍明显以视频为默认素材世界观：

- `core/source_scanner.py` 中正式扫描入口是 `scan_formal_video_materials()`，预览入口是 `collect_preview_video_chunks()`。
- `core/extractor.py` 中正式提取入口调用 `prepare_formal_video_extraction_plan()`，chunk 输入收集、模型请求、`source_kind`、预算缩放和提示词变量都以视频 chunk 为主。
- `utils/cloud_model_presets.py`、`gui/pages/model_page.py`、`gui/main_window.py` 仍保留视频输入模式、视频 FPS、按视频分钟缩放输出期望等配置语义。
- `utils/audio_transcription.py` 已能生成 `episode_transcript.json`，但目前更像视频提取的辅助上下文，不是平级素材入口。
- `utils/media_types.py` 已声明视频、图片、文本后缀集合，但平级素材扫描、计划、提取、知识库消费尚未贯通。

第二阶段的目标不是立刻支持所有素材，而是在接入更多内容形态前先把结构拆清楚：让番剧/视频类内容在代码层成为 `video` 媒体类型的一种输入，而不是整条 Extract Once 工作流的隐含前提。

完成后，后续路线 03 应能在不重写主提取流程的前提下，把番剧、漫画、广播剧、小说、设定集、台本和混合资料包等内容形态映射到 `video`、`image`、`audio`、`text` 四种代码层媒体类型接入。

## 2. 范围

本计划覆盖多媒体接入前的架构体检、耦合拆分、内部边界固化和回归验证。

核心范围：

- 梳理当前视频导向的扫描、预览、正式提取、知识库写入、预算、进度和 UI 触发耦合。
- 生成当前真实结构图和目标重构结构图，并把用户审核通过作为执行重构的硬前置条件。
- 定义素材平级入口的内部词汇、数据契约和模块责任边界。
- 把“生成提取计划”和“执行某种素材的模型调用”拆成可独立演进的层次。
- 保留现有视频预览、正式提取、clean 模式、fast 模式和音频转写辅助路径的用户可见行为。
- 为路线 03 预留番剧、漫画、广播剧、小说、设定集、台本、混合资料包等内容形态的接入口和验收口径，并明确它们与四种代码层媒体类型的映射。

## 3. 不做范围

- 不在本阶段实现完整小说/设定文本、字幕/台本、图片/漫画、广播剧或混合资料包提取功能。
- 不在本阶段承诺音频转写可以独立生成完整角色档案。音频转写可被整理为平级素材候选，但正式覆盖留给路线 03。
- 不改变 `projects/{project_id}/raw/`、`materials/`、`cache/`、`knowledge_base/`、`output/` 的根目录语义。
- 不把预览产物默认升级为正式知识库事实。预览与正式提取边界仍按既有原则处理。
- 不引入新依赖。
- 不做大爆炸重写，不做空泛插件系统，不提前设计第三方扩展市场。
- 不把 GUI 层改成素材扫描、知识库写入或模型调用的承载层。
- 不绕过 `utils.ai_model_middleware` 直连模型后端。
- 不把 `ProjectConfig.target_characters` 重新引入新编译链路；它仍只作为旧项目兼容字段。

## 4. 已确认原则

- 保持用户可见行为优先。02 是重构解耦阶段，默认不改变现有视频工作流输出语义。
- 当前代码事实优先。roadmap、框架文档和目标工作流只提供方向，不能当作已实现证明。
- 执行时必须先画图再重构：当前真实结构图要基于代码和架构文档，目标结构图要体现预计拆分后的模块边界、依赖方向和核心数据流。两张图未经用户审核通过，不得开始业务代码重构。
- 术语必须分层：代码层只区分 `video`、`image`、`audio`、`text` 四种媒体类型；产品和用户表达层使用番剧、漫画、广播剧、小说、设定集、台本等内容形态。字幕、转写、漫画、混合资料包等不作为第五、第六种顶层媒体类型，而应通过内容形态、提取单元、派生材料和证据 metadata 表达。
- 每个里程碑只拆一个清晰边界，避免把 UI、数据模型、IO、API、迁移和多内容形态功能塞进同一阶段。
- 内部抽象必须服务当前可见复杂度，不能为了“以后也许需要”堆空接口。
- 番剧/视频适配应成为第一种被迁移到平级入口的内容形态，用它证明新边界能保持旧行为。
- 音频转写在 02 中先被明确为“可被引用的派生素材/文本上下文”，独立音频提取能力留给 03。
- 小说/设定文本、字幕/台本、图片/漫画、广播剧在 02 中只定义接入位置、数据契约和测试桩，不做完整产品能力。
- 02 的目标架构必须给路线 03 的新内容形态接入做好准备，并交付多媒体接入准备矩阵。该矩阵至少覆盖番剧、漫画、广播剧、小说、设定集、字幕/台本和混合资料包等表达层内容形态，并映射到 `video`、`image`、`audio`、`text` 四种代码层媒体类型，逐项说明提取单元、预算口径、模型能力、证据引用、预览入口、正式入口、知识库落点和失败反馈。
- 预算与模型配置要衔接路线 01 的预算设计：输入预算是真约束，输出预算是期望值。02 只拆配置语义和调用边界，不重新讨论预算产品设计。
- 长耗时任务继续放在线程 worker；页面只触发、显示进度和处理反馈。
- 所有新增用户可见文本必须进入四个 i18n JSON。

## 5. 当前结构复核摘要

### 5.1 素材处理与项目目录

当前项目树由 `utils.paths.ensure_project_tree()` 创建，标准目录包括 `raw/`、`materials/`、`cache/`、`knowledge_base/`、`output/` 和 `config.json`。

当前素材处理边界大致如下：

- `gui/pages/project_page.py` 负责素材列表、处理配置、启动素材处理 worker、清理 raw 和移除素材的 UI。
- `utils.material_processing_middleware.process_source_request()` 负责处理请求协调，先导入到 raw，再根据配置链接或转码到 materials。
- `utils.source_importer` 负责 raw/materials 的复制、链接、清理和移除等文件操作。
- `utils.source_status` 负责项目素材显示、处理状态、raw/materials 关系判断。
- `utils.media_types` 已声明 `VIDEO_SUFFIXES`、`IMAGE_SUFFIXES`、`TEXT_SUFFIXES` 和 `SUPPORTED_SOURCE_SUFFIXES`。

这说明素材输入并非完全只认识视频，但正式 Extract Once 主链路还没有把这些类型当作平级提取对象。

### 5.2 扫描与 manifest

当前扫描存在两条重要路径：

- `scan_source_directory(source_root)` 能按文件夹扫描季/集结构，但只是较通用的旧入口。
- `scan_formal_video_materials(project_id)` 从 `materials/` 生成正式视频扫描结果，`scan_type` 是 `formal_video`，`source_kind` 是 `video`。

正式视频扫描还包含以下视频语义：

- 根目录视频文件会变成 episode。
- episode 目录中的 `segment_` 视频或 `transcoded` 视频会变成 chunks。
- `collect_preview_video_chunks()` 只收集视频后缀文件。
- `preview_chunk_identity()` 根据视频文件相对路径推导预览季、集和 chunk。

这些逻辑可以继续存在，但需要被降级为“视频素材扫描适配器”的内部实现，而不是 Extract Once 的通用扫描模型。

### 5.3 提取入口

`core/extractor.py` 当前承担大量职责：

- source scan 和 manifest 初始化。
- preview chunk 搜索、模型调用、预览结果写入。
- formal video extraction plan 准备。
- formal/clean/fast chunk 提取。
- episode/season content 和 summary 聚合。
- 音频转写生成和 transcript 上下文拼接。
- token 使用量、进度、洞察流事件、warning 发射。

其中正式提取入口 `run_full_extraction_streaming()` 仍调用 `prepare_formal_video_extraction_plan()` 和 `_collect_formal_video_chunk_inputs()`。这会让后续文本、字幕、图片、漫画接入时不得不继续伪装成视频 chunk，或者在 `Extractor` 中叠加更多分支。

### 5.4 模型与预算

云端模型预设当前仍以视频配置为主：

- `CloudModelPreset.video_input_mode` 决定原生视频、抽帧、抽帧加转写或纯转写模式。
- `video_fps` 控制视频帧采样。
- `max_output_tokens` 当前语义是视频每分钟输出期望，并通过 `scale_cloud_max_output_tokens_for_video_duration()` 按视频时长缩放。
- 文本、图片、音频测试也复用同一个 `max_output_tokens` 字段。

路线 01 已经讨论过要把输入预算和输出期望分开表达。路线 02 不重新设计产品交互，但必须在结构上避免继续把所有素材的预算都命名和处理成“视频每分钟”。

### 5.5 音频转写

`utils.audio_transcription.transcribe_episode_audio()` 支持从视频或音频素材生成 `EpisodeTranscript`，并写入 `episode_transcript.json`。

当前正式视频提取中：

- `frame_sampling_with_transcript` 和 `audio_transcript_only` 会触发 episode transcript 生成。
- `transcript_segments_for_material()` 会按 material path 或时间范围提取 chunk 上下文。
- 若转写必需但不可用，正式提取会 warning 或中止。

这条链路证明音频/文本上下文已存在，但它仍附着在视频 chunk 提取上。02 需要把 transcript 的角色定义清楚：它可以是视频素材的派生上下文，也可以在 03 中升级为独立文本类素材入口。

### 5.6 知识库与结构化产物

当前知识库路径集中在 `core/knowledge_base.py`：

- `source_manifest.json`
- `seasons/{season_id}/episodes/{episode_id}/chunks/{chunk_id}.json`
- `episode_content.json`
- `episode_summary.json`
- `season_content.json`
- `season_summary.json`
- `episode_transcript.json`

`core/models.py` 中的 `ExtractionStructuredArtifact` 已有 `source_kind`、`source_counts`、`context_policy`、`token_usage`、`requested_output_tokens` 等字段。`ChunkExtractionResult` 也有 `source_path` 和 `source_kind`。

因此 02 应优先统一这些已有字段的含义，而不是重新发明一套独立知识库格式。

## 6. 主要耦合清单

### 6.1 命名耦合

- `scan_formal_video_materials`
- `collect_preview_video_chunks`
- `prepare_formal_video_extraction_plan`
- `_collect_formal_video_chunk_inputs`
- `_build_formal_video_chunk_request`
- `current_cloud_video_preset`
- `_video_max_output_tokens`
- `video_input_mode`

这些名称有些可以在 02 执行中保留为视频适配器内部函数，有些需要新增通用入口包住旧名称。重命名本身不是目标，目标是让通用层不再依赖视频命名。

### 6.2 数据耦合

- `source_manifest.json` 顶层 `source_kind` 目前等于 `video`。
- episode 和 chunk 条目中 `source_kind` 也主要是 `video`。
- chunk 输入默认有 `video_path`，后续非视频素材缺少平级字段。
- `source_counts` 统计键名多为 `chunks`、`episodes`、`video` 语境。
- transcript 当前用 `material_paths` 反查视频 chunk，上下文身份依赖文件路径匹配。

02 需要定义兼容型字段，而不是一次性迁移所有旧 JSON。

### 6.3 控制流耦合

- 正式提取从视频扫描开始，导致后续素材只能插入视频扫描之后。
- 模型后端选择由 `video_input_mode` 推导，不适合图片、文本、音频独立入口。
- 预算缩放在 chunk 提取附近计算，缺少按媒体类型分派的统一接口。
- transcript 生成是视频输入模式的副作用，而不是独立素材准备阶段。

### 6.4 模块边界耦合

- `Extractor` 同时承担编排、扫描、请求构建、聚合和进度事件。
- GUI 仍直接拿“云端视频预设”触发预览和正式提取。
- `model_page` 中测试能力覆盖文本/图片/音频/视频，但保存的预设仍偏视频命名。
- 素材导入处理已经集中在 `utils`，但后续如果新增素材扫描逻辑，容易被直接塞回页面或 `Extractor`。

### 6.5 认知耦合

- “chunk” 当前几乎等同于视频片段。
- “episode” 当前主要由视频文件或视频目录推导。
- “输出 token/分钟” 容易被误读成所有素材通用预算。
- “音频转写”容易被误认为已经等价于音频素材提取。

02 文档和执行验收需要明确这些词的边界，降低后续误接。

## 7. 目标架构

### 7.1 总体流向

目标流向保持 Extract Once 主线不变：

1. UI 收集项目、素材路径和处理配置。
2. `utils.source_importer` / `utils.material_processing_middleware` 准备 `raw/` 与 `materials/`。
3. `core` 扫描 `materials/`，生成素材清单和提取运行计划。
4. `core` 按媒体类型选择内部处理器，构建模型请求或本地派生结果。
5. 所有模型请求通过 `utils.ai_model_middleware`。
6. `core.knowledge_base` 写入 chunk、episode、season、transcript 等结构化产物。
7. GUI 和洞察流只展示状态、警告、进度与结构化事件。
8. 角色卡编译继续读取正式知识库产物，不回头分析原始素材。

### 7.2 平级素材词汇

建议在 02 中固化以下内部词汇。名称可在执行时根据代码风格微调，但语义应保持稳定。

| 概念 | 含义 | 约束 |
| --- | --- | --- |
| MediaType | 代码层媒体类型，只允许 `video`、`image`、`audio`、`text` | 用于扫描、预算、模型能力和知识库 metadata；不得把 `manga`、`subtitle`、`transcript`、`mixed` 做成平行顶层媒体类型 |
| ContentForm | 产品和用户表达层的内容形态，如番剧、漫画、广播剧、小说、设定集、台本 | 用于 UI 文案、导入说明、项目素材展示和用户理解；不直接决定模型后端 |
| MaterialRef | 指向 `materials/` 中一个原始或处理后素材的稳定引用 | 应优先使用相对路径，避免写死绝对路径 |
| ExtractionUnit | 一次可被提取的最小工作单元 | 番剧通常映射为 video chunk；漫画页映射为 image unit；广播剧片段映射为 audio unit 或派生 text transcript；小说章节映射为 text unit |
| EpisodePlan | 一个 episode 内待处理的 ExtractionUnit 集合 | 继续兼容现有季/集结构 |
| ExtractionRunPlan | 一次提取运行的计划、预算、上下文和阶段状态 | 已有模型应扩展或收敛，不另起重复事实源 |
| EvidenceRef | 结构化结论可追溯的素材位置引用 | 后续角色卡证据与质量评估复用 |
| DerivedMaterial | 从媒体素材生成的中间材料，如 transcript、抽帧、OCR 文本 | 不能无条件等同于正式提取结果；transcript 是 audio/video 派生出的 text 证据，不是顶层媒体类型 |

### 7.3 通用 manifest 方向

`source_manifest.json` 应保留现有 season/episode/chunk 结构，同时增加兼容型通用字段。

建议方向：

```json
{
  "schema_version": 2,
  "scan_type": "formal_materials",
  "media_types": ["video"],
  "content_forms": ["anime_series"],
  "source_root": ".../materials",
  "seasons": [
    {
      "season_id": "season_001",
      "source_path": ".",
      "episodes": [
        {
          "episode_id": "episode_001",
          "media_types": ["video"],
          "content_forms": ["anime_series"],
          "source_path": "episode_001",
          "units": [
            {
              "unit_id": "chunk_0001",
              "unit_kind": "video_chunk",
              "media_type": "video",
              "content_form": "anime_series",
              "source_path": "episode_001/segment_001.mp4"
            }
          ],
          "chunks": []
        }
      ]
    }
  ]
}
```

兼容要求：

- 旧 manifest 没有 `schema_version` 或 `media_types` 时，按当前视频 manifest 读取。
- 02 执行时可以先让 `chunks` 和 `units` 共存；后续确认稳定后再减少重复字段。
- `chunks` 不能突然删除，否则会影响已有知识库初始化和正式提取。
- 所有新增字段必须有默认值或读取降级逻辑。
- 如果执行中发现 schema v2 成本过高，可先实现内存态 `ExtractionUnit`，暂缓持久化 schema 调整，但必须在文档中说明偏差。

### 7.4 通用提取计划

`ExtractionRunPlan` 已存在，应优先扩展或用 helper 转换，不新增另一个平行运行计划模型。

目标能力：

- 记录本次运行包含哪些 `MediaType`，以及面向用户展示的 `ContentForm`。
- 记录每个 episode / unit 的素材引用、派生材料和预算策略。
- 把输入预算、输出期望、上下文窗口、模型能力选择和 fallback 记录到运行计划或 stage state。
- 区分 preview、full、clean、fast 的运行语义。
- 能从旧视频 manifest 构建等价计划。

### 7.5 素材处理器边界

不在 02 中建设大型插件系统。建议采用轻量内部分派：

- 通用层只认识 `ExtractionUnit`、`MediaType`、预算、上下文、产物模型；内容形态只作为 UI 和 metadata 解释层。
- 视频处理器包住现有视频 chunk 请求构建、时长探测、输入模式、转写上下文逻辑。
- 小说/设定文本、字幕/台本、图片/漫画、广播剧处理器在 02 中最多保留接口或测试桩，不做正式 UI 开关；它们在代码层仍分别映射到 `text`、`image`、`audio` 等媒体类型。
- 分派表可以是模块内常量或简单函数，不引入全局 registry、动态发现或插件目录。

### 7.6 知识库兼容策略

02 不能破坏角色卡编译读取正式知识库的现有路径。

目标：

- chunk JSON、episode content、episode summary、season content、season summary 继续写入当前路径。
- 新增字段应优先写入 `source_kind`、`source_counts`、`context_policy`、`model_metadata`、`token_usage`、`requested_output_tokens` 等已有结构。
- 对非视频素材的未来结果，优先复用 `ChunkExtractionResult` 的结构语义，必要时再扩展字段，而不是新增完全不同的产物。
- `episode_transcript.json` 继续作为 transcript 派生产物保存；它是否参与正式提取由运行计划明确记录。
- 预览产物继续使用 `preview__` 前缀和 preview stage 标记。

### 7.7 架构图审核闸门

执行路线 02 时，M01 和 M02 必须先产出两张可审查的 Mermaid 图或等价结构图：

- 当前真实结构图：描述执行前代码中的主要模块、关键文件、依赖方向、素材处理流、预览/正式提取流、知识库写入流和模型调用入口。图中不得把尚未实现的目标结构画成现状。
- 目标重构结构图：描述预计完成路线 02 后的模块边界、通用扫描入口、提取运行计划、素材处理器、视频适配边界、transcript 派生素材边界、GUI/worker/core/utils 依赖方向和知识库写入关系。

图旁必须配短说明：

- 每个节点对应的真实目录、文件、类、函数或计划新增模块。
- 主要依赖方向，以及哪些依赖方向是必须修正的。
- 哪些边界会在 02 中落地，哪些只作为路线 03 接入口保留。
- 当前结构图与目标结构图之间的差异清单。
- 用户审核结论和需要修改的点。

用户未明确确认“结构图合格，可以开始重构”前，只允许继续补充分析、调整图和更新计划，不允许修改业务代码。

### 7.8 路线 03 接入准备矩阵

路线 02 的重构目标不能只解决视频拆耦，还必须让路线 03 接入番剧、漫画、广播剧、小说等内容形态时不用再次移动主架构。

执行 M02 和 M15 时必须维护一张多媒体接入准备矩阵：

| 内容形态表达 | 代码层媒体类型 | 02 必须准备的架构位置 | 不在 02 中实现的内容 |
| --- | --- | --- | --- |
| 番剧/动画 | `video`，可派生 `audio`/`text` | video unit、视频 evidence、视频预算、字幕/transcript 派生关系 | 新的番剧业务能力本身，仍保持既有视频链路 |
| 漫画/图集 | `image` | image unit、页码/序号 evidence、image backend 分派、图片预算占位 | 漫画页理解、OCR 或跨页聚合 |
| 广播剧/音频节目 | `audio`，可派生 `text` transcript | audio unit、时间段 evidence、audio backend 能力判断、转写派生关系 | 原生音频正式提取请求和音频知识库提取 |
| 小说/设定集/台本 | `text` | text unit、章节/段落 evidence、text backend 分派、文本预算占位 | 文本正式提取 prompt 和完整 GUI 能力 |
| 字幕/歌词/台词稿 | `text`，可关联 `video`/`audio` | 时间轴 evidence、text unit、与 episode 对齐的 metadata | 字幕解析细节和说话人推断 |
| 混合资料包 | `video`/`image`/`audio`/`text` 组合 | 单 episode 多 media types、多个 evidence refs、冲突/重复事实合并占位 | 混合媒体正式聚合策略 |

矩阵中每一行都要说明：

- 当前代码中对应的真实落点或计划新增模块。
- 是否已经能由通用扫描和运行计划表达。
- 对应预算口径来自哪里，是否需要路线 03 再确认。
- 对应模型能力如何判断，模型不支持时如何反馈。
- 预览和正式提取分别会走哪个入口。
- 知识库产物应写入哪里，证据如何追溯。
- 面向用户展示时使用哪种内容形态说法，避免把 `video/image/audio/text` 直接变成主要产品文案。

如果某类内容形态在 02 结束时无法映射到四种代码层媒体类型之一，必须在 02 收尾报告中列为路线 03 前置阻塞，而不是留给 03 临时绕开。

## 8. 模块边界

### 8.1 core

`core` 负责业务模型、扫描结果、提取计划、素材单元、上下文组装、提取编排、知识库产物和聚合。

允许：

- 在 `core/models.py` 增加平级素材所需的 Pydantic 模型或枚举。
- 在 `core/source_scanner.py` 增加通用扫描入口，并保留视频扫描作为内部实现。
- 在 `core/extractor.py` 中拆分计划构建、执行、请求构建和结果聚合。
- 增加小型 core 模块承载清晰职责，例如 `core/material_plan.py` 或 `core/extraction_units.py`。

不允许：

- 在 core 中直接复制、删除、移动用户素材。
- 在 core 中绕过 `utils.ai_model_middleware` 直接访问模型。
- 在 core 中做 GUI 组件或 qfluentwidgets 交互。
- 为未实现内容形态堆大而空的抽象层。

### 8.2 utils

`utils` 负责跨模块工具、路径、导入处理、模型中间件、转写、后端能力和全局配置。

允许：

- 扩展 `utils.media_types` 的后缀和类型判断工具。
- 在 `utils.material_processing_middleware` 保持素材处理请求协调。
- 在 `utils.audio_transcription` 暴露更清晰的 transcript 派生材料接口。
- 在 `utils.cloud_model_presets` 中为路线 01 的预算语义迁移提供兼容函数。

不允许：

- 让 `utils` 持有业务流程总编排。
- 让素材处理工具直接写正式提取 JSON。
- 在 `utils` 中硬编码 UI 文案。

### 8.3 gui

GUI 负责用户交互、配置收集、worker 启动、进度展示和反馈。

允许：

- 把“云端视频预设”的 UI 提供函数逐步改名或包裹成“当前提取预设”。
- 根据通用运行计划展示内容形态、媒体类型、处理状态和 warning。
- 在必要时新增 i18n 文案说明预算语义或素材能力限制。

不允许：

- 页面层直接拼接知识库路径。
- 页面层直接构建模型请求。
- 页面层直接推导正式提取的季/集/chunk 结构。
- 页面层为了支持新素材直接复制、删除或重命名项目素材。

### 8.4 workers

workers 只桥接 Qt Signal 与 core/utils 调用。

允许：

- 传递 `ProjectConfig`、模型预设、并发度、取消信号和回调。
- 接收并转发 token usage、progress、InsightEvent。

不允许：

- 在 worker 内实现素材扫描规则。
- 在 worker 内实现提取模型调用细节。
- 在 worker 内写知识库 JSON。

## 9. 数据与兼容规则

- 旧项目不需要一次性迁移。执行路线 02 后，旧项目应仍能打开、预览和正式提取视频素材。
- `raw/` 中可重新处理的源副本和 `materials/` 中当前处理管线消费素材的语义不变。
- 清理 `raw/` 的安全规则不变：清理前必须确认 `materials/` 中已有可用素材，并把清理状态写回项目配置。
- 新增 manifest 字段时必须兼容旧字段读取；必要时给读取函数添加 normalize 层。
- 新增模型字段必须保持默认值，避免旧 JSON 校验失败。
- 如果新增 `schema_version`，只能用于渐进读取和写入分支，不能让旧数据直接不可读。
- 所有路径在持久化 metadata 中优先保存相对 `materials/` 或知识库根目录的路径。
- 运行日志和洞察流不输出 API Key、完整密钥、隐私文本或大型原始素材内容。
- 非视频素材后续进入正式提取时，必须明确证据引用规则，不允许产物只写“来自混合素材”这种不可追溯描述。

## 10. 里程碑

### M01：执行前复核与基线冻结

目标：确认执行 02 时的真实代码状态和路线 01 完成情况。

范围：

- 重新读取 `README.md`、根 `ARCHITECTURE.md`、`core/ARCHITECTURE.md`、`utils/ARCHITECTURE.md`、`gui/ARCHITECTURE.md`。
- 重新检查 `core/source_scanner.py`、`core/extractor.py`、`core/knowledge_base.py`、`core/models.py`。
- 重新检查 `utils/material_processing_middleware.py`、`utils/source_importer.py`、`utils/audio_transcription.py`、`utils/cloud_model_presets.py`。
- 重新检查 `gui/main_window.py`、`gui/pages/project_page.py`、`gui/pages/model_page.py`。
- 确认路线 01 已落地、部分落地或仅完成文档。

交付物：

- 02 执行前现状记录。
- 当前真实结构图初稿，至少覆盖模块结构、依赖方向、素材处理流、提取流、知识库写入和模型调用入口。
- 本计划中需要调整的偏差列表。
- 一个可以回归的视频项目样本说明。

验收：

- 能明确回答“当前正式提取入口是否仍是 video plan”。
- 能明确回答“路线 01 的预算、拒绝样例、观测性设计哪些已经是代码事实”。
- 当前结构图中的节点能对应真实目录、文件、类、函数或功能模块，且没有把目标结构画成现状。
- 没有基于旧计划误判当前代码事实。

### M02：耦合地图与重构边界确认

目标：把视频耦合点分成必须拆、可以包裹、暂不处理三类。

范围：

- 命名耦合：函数、类、变量、i18n key、日志字段。
- 数据耦合：manifest、chunk 输入、结构化产物、token usage。
- 控制流耦合：preview、full、clean、fast、transcript side effect。
- 模块耦合：GUI、worker、core、utils、knowledge_base。

交付物：

- 一份执行用耦合清单，可直接映射到后续 commit。
- 每个耦合点标注风险、预期处理方式和是否影响用户可见行为。
- 目标重构结构图，至少覆盖通用扫描入口、提取计划层、视频素材处理器、transcript 派生素材边界、GUI/worker/core/utils 依赖方向和知识库写入关系。
- 当前结构图与目标结构图的差异清单。
- 用户审核记录：通过、需要修改或暂不允许执行重构。

验收：

- 后续里程碑不再临时扩大到未列出的高风险耦合点。
- 如果发现必须新增里程碑，先补到计划或阶段记录中。
- 用户明确确认结构图合格前，不得进入 M03 及后续代码重构。

### M03：媒体类型、内容形态与提取单元模型

目标：建立最小可用的平级媒体内部契约，并保留面向用户的内容形态解释层。

范围：

- 在 `core/models.py` 或新的小型 core 模块中定义 `MediaType`、`ContentForm`、素材引用、提取单元、派生素材和证据引用的模型。
- 优先使用字符串兼容或轻量枚举，避免对旧 JSON 造成破坏。
- 为视频 chunk 建立从旧 chunk entry 到新 `ExtractionUnit` 的转换。

不做：

- 不实现小说、图片、漫画、广播剧的真实提取。
- 不要求旧知识库立刻写新 schema。

验收：

- 视频 manifest 能转换为等价提取单元列表。
- 新模型字段有默认值或兼容读取路径。
- 模型名称表达媒体类型与内容形态语义，不把 `video_path` 当作通用字段。

### M04：扫描层通用入口

目标：让正式提取先调用通用扫描入口，再由视频扫描实现当前行为。

范围：

- 新增通用扫描函数，例如 `scan_formal_materials(project_id)`。
- `scan_formal_video_materials(project_id)` 保留为视频实现或兼容 wrapper。
- 预览扫描可以先新增通用入口，例如 `collect_preview_material_units(project_id, limit=...)`，内部仍只返回视频单元。
- 旧调用路径保持可用，避免一次性破坏外部引用。

验收：

- 当前视频 materials 生成的 season/episode/chunk 结构与重构前等价。
- 预览仍最多处理当前规定的视频 chunk 数量。
- 无素材时的 warning 行为不改变。

### M05：manifest normalize 与兼容读取

目标：将旧视频 manifest 和未来通用 manifest 的读取逻辑集中。

范围：

- 增加 normalize helper，将旧 `formal_video` manifest 转成内存中的通用结构。
- 保留 `chunks` 字段读取。
- 允许写入兼容字段，如 `schema_version`、`media_types`、`content_forms`、`units`，但不能让旧流程必须依赖新字段。
- 明确 `source_kind`、`media_type`、`content_form`、`unit_kind` 的关系。

验收：

- 旧 `source_manifest.json` 可读取。
- 新写入 manifest 可被现有知识库初始化使用。
- `core.knowledge_base.initialize_structure()` 不需要理解复杂素材细节，只依赖 season/episode 基本结构。

### M06：提取计划构建层

目标：把“扫描结果转运行计划”从正式提取执行中拆出来。

范围：

- 收敛 `ExtractionRunPlan` 的创建逻辑。
- 将 mode、run id、stage、budget plan、source manifest、season/episode refs、media types 和 content forms 放入计划。
- 让 full、clean、fast 共享同一计划构建入口。
- 保持现有 manifest metadata 写入。

验收：

- `run_full_extraction_streaming()` 不再直接假定只有视频扫描入口。
- clean/fast 模式仍能拿到和旧逻辑等价的 chunk inputs。
- 运行计划能在日志或调试记录中解释本次处理了哪些代码层媒体类型，以及向用户展示哪些内容形态。

### M07：视频素材处理器内聚

目标：把视频特有逻辑收束到视频处理器或视频请求构建模块。

范围：

- 视频输入模式、视频 FPS、视频时长探测、视频预算缩放、视频 content part 构造。
- transcript 作为视频模式可选上下文的逻辑。
- `call_video_model` 调用仍通过 `utils.ai_model_middleware`。

不做：

- 不改变模型 prompt 的核心输出结构。
- 不改变正式提取 prompt 的目标角色策略。

验收：

- 原生视频、抽帧、抽帧加转写、纯转写模式仍按旧规则选择后端。
- 视频 chunk 的 `source_kind` 仍为 `video`。
- token usage 聚合和 progress 仍能正确回传。

### M08：音频转写派生素材边界

目标：把 transcript 从“视频模式副作用”整理成清晰的派生素材能力。

范围：

- 明确 `EpisodeTranscript` 与 `ExtractionUnit` 的关系。
- 把 transcript 是否必需、是否可用、对应素材路径、截取策略写入运行计划或上下文策略。
- 保留 `episode_transcript.json` 路径和结构。
- 如果只重构命名和 helper，不新增 UI 能力。

验收：

- `audio_transcript_only` 和 `frame_sampling_with_transcript` 行为不回退。
- 转写失败的 warning 和中止规则不变。
- 后续路线 03 能基于该边界把 transcript 作为文本类素材输入，而不需要反向依赖视频 chunk。

### M09：预算与模型能力分派边界

目标：让预算和模型能力选择按媒体类型进入统一接口。

范围：

- 保留路线 01 确认的语义：输入预算是硬约束，输出 token 是软性期望。
- 当前视频每分钟输出期望继续用于视频素材。
- 把通用提取层从“视频每分钟”命名中解脱出来。
- 为文本、图片、音频等未来预算入口预留字段或转换函数，但不做完整 UI。

验收：

- 现有云端模型预设能继续保存和读取。
- 视频测试、预览和正式提取的输出期望计算不改变。
- 新的通用接口不会让非视频素材误用视频分钟预算。

### M10：知识库写入 metadata 统一

目标：统一结构化产物中的素材来源和统计字段。

范围：

- 明确 `source_kind` 在旧字段中的兼容含义。
- 建议新增或规范 `media_type`、`content_form`、`source_counts`、`context_policy`、`requested_output_tokens` 的写入策略。
- 保持 chunk、episode、season JSON 路径不变。
- 对 preview artifact 和 full artifact 的区分不变。

验收：

- 视频正式提取生成的 chunk/episode/season 产物仍可被角色卡编译读取。
- `source_counts` 不再只出现含糊视频统计，至少能说明当前处理的是视频单元。
- 旧 JSON 读取不报错。

### M11：Extractor 职责瘦身

目标：降低 `core/extractor.py` 的职责密度，但不做大规模重写。

范围：

- 把纯 helper 或可独立测试的计划构建、素材单元转换、预算计算、请求构建迁出到小模块或私有 helper。
- 保留 `Extractor` 作为 GUI-facing 入口，避免全项目调用同时变化。
- 每次迁移都必须有视频回归。

不做：

- 不把 `Extractor` 改成巨大的 `Manager` 套 `Registry`。
- 不一次性迁移所有私有方法。

验收：

- `Extractor.run_preview_streaming()` 和 `Extractor.run_full_extraction_streaming()` 仍是主窗口可调用入口。
- 迁出的 helper 可以独立阅读和测试。
- 文件职责更清晰，而不是只是移动代码。

### M12：GUI 触发语义收敛

目标：让 UI 触发“提取预设”而不是强绑定“视频预设”，但不改变当前页面能力。

范围：

- 检查 `current_cloud_video_preset` 是否需要新增通用 wrapper。
- 保留模型页面现有视频模式设置。
- 如需改文案，四个 i18n JSON 同步。
- 主窗口、项目页、worker 只传配置和预设，不参与素材分派。

验收：

- 预览、正式提取按钮行为不变。
- 低输出期望弹窗仍按现有规则出现。
- UI 不出现承诺“已支持图片/漫画正式提取”的文案。

### M13：进度、洞察流和日志通用化

目标：让事件表达从“视频 chunk”逐步扩展为“素材单元”，同时不丢失现有用户理解。

范围：

- 检查 `InsightEvent` 标题、description、meta 是否有视频硬编码。
- 规划通用 meta，如 `media_type`、`content_form`、`unit_id`、`source_path`、`stage`。
- 日志继续使用标准 logger，不把调试日志塞进洞察流。

验收：

- 视频用户仍能看懂当前处理到第几段/第几集。
- 后续非视频素材可以复用进度结构。
- 不输出大型原始文本、隐私内容或密钥。

### M14：自动化回归与轻量测试补齐

目标：为行为保持型重构提供最低限度保护。

范围：

- 如仓库测试基础仍不足，优先补小型离线测试或脚本级验证。
- 覆盖 manifest normalize、视频 scan 等价性、提取单元转换、预算接口兼容。
- 避免真实云端模型调用作为默认测试。

建议验证：

```powershell
conda run -n CharaPicker python -m ruff check .
```

如果 Ruff 未安装或仓库仍无测试命令，需要在阶段报告中说明。

验收：

- 至少有一组不依赖云端模型的结构验证。
- 视频回归路径可手动复现。
- 没有把测试素材或用户项目数据提交进仓库。

### M15：文档、架构说明与路线 03 交接

目标：把 02 的新边界沉淀到普通项目文档，不依赖 `.codex/`。

范围：

- 更新相关 `ARCHITECTURE.md`，说明通用扫描/运行计划/素材处理器边界。
- 更新 `docs/plans/TODO.zh_CN.md` 或后续 03 文档，列出可直接接入的媒体类型入口和对应内容形态。
- 交付多媒体接入准备矩阵，逐项说明番剧、漫画、广播剧、小说、设定集、字幕/台本和混合资料包等内容形态是否已经能映射到 `video`、`image`、`audio`、`text` 四种代码层媒体类型，并具备路线 03 接入条件。
- 如果长期规则稳定，建议用户是否要更新 `AGENTS.md`，但不能擅自修改。

验收：

- 后续执行 03 的 agent 能从普通文档理解新边界。
- 02 的偏差、未完成项和路线 03 输入条件清晰。
- 不把一次性临时 TODO 写入长期指导文件。

### M16：阶段验收与回滚预案

目标：确认 02 已经完成“解耦准备”，可以进入 03。

验收清单：

- 当前真实结构图和目标重构结构图已经生成，并由用户审核确认可以开始重构。
- 现有视频预览可运行。
- 现有正式视频 full/clean/fast 至少路径级可验证，真实模型验证按可用密钥决定。
- 音频转写辅助模式未破坏。
- 角色卡编译能继续读取正式知识库。
- 旧项目配置和旧知识库 JSON 可读取。
- 新增抽象都有当前用途，没有空 registry、空 manager 或未使用大接口。
- 文档和代码边界一致。

回滚策略：

- 每个里程碑独立提交。
- 数据 schema 相关改动必须能通过兼容读取撤回。
- 若某个抽象无法证明收益，优先回滚该抽象并保留更小的 helper。
- 若真实模型回归不可用，必须保留离线验证和手动验证步骤，不能假装已完成端到端验证。

## 11. 推荐提交分组

- `docs: finalize multi-material refactor plan`
  - 完成 02 计划文档，更新索引和路线链接。
- `docs: record multi-material refactor diagrams`
  - 执行 02 前记录当前真实结构图、目标重构结构图、差异清单和用户审核结论。
- `refactor: introduce material extraction contracts`
  - 新增媒体类型、内容形态、素材引用、提取单元、证据引用等最小模型。
- `refactor: add generic material scan planning`
  - 增加通用扫描入口和 manifest normalize，视频扫描保持兼容。
- `refactor: build extraction plans from material units`
  - 收敛 full/clean/fast 的运行计划构建。
- `refactor: isolate video extraction handling`
  - 把视频请求、视频预算、视频输入模式和 transcript 上下文收束到视频处理边界。
- `refactor: normalize extraction artifact metadata`
  - 统一 source/material metadata 和 source_counts 写入。
- `refactor: simplify extraction UI handoff`
  - 让 GUI/worker 只传递通用提取配置和预设，不承载素材分派。
- `test: cover material scan compatibility`
  - 增加离线验证或测试，覆盖旧视频路径和 manifest 兼容。
- `docs: document material extraction boundaries`
  - 更新架构文档和路线 03 交接说明。

提交要求：

- 用户要求提交时使用 Conventional Commits。
- 本仓库提交使用 `git commit -s` 签名。
- 不把 `projects/`、`config.yaml`、`log/`、`bin/`、`models/` 的本地运行数据作为普通源码提交。

## 12. 验证策略

### 12.1 静态验证

- Ruff 可用时运行 `python -m ruff check .` 或 `conda run -n CharaPicker python -m ruff check .`。
- 检查新增模型是否有类型注解和默认值。
- 检查 GUI 可见文案是否进入四个 i18n JSON。
- 检查没有新增依赖或未记录依赖。

### 12.2 离线结构验证

应优先覆盖：

- 视频 materials 扫描前后结构等价。
- 旧 manifest normalize 不丢 season/episode/chunk。
- 新 `ExtractionUnit` 能表达旧视频 chunk。
- 预算接口不会把文本/图片误按视频分钟计算。
- `EpisodeTranscript` 仍能被视频 chunk 上下文引用。

### 12.3 手动视频回归

至少检查：

- 新建项目，导入视频素材。
- 原始素材模式处理到 `materials/`。
- 预览提取能处理前两个视频 chunk，仍忽略已有 preview chunk JSON。
- 正式 full 提取能写入 chunk、episode、season 结构。
- clean 模式和 fast 模式路径不因计划构建重构而断裂。
- 角色卡页面能读取正式知识库并继续编译。

真实模型调用是否执行取决于当时密钥、网络和费用条件。不能调用真实模型时，阶段报告必须明确说明。

### 12.4 音频转写回归

至少检查：

- `frame_sampling_with_transcript` 或 `audio_transcript_only` 仍能触发 episode transcript 准备。
- `episode_transcript.json` 路径和结构不变。
- transcript 缺失或失败时 warning 和中止规则不变。
- 不把 transcript 缓存误写成正式角色结论。

## 13. 风险与缓解

| 风险 | 表现 | 缓解 |
| --- | --- | --- |
| 抽象过早 | 出现大量未使用接口、registry、manager | 先用视频迁移证明收益，未使用抽象不合并 |
| 破坏旧视频链路 | 预览或正式提取行为变化 | 每个里程碑都跑视频回归 |
| schema 破坏旧项目 | 旧 manifest 或旧 chunk JSON 读取失败 | 新字段默认值、normalize helper、兼容读取 |
| GUI 越界 | 页面直接拼路径或调模型 | code review 中按模块边界检查 |
| 预算语义混乱 | 非视频内容形态继续使用“每分钟” | 通用层只接受按代码层媒体类型解析后的预算 |
| transcript 定位不清 | 音频既像辅助上下文又像独立素材 | 02 明确派生素材边界，03 再做独立能力 |
| 执行范围膨胀 | 02 顺手实现图片/漫画 | 任何新素材正式提取能力都移入 03 |
| 验证不足 | 只改结构但没证明行为保持 | 增加离线结构测试和手动视频回归记录 |

## 14. 执行时不健全事项

以下事项不是当前需要用户立刻拍板的问题，但执行 02 时必须复核并在阶段报告中记录。

- 路线 01 是否已经实际落地。如果只是完成计划文档，02 不能引用其实现作为代码事实。
- `CloudModelPreset.max_output_tokens` 的兼容迁移方式。当前字段还承担多个测试场景的输出期望，执行 02 时需要避免直接破坏保存配置。
- 通用 manifest 是否在 02 持久化。若风险过高，可以先只做内存态 normalize，再把持久化 schema 留给 03 或单独阶段。
- `ChunkExtractionResult` 是否足够表达图片、文本、漫画等内容形态的未来最小单元。02 只能给出兼容方向，不宜一次性扩展到所有领域字段。
- 字幕/歌词/台词稿统一归入 `text` 媒体类型，但需要保留时间轴、字幕行号和可关联 `video`/`audio` 的 evidence。03 再决定首批支持 `.srt`、`.ass`、`.vtt` 的范围。
- 漫画/图集统一归入 `image` 媒体类型，但需要通过 `ContentForm`、页码、页组和目录排序表达漫画语义。真实 OCR/视觉策略留给 03。
- 混合资料包不是独立媒体类型。02 只要求 manifest 和运行计划能表达一个 episode 中多个 media types、content forms 和 evidence refs。
- 预览正式边界。正式提取是否忽略预览产物仍未完全定案，02 不应悄悄改变。

## 15. 代码审查自检表

执行 02 的每个 PR 或阶段提交前，至少自查：

- 是否已经生成当前真实结构图和目标重构结构图，并取得用户审核通过。
- 是否在用户审核结构图前开始了业务代码重构；如果是，必须停止并回退到分析/计划阶段。
- 是否保持现有视频预览和正式提取行为。
- 是否有新依赖。
- 是否有页面层直接拼接知识库路径。
- 是否有页面层或 worker 直接构建模型请求。
- 是否有绕过 `utils.ai_model_middleware` 的模型调用。
- 是否有把预览产物当正式知识库事实的行为。
- 是否有把 `ProjectConfig.target_characters` 重新用于新链路。
- 是否有用户可见文案未同步四个 i18n JSON。
- 是否有新字段缺少默认值导致旧 JSON 读取失败。
- 是否有未使用的大型抽象或空 registry。
- 是否把本地用户数据、日志、模型权重或二进制提交进仓库。
- 是否更新了受影响的普通项目文档。

## 16. 路线 03 交接条件

只有满足以下条件，才建议进入多内容形态覆盖计划：

- 视频链路已经通过通用扫描/运行计划或等价边界运行。
- 新旧 manifest 兼容策略明确。
- 媒体类型、内容形态、提取单元、派生素材、证据引用的内部契约稳定。
- 预算接口不再强迫非视频内容形态使用视频每分钟语义。
- transcript 已有明确派生素材边界。
- 多媒体接入准备矩阵已经覆盖番剧、漫画、广播剧、小说、设定集、字幕/台本和混合资料包等内容形态，并明确它们到 `video`、`image`、`audio`、`text` 四种媒体类型的映射、预览入口、正式入口、模型能力、预算口径、知识库落点和失败反馈。
- GUI/worker/core/utils 的责任没有因重构变得更混乱。
- 文档中列出路线 03 可以直接接入的入口和仍需实现的媒体处理器/内容形态适配器。

路线 03 的首要任务应是基于 02 边界补真实内容形态覆盖，而不是再次大规模移动架构。
