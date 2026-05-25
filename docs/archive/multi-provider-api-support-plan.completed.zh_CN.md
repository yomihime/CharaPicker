# 多供应商与多 API 规范接入计划完成记录

> 归档状态：本文档记录的多供应商 endpoint、API 规范、视频输入方式、DashScope 原生音频测试、Whisper 管理和音频转写首版已完成并归档。后续模型接入开发默认以当前代码、根目录 `README.md`、相关 `ARCHITECTURE.md`、`docs/README.md` 和 `docs/plans/TODO.zh_CN.md` 为准；如需引用本文档，必须先核对当前实现、官方文档和目标供应商的最新 API 说明。

## 1. 范围

本计划用于把云端模型配置从“少量固定供应商”扩展为“供应商、API 地址、API 规范、能力和视频输入方式可组合”的模型接入体系。

第一阶段目标是先接入可用的供应商和预设地址，参考 Chatbox 和 Everywhere 的成熟做法，但不直接照搬其代码结构。实现必须继续遵守 CharaPicker 当前边界：所有模型请求都通过 `utils.ai_model_middleware`，用户可见文案走 `i18n/`，云端模型预设继续由 `utils.cloud_model_presets` 和全局配置管理。

## 2. 非目标

- 不在第一阶段重写完整模型调用架构。
- 不在未验证前承诺所有供应商都支持图片、视频、音频、JSON mode 或流式输出。
- 不把抽帧图片模式描述成完整视频理解能力。
- 不绕过 `network_middleware` 和代理策略直接联网。
- 不把 API Key、完整请求体、完整模型响应或用户素材内容写入普通日志。
- 不新增依赖，除非后续音频转写或原生 API 方案明确证明必须新增。

## 3. 已确认决策

1. 优先选择“先接入”的路线：先让用户能选择更多供应商、地址和视频输入方式，再逐步抽象更多 API 规范。
2. 供应商和 API 地址分开。一个供应商可以提供多个可选 API 地址，由用户在下拉框中选择。
3. 阿里百炼供应商内置多区域 endpoint，默认选择 `cn`。
4. API 地址预设之外必须保留自定义 URL，避免预设不全时阻塞用户。
5. 视频输入方式独立于供应商和 API 地址。用户可以选择供应商原生视频 API，也可以选择 OpenAI-compatible 抽帧模式。
6. 抽帧成图片时默认没有音频信息。需要声音、对白、旁白或背景音时，必须显式启用音频转写，或使用确认支持视频内音频的供应商原生接口。
7. 第一版 UI 可以使用“自动，推荐”作为视频处理方式默认值。阿里百炼自动优先走 DashScope 原生视频；OpenAI-compatible 自动走抽帧。
8. 参考 Chatbox 和 Everywhere 的方向：保留 provider settings / endpoint presets / schema routing / endpoint normalization 的分层思想，但按 CharaPicker 当前 Python/PyQt 架构实现。
9. 供应商和模型图标采用 Lobe Icons 等许可明确的静态资源，不复制 Chatbox 的 GPL 图标代码，也不直接使用 Everywhere 的 Business Source License 资源。
10. 音频转写第一后端采用本地 `whisper.cpp`，按用户主动点击下载运行时和模型文件；云端 STT 作为后续可选后端扩展。
11. 模型页测试项从“文字、图片、视频、全部”扩展为“文字、图片、音频、视频、全部”。音频测试定位为模型原生音频输入冒烟测试：固定测试素材能被读取、必要时转为供应商 API 接受的格式、直接发送给当前模型，并得到非空且大致相关的听觉回复即可；该测试不经过 Whisper/STT，也不做严格逐字 ASR 验收。视频测试继续验证画面或视频输入能力；后续如需验证音画联合能力，应单独设计更严格的测试素材。
12. 模型页固定音频测试素材采用项目自录短语音的标准化 WAV 副本：`res/test_media/model_test_input.wav`。原始录音不作为长期素材保留；后续如需重新生成或替换测试音频，应重新录制或使用项目自有/离线生成的合成音频。
13. 音频能力必须分层记录，不能把“能转写音频”“能听懂音频”“能实时语音对话”“能理解视频内音频”混成同一个布尔值。Extract Once 的可追溯对白文本优先来自 ASR/STT 后端；音频理解模型可用于补充语气、环境声和听觉线索，但不应替代结构化转写事实。
14. Whisper 不是项目必需组件。默认素材整理、普通抽帧、纯文本/图片/音频原生测试/视频原生流程不得因为缺少 Whisper 被阻塞；只有用户选择了需要 transcript 的 API 模式或知识库生成路径时，才检查并提示安装/配置 Whisper。
15. 模型页 `全部` 测试遇到当前模型或 API 不支持的能力时，应表达为“模型不支持”“API 不支持”或同等明确原因，不把它伪装成调用失败。
16. 原生音频输入 schema 第一批优先接入 DashScope/Qwen-Omni 方向，因为当前项目已经存在 DashScope 视频调用路径。
17. Whisper 模型默认选择以模型 bin 体积和普通用户下载负担为优先；高级弹窗提供多个模型文件选择，并展示大小、速度和质量取舍。
18. transcript 知识库落点按独立子流程设计，先把音频转写事实沉入知识库，再由抽帧加转写或角色卡生成流程读取。
19. 当前真人声音测试素材可以继续作为开发与发布候选素材；录音者已确认可用于 CharaPicker 的开发、测试和发布包分发。素材来源简单记录在 `docs/reference/asset-material-declaration.zh_CN.md`。
20. 第一批 OpenAI-compatible 供应商按阶段推进：先接入 OpenAI、DeepSeek、OpenRouter 和自定义 OpenAI-compatible，后续再扩展更多聚合商或国内兼容供应商。
21. 非 Chat Completions schema 的后续优先级为：DashScope/Qwen-Omni 原生音频优先，其次 OpenAI Responses，再后 Gemini GenerateContent，Anthropic Messages 暂缓。
22. transcript 知识库落点以 episode 为主，chunk 只做按需引用或截取；音频转写文本通常不太长，视频拆 chunk 主要是为了控制视觉模型上下文、费用和长上下文退化。

## 4. 当前状态

当前代码事实以实施前重新核对为准；截至本文记录时：

- `utils/cloud_model_presets.py` 中 `CloudModelPreset` 主要保存 `name`、`provider`、`base_url`、`api_key`、`model_name`、`video_fps`、`max_output_tokens`。
- 当前供应商 ID 包括 `aliyunBailian`、`openaiCompatible`、`custom`。
- 阿里百炼的文本和图片后端走 OpenAI-compatible，视频后端走 DashScope。
- OpenAI-compatible 视频输入会在 `utils.ai_model_middleware` 中用 FFmpeg 抽帧为图片组，最多抽取一组有限帧后作为图片输入发送。
- DashScope 视频输入会通过 DashScope SDK 传递本地视频引用，并由 `_dashscope_api_url()` 把 `/compatible-mode/v1` 映射为 `/api/v1`。
- `gui/pages/model_page.py` 和 `core/extractor.py` 中存在基于 `"dashscope.aliyuncs.com"` 字符串判断阿里百炼 extra body 的逻辑，这会漏掉 `dashscope-intl`、`dashscope-us`、`cn-hongkong` 和 EU MaaS 域名。后续应改为基于 provider、endpoint 或 schema 元数据判断。

## 5. 目标状态

云端模型配置至少拆为五个概念：

- `provider`：供应商，例如阿里百炼、OpenAI、OpenRouter、DeepSeek、自定义。
- `endpoint`：该供应商下的 API 地址预设，例如阿里百炼 `cn`、`intl`、`us`、`hk`、`eu`。
- `api_schema`：API 规范，例如 OpenAI Chat Completions、OpenAI Responses、Anthropic Messages、Gemini GenerateContent、DashScope native。
- `capabilities`：能力声明，例如文本、图片、视频、音频转写、音频理解、音频生成、视频内音频理解、JSON mode、流式输出、模型列表、原生视频、抽帧视频。
- `video_input_mode`：视频输入方式，例如自动、供应商原生视频、抽帧图片、抽帧图片加音频转写、仅音频转写。

音频相关能力建议至少拆为：

- `audio_transcription`：语音转文本，产出 transcript、时间戳和可追溯来源；知识库落点以 episode 级 transcript 为主。
- `audio_understanding`：模型直接接收音频并回答“说了什么、有什么声音、语气如何”等问题，但不保证逐字转写精度。
- `audio_generation`：文本转语音或语音生成；当前不是 CharaPicker 的主目标能力。
- `video_audio_understanding`：原生视频接口是否会同时处理视频中的音轨，而不是只看画面帧。

第一阶段不要求把所有概念都持久化为最终形态，但实现时不得把供应商、地址、规范和能力继续揉成同一个字段。

## 6. 阿里百炼 API 地址预设

第一版内置如下地址：

| ID | 显示名 | Base URL | 备注 |
| --- | --- | --- | --- |
| `cn` | 中国内地 / 北京 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 默认值 |
| `intl` | 国际 / 新加坡 | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | 国际站常用 |
| `us` | 美国 / 弗吉尼亚 | `https://dashscope-us.aliyuncs.com/compatible-mode/v1` | API Key 与模型区域需匹配 |
| `hk` | 中国香港 | `https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1` | API Key 与模型区域需匹配 |
| `eu` | 欧盟 / 德国法兰克福 | `https://{WorkspaceId}.eu-central-1.maas.aliyuncs.com/compatible-mode/v1` | 需要用户填入 Workspace ID |
| `custom` | 自定义地址 | 用户输入 | 用于官方新增区域或私有代理 |

阿里百炼区域、API Key、模型可用性和 endpoint 必须匹配。EU endpoint 的 `{WorkspaceId}` 不能静默保留为占位符发起请求；UI 或保存逻辑应提示用户替换。

## 7. 视频输入方式

| 模式 ID | 显示名 | 视觉信息 | 音频信息 | 第一版建议 |
| --- | --- | --- | --- | --- |
| `auto` | 自动，推荐 | 由 provider 决定 | 由 provider 决定 | 默认 |
| `native_video` | 供应商原生视频 API | 有 | 取决于供应商和模型 | 阿里百炼优先 |
| `frame_sampling` | 抽帧为图片 | 有 | 无 | OpenAI-compatible 默认 |
| `frame_sampling_with_transcript` | 抽帧 + 音频转写 | 有 | 有，但转为文本 | 第二阶段细化 |
| `audio_transcript_only` | 仅音频转写 | 无 | 有，转为文本 | 第二阶段细化 |

抽帧模式的用户提示必须明确：该模式只向模型发送画面帧，模型不会听到视频中的声音。若用户需要对白、旁白、语气或背景声信息，应选择支持音频的视频原生 API，或选择抽帧加音频转写。

## 8. 数据与持久化

第一阶段推荐在现有预设结构上做向后兼容扩展：

```python
CloudModelPreset(
    name=...,
    provider="aliyunBailian",
    endpoint_id="cn",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_schema="openai_chat_completions",
    video_input_mode="auto",
    api_key=...,
    model_name=...,
    video_fps=...,
    max_output_tokens=...,
)
```

兼容规则：

- 旧配置没有 `endpoint_id` 时，根据 `provider` 和 `base_url` 尽量反推；反推失败则标记为 `custom`。
- 旧配置没有 `api_schema` 时，沿用当前 provider 的默认 schema。
- 旧配置没有 `video_input_mode` 时，使用 `auto`。
- 保存时可以继续保留 `base_url`，不要只保存 endpoint ID。这样用户自定义地址、历史配置和未来官方地址变更都更安全。

## 9. UI 与用户工作流

模型页面建议调整为：

1. 选择供应商。
2. 根据供应商刷新 API 地址下拉框。
3. 用户选择地址预设；若选择 EU 或自定义地址，展示可编辑 base URL 输入框。
4. 用户填写 API Key、模型名和输出 token 设置。
5. 用户选择视频输入方式，默认 `自动，推荐`。
6. 测试按钮按当前供应商、地址、schema 和视频方式执行实际测试，并在错误信息中提示区域/API Key/模型可能不匹配。

UI 文案必须避免误导：

- `抽帧为图片` 不应写成 `视频理解`。
- `抽帧 + 音频转写` 应提示会增加一次转写调用和费用。
- DashScope 原生视频应提示需要对应区域的 API Key 和支持该输入方式的模型。
- `全部` 测试不等于要求所有模型都支持所有能力。对当前 provider/schema/model 未声明支持的能力，应显示“模型不支持”“API 不支持”或同等原因；只有已声明支持但实际调用失败，才标记为测试失败。
- 模型页原生音频测试必须按 `api_schema` 走对应适配器。不同供应商对音频文件、base64、multipart、URL 或 Responses/GenerateContent 结构的要求不同，UI 不应直接拼请求体。

素材整理台建议同时承载本地工具准备状态：

- 在现有 FFmpeg 下载按钮右侧增加 Whisper 入口，位置仍属于素材整理台，而不是模型供应商设置页。
- Whisper 默认按钮执行推荐下载：当前平台稳定 CPU x64 runtime + 默认推荐模型。按钮文案应表达“一键准备 Whisper”或“下载 Whisper”，不要把高级概念暴露给普通用户。
- Whisper 入口旁增加“高级”按钮或下拉菜单，打开设置弹窗。弹窗内提供 runtime 版本、runtime 包类型、模型大小、模型语言倾向、使用本地已下载 runtime、安装/删除/重新检测等高级选项。
- 默认按钮和高级弹窗复用同一套下载器、进度弹窗、取消逻辑和网络代理策略；不得在 UI 层直接拼接下载 URL。
- Whisper 状态应和 FFmpeg 状态并列展示，例如已就位、缺少 runtime、缺少模型、版本不匹配、需要重新检测。
- Whisper 状态只作为可选能力提示，不参与普通素材处理按钮的启停判断。缺少 Whisper 时，普通素材整理和不需要转写的模型调用仍可继续。

## 10. 模块边界

- `utils.cloud_model_presets`：供应商、endpoint、schema、能力、视频输入方式的静态定义和预设持久化兼容。
- `utils.cloud_models`：按 schema 和 endpoint 拉取模型列表；第一阶段可继续只支持 OpenAI-compatible `/models`。
- `utils.ai_model_middleware`：保持模型请求唯一入口，按 backend/schema/video mode 路由，不让 UI 或 core 直接拼接模型 API。
- `utils.network_middleware`：继续负责应用内 HTTP、代理、错误脱敏和 DashScope SDK 临时代理环境。
- `utils.whispercpp_downloader` 或等价模块：负责 Whisper runtime/model 下载、校验、安装、取消和状态探测；不得把下载逻辑散落在页面层。
- `utils.audio_transcription` 或等价模块：负责音轨提取、格式转换、调用转写后端、缓存命中和 transcript 结构化输出；不得由 `project_page.py` 或 `model_page.py` 直接调用 `whisper-cli.exe`。
- `gui/pages/model_page.py`：只负责表单、测试按钮、状态展示和 i18n 文案，不实现底层模型调用细节。
- `gui/pages/project_page.py`：素材整理台展示 FFmpeg 与 Whisper 本地工具状态、触发默认下载和高级弹窗，不直接执行转写或拼接下载 URL。
- `core/extractor.py`：只选择当前项目和任务需要的预设/模式，具体请求仍交给 `ai_model_middleware`。

## 11. 供应商图标议题

供应商图标第一版采用许可明确的第三方静态资源，优先参考 Lobe Icons 的 MIT 资源。不得直接复制 Chatbox 的 `ProviderIcon.tsx` 或其他 GPL 代码中的 SVG path；也不得从 Everywhere 的 Business Source License 代码或资源中提取图标。

- 图标来源：优先使用 Lobe Icons 中已有的供应商/模型图标；缺失时使用中性首字母徽标或通用云端模型图标。
- 授权边界：新增图标资源时必须记录来源、许可证和拉取日期；若图标代表第三方商标，应在 third-party notice 中说明商标归属。
- 资源位置：运行时图片资源应放入 `res/` 下合适位置，并同步考虑打包。
- UI 呈现：供应商下拉框、预设列表和测试结果摘要可以显示图标；错误弹窗和日志不需要图标。
- 降级策略：缺少图标时显示通用云端模型图标或供应商首字母，不影响功能。
- 数据结构：provider metadata 只保存 `icon_id`，用户配置不保存图标路径。这样后续替换图标或更新资源不会影响旧配置。

参考方式：

- Chatbox 的 `ModelIcon` 先按模型名渲染模型图标，再回退到供应商图标，最后回退到首字母头像。
- CharaPicker 可采用相同优先级，但资源来源应直接来自许可明确的图标包或项目自绘资源，而不是复制 Chatbox 代码。

## 12. 音频转写议题

音频转写第一阶段采用本地 `whisper.cpp`。该方案应像 FFmpeg 和 llama.cpp 一样由用户主动下载运行时或模型文件，不随应用静默下载。

- 输入：从视频文件中提取音轨，或直接处理音频素材。
- 转写后落点：转写文本、时间戳、说话人信息和来源路径应进入可追溯的知识库结构，而不是只塞进一次性 prompt。
- 转写后端：第一后端为本地 `whisper.cpp`；后续可增加 OpenAI Speech-to-text、DashScope ASR 或其他云端 STT。
- 下载方式：新增 `utils/whispercpp_downloader.py` 或等价模块，复用 `network_middleware`、进度回调、取消逻辑、安全解压和错误脱敏。
- 模型文件：默认推荐以模型 bin 体积和普通用户下载负担为优先；大型模型必须明确提示下载大小、磁盘占用、耗时和本地性能要求。
- 格式依赖：`whisper-cli` 路径优先处理 16-bit WAV；视频音轨提取、m4a/mp3 等格式转换通常仍依赖 FFmpeg。需要 transcript 的视频流程若缺少 FFmpeg，也应给出明确提示。
- 与抽帧对齐：若有时间戳，应把帧时间点和转写片段时间范围一起提供给模型，避免画面和对白错位。
- 成本提示：转写会增加调用次数、耗时和费用，UI 必须直白提示。
- 隐私提示：音频可能包含对白、旁白和个人信息；日志不得记录完整转写文本。
- 运行时包：`whisper.cpp` 的 bin 不是单一文件，官方 release 会按平台、架构和加速后端提供不同压缩包。第一版下载器应默认选择 Windows x64 CPU 包，其他加速包作为高级选项。
- 非阻塞原则：缺少 Whisper runtime 或模型时，不影响不需要转写的流程；只有明确需要 transcript 的流程才弹出缺失提示或安装引导。

第一阶段实现边界：

- 模型页的音频测试不使用 Whisper/STT。它应把固定测试音频直接传给当前供应商/模型的音频输入接口，用于验证 `audio_understanding` 或等价能力。
- 若当前 provider/schema/model 没有声明或无法实现直接音频输入，模型页音频测试应禁用或提示“不支持直接音频输入”，不得自动改走 Whisper 转写来伪装通过。
- 预览或正式提取如果选择了 `frame_sampling_with_transcript`、`audio_transcript_only` 或其他明确需要转写的模式，启动前必须检查转写后端。缺少 Whisper runtime 或模型时，提示用户安装、改用不含转写的模式，或取消本次操作。
- 音频测试素材可使用项目自录短语音。模型页音频测试验收优先检查直传音频链路可运行、模型能明确回应听到的内容或语言方向；不要要求模型逐字识别专有名词。
- 视频抽帧加转写模式应先复用已有转写结果；没有可用转写结果且 Whisper 已就位时，在生成知识库或发起模型调用前先执行转写，再把 transcript 与帧时间点一起提供给模型。
- 生成知识库时，如果目标流程需要音频 transcript，但项目尚未生成对应转写结果，应把转写作为生成前置步骤自动执行；若 Whisper 未安装或不可用，则给出明确提示并让用户选择安装、跳过音频、或切换为不需要转写的流程。
- 云端 STT 不是第一后端，但数据模型和 UI 不应把转写能力绑定死在本地 Whisper。

### 12.1 模型页音频测试素材

当前开发期测试素材整理为：

- 规范测试输入：`res/test_media/model_test_input.wav`，由第二版录音转为 16 kHz、mono、PCM WAV。
- 原始 m4a 录音不保留在仓库中，避免不必要的真人声音来源文件沉淀。
- 期望短语：`これはキャラピッカーのオーディオテストです`。

本地 `whisper.cpp` + `ggml-base.bin` 的人工实测结果仅用于转写链路参考，不作为模型页音频测试路径：

- 第二版录音能被识别为日语方向，`-l auto` 和 `-l ja` 均能返回非空日语文本。
- base 模型对专有词和软萌/含糊发音会有误识别，实测近似输出为 `これはキャラピンカムオーティオーペストです。`。
- 该结果足以证明本地转写链路可运行，但不足以作为逐字转写质量验收。

模型页音频测试的推荐验收口径：

- 对音频理解模型：测试提示应询问“你听到了什么”，通过条件是模型能明确回应音频内容或语言方向，而不是严格匹配全文。
- 对“全部”测试：音频失败应单独标记具体环节，例如文件读取、音频格式转换、模型 schema 不支持音频输入、供应商接口不支持音频，或模型返回无法判断。
- 对不支持音频输入的模型：`全部` 测试可以把音频项标记为“模型不支持”“API 不支持”或同等原因，不应让整个测试结果表现得像链路故障。
- 对 STT/ASR 后端：不归入模型页音频测试；后续如需单独测试转写器，应建立“转写测试”入口或放在 Whisper 高级弹窗中。
- 对发布包：当前真人声音测试素材可以保留。若后续不想包含真人声音，再替换为项目自有或离线生成的合成音频。

### 12.2 `whisper.cpp` 运行时包选择

截至 2026-05-25，`whisper.cpp` 官方 latest release 为 `v1.8.4`。实现下载器前必须重新核对 latest release 和 assets 列表；不要把下列包名写死为永不过期事实。

下载器应把三类对象分开：

- 转写引擎：`whisper.cpp`。这是后端类型和兼容层名称，不等同于某一个具体 zip 包。
- 运行时包：具体可执行文件和动态库，例如 CPU x64、BLAS x64、CUDA x64。它决定“怎么跑”和能否利用硬件加速。
- 模型文件：`ggml-*.bin`，例如 `base`、`small`、`medium`。它主要决定识别质量、语言覆盖、速度和内存占用。

第一版建议支持：

- 默认包：`whisper-bin-x64.zip`。适合绝大多数 Windows 64-bit 用户，体积小，依赖少，作为 CharaPicker 默认下载项。
- 兼容包：`whisper-bin-Win32.zip`。仅面向 32-bit Windows；CharaPicker 若只支持 64-bit 打包，可以不暴露给普通用户。
- CPU 加速包：`whisper-blas-bin-x64.zip`。可能提升 CPU 推理性能，但包更大，依赖和运行环境更复杂；可作为“高级/实验”选项。
- NVIDIA GPU 包：`whisper-cublas-11.8.0-bin-x64.zip`、`whisper-cublas-12.4.0-bin-x64.zip`。需要 NVIDIA GPU、驱动和对应 CUDA 运行时匹配；包更大，失败面更宽，不作为默认下载。
- 非 CharaPicker Windows 桌面主线包：`whisper-v1.8.4-xcframework.zip` 面向 Apple framework 场景，`whispercpp.jar.zip` 面向 Java 绑定；第一阶段不需要接入。

下载器策略：

- UI 默认展示“推荐配置”，自动选择当前平台的稳定 CPU x64 runtime；高级区域允许用户手动选择 runtime 版本和包类型。
- 默认下载入口放在素材整理台的 FFmpeg 下载按钮右侧；高级设置通过相邻按钮或菜单弹出，不挤占主表单。
- runtime 版本选择应支持“推荐稳定版”和“手动选择版本”。第一版可以只内置一个经测试的版本；后续通过远程 manifest 或 GitHub release metadata 扩展可选版本。
- runtime 包类型选择应与版本选择分开，例如同一个 `v1.8.4` 下可选 CPU x64、BLAS x64、CUDA 11.8、CUDA 12.4。
- 支持“使用本地已下载 runtime”作为兜底入口，让高级用户手动指定 `whisper-cli.exe` 所在目录。
- 记录 `runtime_version`、`package_id`、`download_url`、`sha256`、`installed_path` 和 `detected_backend`，便于后续升级、校验和故障排查。
- UI 默认只展示“推荐 CPU x64”，高级选项折叠展示 BLAS/CUDA。
- 自动探测 GPU 可以作为后续增强；第一版不应自动下载 CUDA 包，避免体积、驱动和兼容性问题让用户困惑。
- 运行时包和 Whisper 模型文件分开安装、分开升级、分开删除。升级 runtime 不应删除模型文件；更换模型也不应要求重新下载 runtime。
- 安装目录建议按版本和包类型隔离，例如 `bin/whisper.cpp/{version}/{package_id}/`；模型文件继续放在 `models/whisper/`。

模型文件策略：

- 默认模型以 `ggml-*.bin` 文件体积和普通用户下载负担为优先，第一版可选择轻量模型作为推荐默认值；实施前按实际模型清单重新核对大小。
- 高级弹窗提供模型选择，不把用户锁死在默认模型。每个选项应展示大致体积、速度、质量倾向和适合场景。
- 大模型不应默认下载；选择大型模型时必须提示磁盘占用、下载耗时和本地推理性能要求。
- 模型文件与 runtime 分开校验。模型缺失时只提示下载模型，不要求重装 runtime。

### 12.3 transcript 知识库子流程

transcript 子流程目标是把音频事实作为可追溯素材写入知识库，而不是只在一次模型 prompt 中临时拼接。默认以 episode 级 transcript 为主要落点，chunk 级数据只在需要和画面帧精确对齐时引用或截取。

推荐流程：

1. 识别转写需求：只有 `frame_sampling_with_transcript`、`audio_transcript_only`、角色卡生成需要对白事实，或用户显式启用音频转写时，才进入本流程。
2. 定位素材与音轨：从项目 `materials/` 中定位视频或音频素材；视频素材优先通过 FFmpeg 提取音轨并转为转写后端可接受的格式。
3. 查找缓存：按素材路径、文件指纹、处理配置、转写后端、模型文件和语言参数查找已有 transcript。
4. 执行转写：缓存缺失且后端可用时调用 Whisper 或后续云端 STT；失败时记录脱敏错误并让上层决定安装、跳过或切换流程。
5. 写入知识库：优先写入 episode 级 transcript，保存 transcript 文本、分段、时间戳、来源素材、后端信息、模型信息和生成时间。
6. 对齐画面：抽帧加转写模式读取 episode transcript 分段，并按时间戳为 chunk 或帧时间点截取相关片段后传给模型。
7. 失效与重用：素材变化、转写模型变化、语言参数变化或切分策略变化时，应让旧 transcript 失效或标记为需重建。

首版先按第 16 节 M06 的 schema 和 `knowledge_base/seasons/.../episodes/.../episode_transcript.json` 路径实现；原则上 episode 是主文件，chunk 不重复保存完整 transcript。后续若知识库结构调整，再增加迁移或兼容读取。

## 13. 音频模型能力分层

音频模型相关能力建议按用途拆开，而不是统一称为“支持音频”。

| 能力层 | 典型输入 | 典型输出 | 适合用途 | 第一阶段建议 |
| --- | --- | --- | --- | --- |
| ASR / STT 转写 | 音频或视频音轨 | 文本、时间戳、分段 | Extract Once 的对白、旁白、可追溯素材事实 | 优先接入 |
| 音频理解模型 | 音频片段 | 自然语言回答或结构化听觉摘要 | 模型页听觉冒烟测试、语气、情绪、环境声、音乐和非语言声音线索 | DashScope/Qwen-Omni 优先 |
| 实时语音 / Speech-to-speech | 麦克风流或低延迟音频流 | 实时文本、语音或对话事件 | 语音交互、实时助手 | 暂不作为主线 |
| 原生视频音频理解 | 视频文件或视频 URL | 音画联合回答 | 供应商能同时看画面和听音轨时的视频理解 | 能力需逐供应商验证 |

设计结论：

- 角色档案生成需要稳定、可追溯、可缓存的对白事实，因此正式知识库中的 transcript 应优先来自 ASR/STT 后端，而不是来自音频理解模型的一段自由回答。
- 音频理解模型适合补足“语气很急”“背景有掌声”“角色在哭腔说话”“画面外有人说话”等听觉线索，这些内容可以作为 insight 或证据备注进入知识库。
- 原生音频输入第一批 schema 优先接入 DashScope/Qwen-Omni 方向，复用当前已有 DashScope 视频调用和代理适配经验。
- 原生视频模型可能同时理解画面和音轨，但不同供应商、不同模型差异很大；模型页应把它作为独立能力测试，不应从“支持视频上传”自动推断“支持视频内音频”。
- 供应商预设需要允许“聊天/视觉模型”和“转写模型”分开配置。例如同一个项目可以用 OpenAI-compatible 聊天模型做图文分析，用本地 `whisper.cpp` 或云端 STT 做转写。
- 后续数据结构可以增加 `transcription_backend`、`audio_understanding_backend` 或等价字段。第一阶段可以先在计划和能力声明中留出边界，不急于持久化所有字段。

## 14. 参考来源

- Alibaba Cloud Model Studio regions：`https://www.alibabacloud.com/help/en/model-studio/regions/`
- Alibaba Cloud Qwen-Omni：`https://www.alibabacloud.com/help/en/model-studio/qwen-omni`
- Google Gemini audio understanding：`https://ai.google.dev/gemini-api/docs/audio`
- Google Gemini video understanding：`https://ai.google.dev/gemini-api/docs/video-understanding`
- OpenAI Speech to text：`https://platform.openai.com/docs/guides/speech-to-text`
- OpenAI Responses API reference：`https://platform.openai.com/docs/api-reference/responses`
- Chatbox OpenAI-compatible model source：`https://github.com/chatboxai/chatbox/blob/b45fc528e6f6682656166d5d068f2f1b4907c405/src/shared/models/openai-compatible.ts`
- Chatbox ModelIcon source：`https://github.com/chatboxai/chatbox/blob/b45fc528e6f6682656166d5d068f2f1b4907c405/src/renderer/components/icons/ModelIcon.tsx`
- Chatbox ProviderIcon source：`https://github.com/chatboxai/chatbox/blob/b45fc528e6f6682656166d5d068f2f1b4907c405/src/renderer/components/icons/ProviderIcon.tsx`
- Lobe Icons license：`https://github.com/lobehub/lobe-icons/blob/master/LICENSE`
- whisper.cpp license：`https://github.com/ggml-org/whisper.cpp/blob/master/LICENSE`
- whisper.cpp latest release：`https://github.com/ggml-org/whisper.cpp/releases/latest`
- OpenAI Whisper license：`https://github.com/openai/whisper/blob/main/LICENSE`
- Everywhere provider schema source：`https://github.com/Sylinko/Everywhere/blob/615215a8154f33858ce43560b0601613945453ee/src/Everywhere.Abstractions/AI/ModelProviderSchema.cs`
- Everywhere kernel factory source：`https://github.com/Sylinko/Everywhere/blob/615215a8154f33858ce43560b0601613945453ee/src/Everywhere.Core/AI/KernelMixinFactory.cs`

## 15. 执行前准备

后续 AI 或开发者开始实现前，先完成以下动作：

1. 读取 `AGENTS.md`、`ARCHITECTURE.md`、`utils/ARCHITECTURE.md`、`gui/ARCHITECTURE.md`、`i18n/ARCHITECTURE.md`、`res/ARCHITECTURE.md`。
2. 运行 `git status --short`，确认工作区中是否已有用户改动；不得回滚无关改动。
3. 重新核对阿里百炼 region 文档、`whisper.cpp` latest release assets、DashScope/Qwen-Omni 音频输入文档。
4. 检查当前代码事实是否仍与本计划第 4 节一致；若不一致，先更新本计划或在实现说明中记录偏差。
5. 每个里程碑独立完成和验证；不要一次性跨所有模块大改。

推荐基础验证命令：

```powershell
python -m compileall utils gui core
git diff --check
```

如果当前环境装有 Ruff，再运行：

```powershell
python -m ruff check utils gui core
```

## 16. 可执行里程碑

### M00：整理基线与素材声明

目的：先确认固定测试素材和文档入口，避免后续功能依赖缺文件。

涉及文件：

- `docs/README.md`
- `docs/reference/asset-material-declaration.zh_CN.md`
- `res/test_media/model_test_input.jpg`
- `res/test_media/model_test_input.mp4`
- `res/test_media/model_test_input.wav`

实施步骤：

1. 确认三份测试素材存在，音频为 16 kHz、mono、PCM WAV。
2. 确认 `docs/README.md` 已链接素材来源说明。
3. 若替换图片、视频或音频，在 `docs/reference/asset-material-declaration.zh_CN.md` 补来源说明。

验收：

- `res/test_media/` 中存在图片、视频、音频三类测试素材。
- 文档索引可找到素材来源说明。
- `git diff --check` 无空白错误。

边界：

- 不处理用户 `projects/` 中的素材。
- 不下载外部模型或工具。

建议提交：`docs: record bundled test asset sources`

### M01：供应商、endpoint、schema 和能力元数据

目的：把 provider、endpoint、schema、capabilities 和 video mode 从单一字段中拆开，并兼容旧配置。

涉及文件：

- `utils/cloud_model_presets.py`
- `utils/cloud_models.py`
- `i18n/zh_CN.json`
- `i18n/zh_TW.json`
- `i18n/en_US.json`
- `i18n/ja_JP.json`

实施步骤：

1. 在 `utils/cloud_model_presets.py` 中新增稳定常量和类型：
   - `CloudEndpointPreset`
   - `CloudApiSchema`
   - `CloudCapability`
   - `VideoInputMode`
2. 扩展 `CloudModelPreset`，新增可选字段：
   - `endpoint_id: str = ""`
   - `api_schema: str = ""`
   - `video_input_mode: str = "auto"`
3. 保留并继续保存 `base_url`。保存时不要只保存 endpoint ID。
4. 在加载旧配置时按规则补默认值：
   - 没有 `endpoint_id`：根据 provider 和 base_url 尽量反推，失败用 `custom`。
   - 没有 `api_schema`：使用 provider 默认 schema。
   - 没有 `video_input_mode`：使用 `auto`。
5. 为阿里百炼内置 endpoint：
   - `cn`
   - `intl`
   - `us`
   - `hk`
   - `eu`
   - `custom`
6. 为 OpenAI、DeepSeek、OpenRouter、自定义 OpenAI-compatible 增加 provider 模板，顺序为阿里百炼、OpenAI、DeepSeek、OpenRouter、自定义。
7. 为每个 provider 声明默认 schema、默认 endpoint、模型列表能力、文本/图片/视频/音频能力、默认视频模式。
8. 更新 `utils/cloud_models.py`，让模型列表拉取通过 provider/schema 元数据决定是否可用；第一阶段仍可只实现 OpenAI-compatible `/models`。
9. 补四语 i18n 文案，包括 provider 名称、endpoint 名称、状态名和能力不支持原因。

验收：

- 旧 `config.yaml` 里的 cloud preset 能正常加载、显示、保存。
- 阿里百炼默认 endpoint 为 `cn`。
- EU endpoint 占位符 `{WorkspaceId}` 未替换时不会静默发起请求。
- OpenAI、DeepSeek、OpenRouter、自定义 OpenAI-compatible 能作为独立供应商模板出现。
- 不支持模型列表的 schema 不会被当作网络错误。

可用轻量检查：

```powershell
python -m compileall utils
```

边界：

- 不在此阶段改模型页布局。
- 不接入非 Chat Completions 的真实请求体。

建议提交：`feat(models): add provider endpoint metadata`

### M02：模型页 UI 与旧预设交互

目的：让用户能选择供应商、endpoint、视频输入方式，并清楚看到能力支持状态。

涉及文件：

- `gui/pages/model_page.py`
- `gui/pages/model_test_helpers.py`
- `utils/model_preferences.py`
- 四个 `i18n/*.json`

实施步骤：

1. 在模型页 provider 选择处改为读取 provider metadata，而不是硬编码当前三类 provider。
2. 增加 endpoint 下拉框：
   - 切换 provider 后刷新 endpoint 列表。
   - 选择 EU 或 custom 时展示可编辑 base URL。
   - 选择普通 endpoint 时用预设 base URL 填充。
3. 增加视频输入方式下拉框：
   - 默认 `auto`。
   - 可选 `native_video`、`frame_sampling`、`frame_sampling_with_transcript`、`audio_transcript_only`。
   - 未支持项禁用或提示原因，不要运行后才失败。
4. 保存 preset 时写入新增字段，并继续写入 `base_url`。
5. 读取 preset 时恢复 provider、endpoint、schema、video mode 和 base URL。
6. `全部` 测试结果增加“模型不支持”“API 不支持”“已跳过”等状态，不把未支持能力当作失败。
7. 文案必须四语同步，避免把抽帧写成完整视频理解。

首版状态文案建议：

| 状态 | zh_CN | zh_TW | en_US | ja_JP |
| --- | --- | --- | --- | --- |
| model_unsupported | 模型不支持 | 模型不支援 | Model unsupported | モデル未対応 |
| api_unsupported | API 不支持 | API 不支援 | API unsupported | API 未対応 |
| skipped | 已跳过 | 已略過 | Skipped | スキップ済み |
| failed | 调用失败 | 呼叫失敗 | Call failed | 呼び出し失敗 |

验收：

- 切换阿里 endpoint 后 base URL 正确变化。
- 自定义 endpoint 可编辑并可保存。
- 旧 preset 没有新增字段时仍可正常显示。
- `全部` 测试对未支持能力显示明确状态。
- UI 不直接拼接音频请求体或下载 URL。

可用轻量检查：

```powershell
python -m compileall gui utils
```

边界：

- 不在此阶段实现 DashScope 原生音频请求。
- 不在此阶段实现 Whisper。

建议提交：`feat(ui): expose provider endpoints and video modes`

### M03：修正阿里区域判断和请求路由

目的：移除域名子串判断，让阿里专用行为由 provider/endpoint/schema 元数据决定。

涉及文件：

- `gui/pages/model_page.py`
- `core/extractor.py`
- `utils/ai_model_middleware.py`
- `utils/cloud_model_presets.py`

实施步骤：

1. 删除或替换基于 `"dashscope.aliyuncs.com"` 的判断。
2. 新增 helper，例如 `is_aliyun_provider(provider)` 或 `provider_metadata.requires_aliyun_extra_body`。
3. 模型页测试、预览、正式提取都通过 provider 元数据决定是否注入 `enable_thinking=False` 等阿里参数。
4. 确保 `dashscope-intl`、`dashscope-us`、`cn-hongkong`、EU MaaS 都被识别为阿里 provider。
5. 确保自定义 OpenAI-compatible 地址不会被误判为阿里。

验收：

- 阿里五类 endpoint 行为一致。
- 非阿里自定义 URL 不注入阿里专用参数。
- 视频请求仍经 `call_video_model()` 进入 `utils.ai_model_middleware`。

可用轻量检查：

```powershell
python -m compileall core gui utils
```

边界：

- 不改 DashScope SDK 底层上传策略。
- 不把 provider 判断散落在页面和 core 中。

建议提交：`fix(models): route aliyun behavior by metadata`

### M04：模型页原生音频测试，DashScope/Qwen-Omni 优先

目的：新增模型页“音频”测试，直接把音频传给模型，验证模型原生听音频能力。

涉及文件：

- `gui/pages/model_page.py`
- `gui/pages/model_test_helpers.py`
- `utils/ai_model_middleware.py`
- `utils/cloud_model_presets.py`
- `res/test_media/model_test_input.wav`
- 四个 `i18n/*.json`

实施步骤：

1. 新增 `AUDIO_TEST_ASSET = TEST_MEDIA_ROOT / "model_test_input.wav"`。
2. 模型页测试类型从文字/图片/视频/全部扩展为文字/图片/音频/视频/全部。
3. 新增 `CloudAudioTestWorker`，只用于原生音频输入测试，不调用 Whisper/STT。
4. 在 `utils.ai_model_middleware` 中新增音频调用入口，建议命名为 `call_audio_model()`。
5. 第一批只实现 DashScope/Qwen-Omni 方向的 schema 适配；不支持的 schema 返回可解释的“不支持 API 音频输入”错误。
6. 音频测试 prompt 使用“你听到了什么”这类轻量提示，要求模型返回非空且大致相关的听觉回复。
7. `全部` 测试按顺序执行文字、图片、音频、视频；音频不支持时标记为模型不支持或 API 不支持，不让整个测试失败。
8. 音频文件如需转为供应商接受的格式，转换逻辑放在中间件/helper，不放在 UI。

验收：

- DashScope/Qwen-Omni 支持时，音频测试直接上传/传递 `model_test_input.wav` 并得到回复。
- 不支持音频输入的模型，音频项显示“模型不支持”或“API 不支持”。
- 缺少 Whisper 不影响音频测试。
- `全部` 测试能展示音频分项状态。

可用轻量检查：

```powershell
python -m compileall gui utils
```

人工验收：

- 用支持音频的 DashScope/Qwen-Omni 模型测试音频。
- 用不支持音频的普通 OpenAI-compatible 模型测试，确认状态不是普通错误。

边界：

- 不实现 OpenAI Responses 或 Gemini 音频 schema。
- 不要求模型逐字识别测试短语。

建议提交：`feat(models): add dashscope audio connectivity test`

### M05：Whisper 下载器和素材整理台入口

目的：把 Whisper 作为可选本地工具放在素材整理台，默认一键准备，高级可选 runtime/model。

涉及文件：

- `utils/whispercpp_downloader.py`
- `utils/env_manager.py`
- `utils/startup_middleware.py`
- `gui/pages/project_page.py`
- 四个 `i18n/*.json`
- 可选：`utils/ARCHITECTURE.md`

实施步骤：

1. 新增 `utils/whispercpp_downloader.py`，参考 `utils/ffmpeg_downloader.py`：
   - 使用 `network_middleware.open_response()`。
   - 支持 progress callback。
   - 支持 cancelled callback。
   - 安全解压 zip，防路径穿越。
   - 错误信息脱敏。
2. runtime 和 model 分开下载、安装、检测：
   - runtime 放 `bin/whisper.cpp/{version}/{package_id}/`。
   - 模型放 `models/whisper/`。
3. 默认 runtime 为 Windows x64 CPU 包；BLAS/CUDA 只放高级选项。
4. 默认模型按 `ggml-*.bin` 体积和普通用户下载负担选择轻量推荐；高级弹窗显示多个模型选项。
5. 在 `env_manager.py` 或新 helper 中增加 Whisper runtime/model 检测函数。
6. 在 `startup_middleware.py` 的预热快照中加入 Whisper 可用性状态，若实现成本偏大，可先由项目页按需探测。
7. 在 `gui/pages/project_page.py` 的素材整理台 FFmpeg 下载按钮右侧增加 Whisper 默认按钮和高级按钮。
8. 默认按钮一键下载推荐 runtime + 推荐模型。
9. 高级弹窗提供 runtime 版本、包类型、模型文件、使用本地 runtime、重新检测、删除/重装等入口。
10. Whisper 缺失不禁用普通素材整理。

验收：

- 普通用户点击默认 Whisper 按钮可看到下载、解压、安装进度。
- 取消下载不会留下半安装状态，也不会破坏已有 FFmpeg。
- 高级弹窗可切换选项或指定本地 `whisper-cli.exe`。
- 缺少 Whisper 时普通素材整理按钮仍可用。
- 所有新增可见文案四语同步。

可用轻量检查：

```powershell
python -m compileall utils gui
```

人工验收：

- 在没有 Whisper 的环境打开素材整理台，确认状态为可选缺失。
- 下载默认包，确认检测为可用。
- 删除或重命名模型文件，确认提示缺少模型而不是要求重装 runtime。

边界：

- 不自动下载 CUDA 包。
- 不在页面层拼下载 URL。
- 不随应用静默下载 Whisper。

建议提交：`feat(tools): add optional whisper runtime manager`

### M06：本地转写服务和 episode transcript

目的：实现 episode 级 transcript 子流程，供抽帧加转写和角色卡生成复用。

涉及文件：

- `utils/audio_transcription.py`
- `utils/ffmpeg_tool.py`
- `utils/paths.py`
- `core/extractor.py`
- `core/models.py`
- 可选：`core/knowledge_base.py` 或当前知识库 helper 所在文件
- 四个 `i18n/*.json`

建议路径：

- 主文件：`knowledge_base/seasons/{season_id}/episodes/{episode_id}/episode_transcript.json`
- chunk 引用：只保存时间范围、来源引用或截取摘要，不重复保存完整 transcript。

首版 schema：

```json
{
  "schema_version": 1,
  "source": {
    "material_path": "materials/...",
    "source_fingerprint": "...",
    "episode_id": "...",
    "season_id": "..."
  },
  "transcription": {
    "backend": "whisper.cpp",
    "runtime_version": "v1.8.4",
    "runtime_package": "whisper-bin-x64",
    "model_file": "ggml-base.bin",
    "language": "auto",
    "generated_at": "..."
  },
  "segments": [
    {
      "start_seconds": 0.0,
      "end_seconds": 2.4,
      "text": "..."
    }
  ],
  "plain_text": "..."
}
```

实施步骤：

1. 新增转写服务入口，例如 `transcribe_episode_audio(project_id, episode_ref, options)`。
2. 需要 transcript 时先查 episode transcript 缓存。
3. 缓存 key 至少考虑素材路径、文件指纹、转写后端、模型文件、语言参数、处理配置。
4. 对视频素材先通过 FFmpeg 提取音轨并转为 16-bit WAV；缺 FFmpeg 时提示不能提取音轨。
5. 调用 `whisper-cli.exe` 时使用非交互子进程，避免日志写入完整 transcript。
6. 解析输出为 segments 和 plain_text。
7. 写入 episode transcript JSON。
8. 抽帧加转写时按帧或 chunk 时间范围截取相关 transcript 片段，随 prompt 传入模型。
9. 素材、模型、语言或切分策略变化时让缓存失效或标记需重建。

验收：

- 已安装 Whisper 后，固定测试音频可生成 transcript JSON。
- 需要 transcript 的视频流程在没有 episode transcript 时会先转写。
- 缺 Whisper 时提示安装/切换/跳过，不伪造 transcript。
- 缺 FFmpeg 且输入是视频时提示无法提取音轨。
- transcript 不进入普通日志。
- chunk 不重复保存完整 transcript。

可用轻量检查：

```powershell
python -m compileall utils core
```

人工验收：

- 用 `res/test_media/model_test_input.wav` 跑一次本地转写。
- 用一个短视频素材确认 episode transcript 写入知识库。

边界：

- 不在本阶段做云端 STT。
- 不把 transcript 塞进一次性 prompt 后丢弃。

建议提交：`feat(extraction): add episode audio transcription`

### M07：抽帧加转写模式接入模型调用

目的：让 `frame_sampling_with_transcript` 和 `audio_transcript_only` 真正影响请求输入。

涉及文件：

- `utils/ai_model_middleware.py`
- `core/extractor.py`
- `utils/cloud_model_presets.py`
- `utils/audio_transcription.py`
- 四个 `i18n/*.json`

实施步骤：

1. `video_input_mode=auto` 继续按 provider 默认策略。
2. `frame_sampling` 只发送画面帧，不包含 transcript。
3. `frame_sampling_with_transcript` 先确保 episode transcript 可用，再发送画面帧和对应时间范围 transcript。
4. `audio_transcript_only` 只发送 transcript 文本，不发送画面帧。
5. 所有 transcript 文本都经过长度控制，避免塞满上下文。
6. UI 明确提示抽帧加转写会增加耗时，云端 STT 后续还可能增加费用；本地 Whisper 主要增加本机耗时。

验收：

- 同一视频选择 `frame_sampling` 时 prompt 不含 transcript。
- 选择 `frame_sampling_with_transcript` 时 prompt 含相关 transcript。
- 选择 `audio_transcript_only` 时不抽帧。
- Whisper 缺失时只有需要 transcript 的模式被拦截。

可用轻量检查：

```powershell
python -m compileall utils core gui
```

边界：

- 不改变供应商原生视频模式的行为。
- 不假设原生视频一定听得到音频。

建议提交：`feat(models): route video transcript input modes`

### M08：供应商和模型图标

目的：给 provider/model 增加图标显示，同时保持授权简单清楚。

涉及文件：

- `utils/cloud_model_presets.py`
- `gui/pages/model_page.py`
- `res/` 下新增图标资源目录
- `docs/reference/asset-material-declaration.zh_CN.md`
- 可选：`main.spec`
- 四个 `i18n/*.json`

实施步骤：

1. provider metadata 新增 `icon_id`。
2. 资源优先来自 Lobe Icons 或项目自绘资源；不要复制 Chatbox GPL SVG path 或 Everywhere BSL 资源。
3. 建立 `icon_id` 到资源路径的映射。
4. 模型页 provider 下拉或列表渲染图标；缺图时回退到通用图标或首字母。
5. 更新素材来源说明或 third-party notice。
6. 确认 PyInstaller 打包包含新增资源。

验收：

- 缺图不影响功能。
- 打包后图标可加载。
- 授权来源有记录。

可用轻量检查：

```powershell
python -m compileall gui utils
```

边界：

- 不把图标路径写入用户配置。
- 不让图标加载失败影响模型调用。

建议提交：`feat(ui): add provider icons`

### M09：文案、验证和收尾

目的：保证功能可用、文案完整、实现边界没有跑偏。

涉及文件：

- 四个 `i18n/*.json`
- `docs/archive/multi-provider-api-support-plan.completed.zh_CN.md`
- `docs/reference/asset-material-declaration.zh_CN.md`
- 相关 `ARCHITECTURE.md`，若新增模块职责已稳定则更新

实施步骤：

1. 全量搜索新增中文文案，确认都进入四个 i18n JSON。
2. 全量搜索 `dashscope.aliyuncs.com`，确认没有旧的区域判断逻辑。
3. 全量搜索 `Whisper`、`whisper`，确认下载、检测、转写职责在 utils，不在页面层执行核心逻辑。
4. 确认日志不输出完整 API Key、代理凭据、完整 transcript、大型素材内容。
5. 确认 `docs/reference/asset-material-declaration.zh_CN.md` 包含新增随包资源。
6. 若新增长期模块，更新 `utils/ARCHITECTURE.md` 或相关架构文档。

验收命令：

```powershell
python -m compileall utils gui core
git diff --check
```

如果 Ruff 可用：

```powershell
python -m ruff check utils gui core
```

人工验收清单：

- 旧云端模型预设仍可打开和保存。
- 阿里 `cn` endpoint 默认可见。
- 切换 provider 会刷新 endpoint。
- `全部` 测试能区分成功、失败、模型不支持、API 不支持、已跳过。
- DashScope 原生音频测试直接传音频，不调用 Whisper。
- Whisper 缺失不阻塞普通素材整理。
- 需要 transcript 的流程在 Whisper 缺失时给出明确选择。
- episode transcript 可复用，不重复转写同一素材。

执行记录（2026-05-25）：

- 已全量搜索 Python 源码中的中文文案；除 `utils/i18n.py` 语言名和模型页固定测试 prompt 外，新增用户可见文案均已进入四个 `i18n/*.json`。
- 已搜索 `dashscope.aliyuncs.com`、`dashscope-intl`、`dashscope-us`、`cn-hongkong` 和 `maas.aliyuncs`；相关字符串保留在 endpoint 预设和 DashScope URL 归一化中，`gui/` 与 `core/` 不再用旧域名字符串判断阿里行为。
- 已搜索 `Whisper` / `whisper`；下载、检测、安装、删除、转写和 transcript 缓存逻辑位于 `utils/`，页面层只负责状态展示、用户触发和 Qt worker 桥接。
- 已抽查模型调用、下载器、转写和页面 worker 日志；日志只记录 endpoint、模型名、状态、路径、计数、token usage 或脱敏错误，不输出完整 API Key、完整 transcript、完整请求体或大型素材内容。
- `docs/reference/asset-material-declaration.zh_CN.md` 已记录新增的 `res/provider_icons/*.svg` 随包资源；`core/`、`utils/`、`projects/`、`res/` 的架构说明已随对应里程碑更新。
- 已运行：`python -m compileall utils gui core`、`conda run -n CharaPicker python -m compileall utils gui core`、`python -m ruff check utils gui core`、对四个 `i18n/*.json` 分别执行 `python -m json.tool`、`python -m json.tool res\default_prompts.json`、`git diff --check`。
- 已做轻量冒烟：旧 `openaiCompatible` 预设可归一化；阿里 `cn/intl/us/hk/eu/custom` endpoints 可枚举；模型页能力状态 helper 在 `CharaPicker` conda 环境可导入并返回预期状态。
- 未执行真实联网 API 与完整 GUI 人工验收；这些需要有效供应商 API Key、可用模型和用户侧交互试用。

建议提交：`test: verify multi-provider and audio workflows`

## 17. 实施顺序和提交分组

建议按以下顺序提交，便于审查和回退：

1. `docs: refine multi-provider implementation guide`
2. `feat(models): add provider endpoint metadata`
3. `feat(ui): expose provider endpoints and video modes`
4. `fix(models): route aliyun behavior by metadata`
5. `feat(models): add dashscope audio connectivity test`
6. `feat(tools): add optional whisper runtime manager`
7. `feat(extraction): add episode audio transcription`
8. `feat(models): route video transcript input modes`
9. `feat(ui): add provider icons`
10. `test: verify multi-provider and audio workflows`

提交边界：

- 每个提交必须能通过 `python -m compileall`。
- UI 提交必须补齐四语 i18n。
- 下载器提交必须复用 `network_middleware`。
- 模型请求提交必须通过 `ai_model_middleware`。
- transcript 提交不得把完整 transcript 写入普通日志。

## 18. 验收后收尾

只有完成全部开发里程碑并经过用户试用后，再做收尾：

- 删除临时调试脚本、临时下载文件和中间转码测试文件。
- 检查 `bin/`、`models/`、`projects/`、`log/` 没有被误提交。
- 检查新增资源是否需要进入 `main.spec` 或打包数据列表。
- 检查普通用户路径是否只显示推荐选项，高级选项不挤占主界面。
- 若功能边界稳定，更新相关 `ARCHITECTURE.md`。

## 19. 归档口径

本计划完成并验收后再归档：

- 已完成的执行记录可移入 `docs/archive/`，文件名建议为 `multi-provider-api-support-plan.completed.zh_CN.md`。
- 稳定下来的长期事实同步到相关 `ARCHITECTURE.md`；只有明确需要长期约束 Codex 行为时，再征得用户同意后更新 `AGENTS.md`。
- 不阻塞首版的可选增强已拆到 `docs/plans/TODO.zh_CN.md`，归档时计划书末尾不再保留开放 TODO。
