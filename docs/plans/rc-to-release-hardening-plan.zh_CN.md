# RC 到 Release 三部分收口计划（zh_CN）

> 本文档同时记录执行契约和当前检查点；具体实现事实仍以源码、CI 与 GitHub Release 为准。

- 计划阶段：`v1.0.0-rc` 到 `v1.0.0` Release 的执行中专项。
- 当前检查点：`v1.0.0-rc.2` 已于 2026-08-16 发布；B00-B06 已合并并删除分支，B07 正在准备稳定版。
- 可用性：继续作为稳定版准备与发布验收入口；计划在 `v1.0.0` 发布链路完成后归档。
- 最近整理日期：2026-08-29。
- 当前代码事实优先级：当前源码与构建配置 > `ARCHITECTURE.md` 与稳定参考文档 > 本计划与 TODO。

### 当前执行检查点

| 批次 | 状态 | 结果 |
| --- | --- | --- |
| B00 | 已完成（PR #18） | 固化本计划、串行分支与验收契约。 |
| B01 | 已完成（PR #19） | 锁定发布环境并接入 Release 预检、回归、包契约、健康检查和依赖库存门禁。 |
| B02 | 已完成（PR #20） | 关键 JSON/YAML 原子写入、单份有效备份与确认恢复链路落地。 |
| B03 | 已完成（PR #21） | 模型失败分类、拒绝样例版本归因与脱敏回归基础落地。 |
| B04 | 已完成（PR #22） | 更新包、外部运行时、Whisper 模型与原生音频请求大小和完整性保护落地。 |
| B05 | 已完成（PR #23） | 未签名披露、签名状态检查、SHA-256 和 GitHub artifact attestation 链路落地。 |
| RC.2 | 已发布（PR #24） | 锁定 Windows 构建、质量门禁、provenance 和 GitHub Release 发布均通过。 |
| RC.2 后续构建加固 | 已完成（PR #27、#28、Actions #33185134656） | PyInstaller 子进程隔离宿主机 `PATH`，正式构建在清理产物和打包前复核 Release 锁与目标工具链；最新 `main` 的 Windows Build 与打包态健康检查已通过。 |
| B06 | 已完成（PR #25） | 四语用户文档、默认 Prompt v2、发布相关 i18n 和第三方许可边界已进入主线，分支已删除。 |
| B07 | 执行中 | 维护者已接受跳过 RC.3 与未签名分发风险；在 `release/v1.0.0` 准备稳定版文本、版本元数据与最终门禁。 |

维护者已于 2026-08-29 明确接受跳过 RC.3、缺少新增真人 Windows/UI 与真实 Prompt 样例证据、
以及未使用 Authenticode 的分发风险，并授权准备 `v1.0.0`。这表示接受剩余风险，不表示这些人工项目已经通过；
计划仍需在稳定版 tag、GitHub Actions 和 GitHub Release 全部完成后归档。

## 1. 目的与范围

本计划统一分成三部分：

1. **文档与文本**：用户文档、四语状态与限制、CHANGELOG/Release 文案、i18n 文本清理、第三方声明，以及基于拒绝证据的 Prompt 文本调优。
2. **全自动验证**：Release 预检、Ruff/统一离线回归、构建可重建性、发布包契约、打包态健康检查、版本/i18n/文档/进度不变量和依赖库存漂移门禁。
3. **优化与完善**：数据耐久性、更新器与外部下载保护、原生媒体请求体保护、拒绝分类基础、签名与分发信誉。

此前确认的用户文档、数据耐久性、构建可复现性、签名与分发信誉、Prompt 安全误拒绝优化五个主题全部保留，只改变组织方式，不缩减验收边界。

目标不是把 CharaPicker 包装成成熟商业软件，而是让首个正式版具备清楚的用户承诺、可恢复的关键数据写入、可重建的发布环境、可解释的分发信任链、可持续验证的 prompt 拒绝优化流程，以及能在发布前自动阻断已知回退的仓库门禁。

## 2. 非目标

- 不在本专项接入本地模型真实推理。
- 不新增 OpenAI Responses、Gemini、Anthropic 等 API schema。
- 不重做提取、知识库或角色卡数据模型。
- 不大规模拆分 `core/extractor.py`、模型页或项目页。
- 不把项目改造成数据库应用，也不引入新的持久化依赖。
- 不承诺大模型永不拒绝、永不幻觉或对所有供应商输出一致。
- 不通过 jailbreak、隐藏意图、要求模型忽略安全策略等方式规避供应商安全边界。
- 不把代码签名证书、PFX、私钥、API Key 或用户素材提交到仓库。

## 3. 已确认决策

### 3.1 Release 范围

- RC 阶段冻结新功能，只处理本计划列出的收口项和验收中发现的 Release 阻断 bug。
- 1.0 的稳定含义是“现有工作流和数据边界形成首个可持续升级基线”，不是“生产级、零风险或无需人工复核”。
- 本计划中的文档、数据写入、构建和 prompt 调整不得静默改变四媒体类型、Extract Once、preview/full 隔离或角色卡 JSON 母本规则。

### 3.2 用户文档

- 根 README 和三份多语言 README 不维护精确当前版本号；精确版本、日期和差异继续以 GitHub Releases 与 `CHANGELOG.md` 为准。
- 当前阶段、稳定承诺、限制、数据风险、模型费用和签名状态属于用户需要知道的信息，必须使用直白文案。
- 简体中文是维护主版本；繁体中文、英语和日语同步检查核心状态与风险信息。
- `AGENTS.md` 的长期项目快照需要更新，但仍遵守其维护规则：实施者必须先说明修改内容和章节，并取得用户明确允许。

### 3.3 数据耐久性

- 关键 JSON/YAML 采用同目录临时文件加 `os.replace()` 的原子替换策略，不新增依赖。
- `config.yaml`、项目 `config.json` 和正式角色卡 `card.json` 属于不可简单再生的用户事实，需要比可再生提取产物更强的恢复保护。
- chunk、episode、season 和 run plan 等提取产物可以重新生成，但仍应避免留下半写入文件。
- 1.0 之后改变持久化 schema 时，必须提供兼容读取、迁移或明确失败提示，不得静默丢字段或覆盖旧数据。

### 3.4 构建可复现性

- Release 的第一目标是“可重建”：相同 tag、锁定依赖、已记录工具链和相同构建入口能够重建等价产物。
- 字节级一致作为第二层目标。未签名中间产物可以通过固定随机种子、构建时间源和 ZIP 元数据继续收敛；带可信时间戳的 Authenticode 签名产物不要求跨时间重复构建后 hash 完全相同。
- 日常开发依赖范围与官方 Release 锁定环境分开维护；不要求把 `requirements.txt` 改成只适用于单一 Windows 构建环境的完整锁文件。

### 3.5 签名与分发信誉

- SHA-256、签名、时间戳和构建溯源是不同层次的证明，不互相冒名。
- 即使暂时没有 Authenticode 证书，正式发布也必须提供精确来源、SHA-256、构建信息和“当前未签名”说明。
- 如果启用 Authenticode，主程序和独立更新器都必须签名并验证；签名发生在压缩与生成 SHA-256 之前。
- GitHub Actions 使用的第三方 action 应逐步固定到完整 commit SHA，避免发布流程依赖可移动 tag。

### 3.6 Prompt 安全误拒绝优化

- 目标是减少合法、授权、虚构素材的误拒绝，不是绕过模型安全规则。
- prompt 正文继续只维护在 `res/default_prompts.json`，统一通过 `utils.ai_model_middleware` 加载。
- 用户 prompt override 继续优先于默认 prompt；默认 prompt 更新不得静默覆盖用户自定义内容。
- 没有可复现样例时不做大幅全局改写；每次调整必须能追溯到 prompt purpose、供应商、模型和失败分类。

### 3.7 全自动验证边界

- “可全自动验证”指脚本和 CI 可以在没有人工点击、真实用户数据或付费模型调用的情况下给出确定的通过/失败结果；实现工作仍归第一或第三部分所有。
- 自动验证不等于自动发布。创建或移动正式 tag、推送、发布 GitHub Release、采购证书和接受最终产品风险仍需维护者明确授权。
- 自动门禁可以验证格式、结构、哈希、依赖清单、启动健康和已编码的不变量，但不能替代真人 UI 体验、真实素材质量判断、法律意见、SmartScreen 信誉积累或 Prompt 安全边界的最终判断。
- 横向加固默认不新增运行时依赖；若安全扫描或 SBOM 工具需要新增 CI 工具，实施前单独说明用途、版本、权限和替代方案。

### 3.8 分支、提交与 PR 串行协议

- “文档与文本”使用一个专用分支，内部按用户文档、Release 文案、i18n/声明文本和 Prompt 文本等独立关注点拆成小提交。
- “全自动验证”使用一个专用分支，内部按构建锁定、CI 门禁、Release 预检、发布包健康检查、确定性不变量和依赖库存拆成小提交。
- “优化与完善”不使用一个总分支；数据耐久性、拒绝分类、下载与请求保护、分发信誉分别使用独立分支。
- 同一时间只允许一个活动开发分支，不并行开发、不提前创建后续分支，也不使用多个 worktree 绕过串行约束。
- 每个分支从前一个 PR 合并后的最新 `main` 创建；分支完成后开 PR，等待检查通过并合并，再删除远端和本地分支。
- 只有确认前一个 PR 已合并、对应分支已删除且本地 `main` 已同步，才能创建下一个分支。
- 提交遵循 Conventional Commits 和 `git commit -s`；保持人类程序员风格的小提交，每个提交只表达一个可审查意图，并尽量在提交边界保持验证通过。
- 默认不 squash 这些小提交；PR 使用能保留提交历史的合并方式。若仓库设置只允许 squash，必须在合并前向用户说明。
- PR 评审修正继续提交到当前分支；不得另开修复分支，也不得在当前 PR 未结束时开始下一项。

## 4. 当前状态与目标状态

| 主题 | 当前状态 | Release 目标 |
| --- | --- | --- |
| 用户文档 | 四语 README、发布相关 UI 文案和 `AGENTS.md` 长期快照已对齐 1.0 RC 能力、限制、数据、费用、uv 开发构建环境与未签名边界 | 真人复核自然度，并在稳定 tag 前准备最终 `v1.0.0` changelog/Release 文案 |
| 数据耐久性 | 关键事实与可再生产物已迁移到原子写入；关键配置和正式角色卡保留单份有效备份与确认恢复路径 | 使用隔离旧项目完成人工打开、保存、重启与恢复验收 |
| 构建可复现性 | 官方 Release 已固定 Python patch、PyInstaller、Ruff、带 hash 依赖、action commit 和构建清单；RC.2 锁定构建通过 | 稳定 tag 继续复用同一门禁，并复核构建输入未漂移 |
| 签名与分发信誉 | RC.2 已发布 SHA-256、构建/依赖清单和 GitHub artifact attestation，并明确披露 Windows 程序未使用 Authenticode | 维护者决定稳定版是否接受未签名分发；有证书时再启用 Authenticode 与时间戳路径 |
| Prompt 安全误拒绝 | 失败分类和版本归因已落地；默认 Prompt v2 已加入中立、授权虚构素材与结构化索引边界及离线回归 | 用经授权真实样例复核拒绝改善、JSON 与证据质量，不承诺消除供应商拒绝 |
| 全自动验证 | PR、主分支和 tag 已运行 Ruff、统一离线回归、Release 预检、包契约、打包态健康与依赖库存门禁 | 保持门禁通过，并把无法自动判断的体验、法律与真实模型质量留给人工验收 |

## 5. 三部分执行结构

### 5.1 第一部分：文档与文本

负责内容：

- 四语 README 的 Release 状态、能力、限制、数据风险、费用风险和签名状态。
- `CHANGELOG.md`、GitHub Release 正文、校验说明和已知问题。
- i18n 中重复、过期或与当前功能冲突的用户可见文本。
- `THIRD_PARTY_NOTICES.md` 和素材/许可证声明的文字同步。
- 经过失败分类和样例验证后，对 `res/default_prompts.json` 做最小 purpose 级文本调整。

完成标准：文本事实与当前代码一致，四语风险等级一致，不承诺尚未实现的能力；所有可机械检查的内容交给第二部分验证。

对应里程碑：M01、M09，以及 M10 中的文档与 Release 文案收口。

### 5.2 第二部分：全自动验证

负责内容：

- Release 锁定环境、构建清单、两次构建比较和 CI 权限分层。
- Ruff、统一离线回归、版本/CHANGELOG/资产命名预检。
- 发布 ZIP 契约、禁止路径、SHA-256、构建清单和打包态健康检查。
- i18n 重复 key、Markdown 相对链接、四语状态、进度事件和依赖库存漂移检查。
- 对第三部分的数据写入、更新、下载、请求体和签名结果执行故障测试或自动验证。

完成标准：每项检查都有确定退出码和可读错误；PR、主分支和 tag 不能绕过 P0 门禁；验证不依赖真实用户数据、付费模型或人工点击。

对应里程碑：M04、M05、M11、M12、M14、M15，以及所有实现里程碑附带的自动回归。

### 5.3 第三部分：优化与完善

负责内容：

- 关键 JSON/YAML 原子写入、有限备份和损坏恢复边界。
- 更新包压缩体积上限、外部运行时/模型受控来源与 hash、原生音频编码前大小保护。
- 拒绝、unsupported、截断、解析和网络错误分类，以及 Prompt 版本归因基础。
- 无证书分发信誉基线、可选 artifact attestation 和有证书时的 Authenticode 路径。

完成标准：实现行为得到第二部分自动门禁覆盖；涉及证书、法律判断、真实 Prompt 安全边界和最终发布时，仍保留明确人工决策点。

对应里程碑：M02、M03、M06、M07、M08、M13，以及 M10 中的集成验收。

### 5.4 所有权规则

- 每项工作只指定一个主部分，避免把“实现”和“验证”重复记成两项功能。
- 第二部分可以验证第一、第三部分，但不替代文本审阅、证书决策、法律判断或真实素材验收。
- 三部分不得并行准备；执行顺序和分支边界以第 14 节为准。
- M10 只在 B01-B05 的 PR 已合并并删除后，随最后的 B06 文档与文本分支完成最终集成。
- 每个提交按可审查意图组织，不按文件数量机械拆分；测试与实现可以放在同一小提交中，以避免主历史长期保留故意失败的提交。

## 6. 详细规范 A：用户文档

### 6.1 文档事实分工

| 文档 | 负责内容 | 不负责内容 |
| --- | --- | --- |
| `README.md` | 项目定位、当前成熟度、主要能力、主要限制、用户风险入口 | 精确版本号、完整开发验收细节 |
| `docs/readme/README.*.md` | README 的繁中、英文、日文补充版本 | 独立产生与简中相冲突的产品承诺 |
| `CHANGELOG.md` | 精确版本、日期、用户可见变化和 Release 差异 | 长期架构规则 |
| `docs/reference/release-packaging.zh_CN.md` | 构建、资产命名、签名、校验、溯源和发布契约 | 临时 RC 测试记录 |
| `docs/reference/runtime-middleware.zh_CN.md` | 配置、隐私、日志、原子写入和 prompt 中间件边界 | 用户首页营销文案 |
| GitHub Release 正文 | 当前版本新增、修复、已知问题、签名状态和校验方式 | 替代仓库中的长期参考文档 |
| `AGENTS.md` | 稳定项目快照和长期工作规则 | 本专项进度和一次性验收日志 |

### 6.2 1.0 用户承诺

Release 前，用户文档至少说明：

- CharaPicker 是个人实验性质工具；1.0 表示首个稳定基线，不表示适合托付唯一重要资料。
- 官方二进制支持的平台和架构；源码运行所声明的 Python 范围。
- 云模型调用会产生费用、失败、拒绝和幻觉风险；重要角色事实需要人工复核。
- 本地模型推理尚未接线，不把下载器或 UI 占位写成已支持能力。
- PDF 首版不做 OCR，容器、7-Zip、FFmpeg、Whisper 和原生音视频能力的限制保持清楚。
- `config.yaml` 可能包含 API Key，目前保存在本地应用目录，不使用系统凭据库加密。
- `projects/` 是用户数据；更新器应保留它，但用户仍应在重要升级前自行备份。
- 官方下载入口只指向项目 GitHub Releases；如果二进制未签名，明确说明可能出现的系统信誉警告和 SHA-256 验证方式。

### 6.3 文档同步规则

- 修改“当前状态”“主要限制”“安装/构建入口”“许可证/签名状态”时，同步检查四种语言。
- 允许语言表达自然，不要求逐字翻译；不能改变风险等级和功能边界。
- 搜索并清理把当前状态误写成 beta 的句子，但保留发布规范中的 `beta` 示例和历史 changelog。
- `CHANGELOG.md` 的 `v1.0.0` 小节必须在 tag 前准备，包含 RC 之后的修复、已知限制和签名状态。
- 文档链接、相对路径和 UTF-8 编码纳入验证。

## 7. 详细规范 B：数据耐久性

### 7.1 数据分级

| 等级 | 数据 | 恢复策略 |
| --- | --- | --- |
| D0 不可简单再生 | `config.yaml`、项目 `config.json`、正式角色卡 `card.json`、用户选择的封面/裁剪信息 | 原子写入；保留最多一份最近有效备份；损坏时不静默覆盖 |
| D1 昂贵但可再生 | run plan、chunk/episode/season JSON、transcript、预处理 manifest | 原子写入；失败保留旧完整版本或明确缺失；不要求长期备份每次修订 |
| D2 派生产物 | Markdown、HTML、外部角色卡 JSON、Release 构建清单 | 临时文件后替换；失败可重新生成 |
| D3 临时/诊断 | preview 草稿、拒绝样例 cache、构建临时目录 | 可清理；仍不得留下被误读为成功的半文件 |

### 7.2 统一原子写入 helper

建议新增只依赖标准库的 `utils/atomic_io.py`，至少提供：

- `write_text_atomically(path, text, *, encoding="utf-8")`。
- `write_json_atomically(path, payload, *, trailing_newline=True)`。
- 同目录、不可预测或进程唯一的临时文件名，避免不同 worker 共用固定 `.updating` 文件。
- 写入后 flush，并在平台允许时执行 `os.fsync()`。
- 通过 `os.replace()` 完成最终切换。
- 成功和失败路径都清理本次创建的临时文件，不删除其他进程的临时文件。
- 异常继续抛给调用方；helper 不把写入失败伪装成成功。

`utils.material_preprocessing._write_json_atomically()` 的现有行为作为迁移参考，完成统一 helper 后移除重复实现或保留清楚的专项理由。

### 7.3 关键事实备份与恢复

- D0 文件在替换前，将最近一次可解析内容保存为同目录单份备份；不建立无限历史。
- 备份文件继续视为私有数据，不进入 release、日志、拒绝样例包或 Git 提交。
- `config.yaml` 的备份同样可能包含 API Key，文档必须说明不得分享应用目录；日志不能输出其内容。
- 主文件解析失败且备份有效时，应用不得静默把备份覆盖回主文件。应向用户说明：主文件损坏、可恢复版本位置、是否继续恢复。
- 主文件和备份都无效时，保留原文件并给出可读错误；不得自动创建空配置覆盖损坏内容。

### 7.4 迁移顺序

1. 为原子 helper 建立故障注入单测。
2. 迁移 `core.knowledge_base.write_json()`，让角色卡和知识库共用原子写入。
3. 迁移 `utils.state_manager.save_project_config()`。
4. 迁移 `utils.global_store.YamlFileGlobalStore._write()`。
5. 迁移拒绝样例、导出文本和其它用户可见小文件。
6. 检查仍然直接写入的路径，按 D0-D3 分类；不要机械改动媒体流式写入或大型二进制处理。

### 7.5 数据耐久性验收

- 在最终替换前模拟异常，旧文件仍然完整可读。
- 在临时文件写完后模拟 `os.replace()` 失败，旧文件不丢失，临时文件得到清理。
- 同一路径连续保存不会残留固定临时文件。
- 旧 `card.json` 的未知扩展字段仍能保留。
- 损坏主配置不会被空默认值静默覆盖。
- 用户删除项目、清理 raw、洁净提取和更新器替换目录的现有边界不因原子 helper 改变。

## 8. 详细规范 C：构建可复现性与验证

### 8.1 目标层级

| 层级 | 定义 | 1.0 要求 |
| --- | --- | --- |
| R1 可重建环境 | 能从 tag、锁文件和记录的工具链安装相同依赖集合 | 必须 |
| R2 可重建等价产物 | 相同入口产生结构、功能、依赖清单一致的包 | 必须 |
| R3 未签名产物字节稳定 | 在相同平台和时间源下，未签名 exe/zip hash 可重复 | 尽量实现并记录偏差 |
| R4 已签名产物字节稳定 | 含独立可信时间戳的最终签名包跨时间 hash 相同 | 不作为要求；以签名、manifest 和 provenance 验证 |

### 8.2 Release 依赖锁

- 保留 `requirements.txt` 和 `pyproject.toml` 的开发/源码兼容范围。
- 新增面向官方 Windows x64、指定 Python patch 的 Release 锁文件，例如 `requirements-release-windows-py312.txt`。
- 锁定直接依赖、传递依赖、PyInstaller 和必要构建工具的精确版本。
- 优先使用 pip hash-checking mode；若首轮暂不加入所有 wheel hash，必须在计划完成记录中说明剩余风险，不能把普通版本 pin 描述成完整供应链校验。
- Release CI 使用锁文件，不再单独安装当时最新的 PyInstaller。

pip 官方将精确版本 pin、hash-checking 和 wheelhouse 作为逐级增强的可重复安装手段；实施时按 [Repeatable Installs](https://pip.pypa.io/en/stable/topics/repeatable-installs/) 和 [`--require-hashes`](https://pip.pypa.io/en/stable/cli/pip_install/#cmdoption-require-hashes) 复核当前语法。

### 8.3 构建环境与时间源

- GitHub Actions 的 Python 使用经过验证的具体 patch 版本，不只写 `3.12`。
- 将 `windows-latest` 改为实施时仍受支持的非浮动 Windows runner 标签，或至少把 runner image 名称和版本写入构建清单。
- 设置固定 `PYTHONHASHSEED`。
- 从 tag 对应 commit 时间生成稳定 `SOURCE_DATE_EPOCH`，不使用执行时当前时间作为未签名构建内容的随机来源。
- 如继续使用 PowerShell `Compress-Archive` 无法满足 ZIP 顺序/时间稳定要求，改用标准库脚本按固定排序和规范时间生成 ZIP，不新增压缩依赖。
- PyInstaller 的可复现构建参数在实施时按官方 [Creating a Reproducible Build](https://www.pyinstaller.org/en/stable/advanced-topics.html#creating-a-reproducible-build) 复核。

### 8.4 构建清单

建议新增由 `scripts/` 生成的 `build-info.json`，包含：

- 应用版本、阶段、tag 和完整 commit SHA。
- 构建时间源，不记录本地绝对路径。
- Python、pip、PyInstaller 版本。
- Windows runner/image 标识与架构。
- Release 锁文件 SHA-256。
- 已安装依赖名称与版本。
- 主程序、更新器和最终 zip 的 SHA-256。
- `signed`、`signature_verified`、`attestation_generated` 状态。

构建清单不得包含环境变量值、token、证书路径、用户目录、API Key 或完整 GitHub secret 名称。

### 8.5 CI 门禁

官方 tag 发布顺序固定为：

```text
Ruff
  -> 统一离线回归
  -> 锁定环境安装
  -> Release 锁与目标工具链预检
  -> 隔离宿主 PATH 的 PyInstaller 构建
  -> 可选 Authenticode 签名
  -> 签名/结构验证
  -> 规范化压缩
  -> SHA-256 与 build-info
  -> 可选 artifact attestation
  -> GitHub Release
```

- 任一门禁失败，不发布 Release 附件。
- 相同 tag 连续执行两次干净构建，依赖清单和包结构必须一致。
- 如果最终 hash 不一致，先区分签名时间戳、ZIP 元数据、PE 时间戳和实际依赖差异，不直接把差异忽略。

## 9. 详细规范 D：签名与分发信誉

### 9.1 信任层级

| 层级 | 证明内容 | 局限 |
| --- | --- | --- |
| Git tag/Release 来源 | 产物来自项目官方仓库的一个版本入口 | 轻量未签名 tag 本身不能证明签名者身份 |
| SHA-256 | 用户下载内容与 Release 页列出的字节一致 | 同一账号被控制时，zip 与 checksum 可同时被替换 |
| Build manifest | 记录 tag、工具链、依赖和产物 hash | 清单自身仍需可信发布渠道或 attestation |
| GitHub artifact attestation | 建立 GitHub Actions 构建 provenance | 不等于 Windows Authenticode，也不自动消除系统信誉提示 |
| Authenticode | 证明 Windows 二进制签名发布者并检测签名后篡改 | 需要证书、私钥保护、续期和时间戳服务 |

GitHub 官方说明 artifact attestation 用于建立二进制等构建产物的 provenance；实施前按 [Artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations) 复核仓库可用性和权限。

### 9.2 无证书时的 1.0 最低基线

- 最终版只从官方 GitHub Release 分发，不提供来源不明的镜像链接。
- Release 同时发布 zip、同名 `.sha256` 和 `build-info.json`。
- Release 正文明确写“当前 Windows 二进制未使用 Authenticode 签名”，并提供 PowerShell SHA-256 校验命令。
- 保留源码 tag 与二进制版本对应关系。
- GitHub Actions 的 action 引用固定到经核对的完整 commit SHA；GitHub 官方将完整 SHA 作为 action 不可变引用的安全做法，实施时按 [Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use) 复核。
- 不把 SHA-256 文案写成“已验证发布者身份”。

### 9.3 有证书时的 Authenticode 路径

- 证书来源、主体名、有效期、续期责任和紧急吊销流程先由维护者确认。
- 私钥只进入受保护的 CI secret、硬件/云签名服务或隔离签名环境；不得写入仓库、构建日志、artifact 或 release 包。
- 使用 SHA-256 文件摘要和可信时间戳服务签名。
- 同时签名 `CharaPicker.exe` 与 `CharaPickerUpdater.exe`，以及后续新增的官方可执行文件。
- 在复制到 staging 和压缩前验证签名；压缩后再次解压抽检签名。
- 签名失败或验证 warning 都阻断正式发布，不允许自动降级为未签名包后继续发布。
- Microsoft SignTool 支持签名、验证和时间戳；实际参数以发布时的 [SignTool 文档](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool) 与 [Authenticode 时间戳说明](https://learn.microsoft.com/en-us/windows/win32/seccrypto/time-stamping-authenticode-signatures) 为准。

### 9.4 更新器与签名

- 无证书阶段继续依赖 HTTPS、精确资产名、SHA-256、包结构检查和 GitHub Release 来源。
- 启用稳定 Authenticode 发布者后，再评估在更新安装前验证新包主程序和更新器的签名与发布者身份。
- 更新器签名验证不得替代现有 SHA-256、路径穿越、大小限制、备份和回滚保护。
- 如果发布者证书更换，需要设计允许的证书迁移窗口，不能把旧安装永久锁死在单一证书指纹。

## 10. 详细规范 E：Prompt 安全误拒绝文本与分类

### 10.1 优化边界

允许的优化：

- 明确任务是授权素材的中立理解、索引、摘要和结构化提取。
- 对虚构作品中的敏感情节使用克制、非刺激、非操作性的高层概括。
- 明确不续写、不角色扮演、不美化、不提供违法、自伤、暴力或性内容操作细节。
- 证据不足时输出未知、未确认或需人工复核。
- 把结构化提取、JSON 约束和证据定位写清楚。

禁止的优化：

- 要求模型忽略、绕过、关闭或隐藏安全策略。
- 通过编码、分片、暗示或伪装意图诱导模型输出原本不应生成的内容。
- 把供应商能力不支持、网络错误、token 截断或 JSON 解析失败都归类为安全拒绝。
- 为降低拒绝率而删除证据约束、扩大自由创作空间或弱化未成年人等高风险内容边界。

### 10.2 失败分类

拒绝优化前先把失败分为：

- `provider_policy_refusal`：供应商明确返回安全/策略拒绝。
- `model_text_refusal`：HTTP 成功，但模型文本拒绝执行合法提取。
- `unsupported_capability`：模型或 API schema 不支持该媒体输入，不算安全拒绝。
- `output_truncated`：输出 token 或上下文预算导致截断。
- `json_parse_failure`：模型已回答但结构不合法。
- `transport_or_auth_failure`：网络、鉴权、限流或服务错误。
- `user_override_regression`：用户 prompt override 导致旧模板、缺变量或边界变化。
- `content_requires_manual_review`：模型合理拒绝或素材确实不适合自动展开，不强行消除。

只有前两类进入“安全误拒绝 prompt 调优”主队列。

### 10.3 样例和版本归因

- 继续使用 `projects/{project_id}/cache/refusal_samples/` 保存脱敏失败记录，不自动上传。
- 不把真实用户样例、素材、完整 prompt 或完整模型响应提交到仓库。
- 新增可提交的合成/脱敏最小回归样例时，放在 `tests/fixtures/` 或验证脚本专用目录，不放真实作品片段。
- `res/default_prompts.json` 的 `version` 在默认 prompt 发生语义调整时递增。
- 拒绝样例增加默认 prompt resource version、有效 prompt 来源（default/override）和必要的模板摘要 hash；不记录 prompt 正文。
- 相同样例复跑时记录应用版本、provider、backend、model、prompt purpose、temperature/结构化输出设置和结果分类。

### 10.4 调优流程

1. 收集可复现失败，确认不是 unsupported、token、网络或解析问题。
2. 按 prompt purpose 聚类，不先改全局共用语气。
3. 建立修改前基线：拒绝分类、JSON 可解析性、证据质量、token 用量和耗时。
4. 只生成最小 prompt patch，先检查是否属于项目特定 user override。
5. 对合成样例和已获授权样例复跑。
6. 确认拒绝下降没有带来更多幻觉、越界扩写、JSON 失败或角色错配。
7. 开发者确认后修改 `res/default_prompts.json`，不得由工具静默应用。
8. 记录变更目的、受影响 purpose、验证模型和已知供应商差异。

### 10.5 验收指标

- 已确认的合法误拒绝样例不再无解释地失败；仍失败时标记供应商限制或人工复核原因。
- `provider_policy_refusal` 与 unsupported、transport、parse failure 的统计不混淆。
- 现有离线回归和 JSON 解析约束全部通过。
- 输出继续只基于素材，不新增剧情，不把敏感内容扩写成刺激性细节。
- prompt 调整后 token 用量没有无边界增长；明显增长必须解释收益。
- 用户 override 存在时，UI/失败样例能够说明实际使用了 override，避免把旧自定义模板问题误判为默认 prompt 回退。

### 10.6 Release 与持续维护边界

- Release 前：建立分类与基线，处理当前已知且可复现的合法误拒绝，不要求穷尽所有未来模型变化。
- Release 后：继续按真实样例小步更新；供应商模型升级导致的新拒绝进入同一流程。
- 没有新样例时，不因“可能更安全”而持续膨胀所有 system prompt。

## 11. 详细规范 F：跨部分自动化与加固清单

### 11.1 审计结论与优先级

| 批次 | 自动化工作 | 当前缺口 | Release 优先级 | 自动化边界 |
| --- | --- | --- | --- | --- |
| A01 | Release 预检与 CI 最小权限门禁 | `.github/workflows/build.yml` 只在手动或 tag 构建；不运行 Ruff 和统一离线回归，整个 job 持有 `contents: write` | P0 | 可完整实现和验证；实际 push/tag 仍需授权 |
| A02 | 发布包契约与打包态健康检查 | 构建后只生成 ZIP/SHA-256，没有检查包根目录、必需文件、私有路径、缺失 DLL/资源或可执行文件启动 | P0 | 可在隔离目录和 CI 中自动完成；不等于真人 UI 验收 |
| A03 | 更新器、外部下载与原生媒体请求保护 | 更新包有 SHA-256、成员数和解压体积保护，但没有压缩包下载上限；FFmpeg、whisper.cpp、Whisper 模型和 llama.cpp 使用可变来源且没有内容 hash 校验；原生音频会在中间件直接读入并 Base64 编码，缺少请求体前置上限 | P0 | 可实现上限、固定来源、hash、降级 warning 和故障测试；上游换版仍需维护清单 |
| A04 | i18n、文档、版本和进度不变量 | i18n 校验在 JSON 解析后比较 key，无法发现重复 key；当前已有重复 `project.inputFormat.7z` 和过期 placeholder；文档/版本检查未形成门禁 | P1 | 可自动清理并建立确定性校验；自然语言质量仍需人工抽读 |
| A05 | 依赖、许可证和发布清单漂移检查 | 依赖范围、打包环境和第三方声明依靠人工同步；无机器可读依赖库存 | P1 | 可自动生成库存并检查遗漏；不能自动作出法律结论或修复所有漏洞 |

当前本地基线已经验证：`scripts/validate_multi_material_regression.py` 全部通过，其中 `unittest` 发现并通过 49 个测试；Ruff 同样通过。因此 A01 的主要工作不是修复现有失败，而是把已经存在且有效的验证变成每次 PR、主分支和 tag 都不能绕过的门禁。

### 11.2 A01：Release 预检与 CI 门禁

- 新增只读的 `quality` workflow，覆盖 pull request、主分支 push 和手动触发，运行 Ruff、统一离线回归和 Release 静态预检。
- tag 发布必须依赖质量 job 成功；测试/构建 job 使用 `contents: read`，只有最终发布 job 获得 `contents: write`。
- 为 workflow 设置合理的 `timeout-minutes` 和同 ref `concurrency`，防止重复 tag 构建并发发布或无边界占用 runner。
- 新增 `scripts/validate_release_readiness.py`，验证 tag 语法、`utils/app_metadata.py`、`pyproject.toml`、`build.bat`、CHANGELOG 小节、正式版资产命名、四语状态和禁止跟踪的运行时路径。
- 保留现有 `scripts/build_meta.py` 作为构建参数事实来源；Release 预检复用其解析逻辑，不复制一套版本规则。

### 11.3 A02：发布包契约与打包态健康检查

- 新增 `scripts/validate_release_artifact.py`，验证 ZIP 只有一个 `CharaPicker/` 顶层目录，并包含 `CharaPicker.exe`、`CharaPickerUpdater.exe`、README、LICENSE、第三方声明、i18n 和运行资源。
- 明确禁止发布包包含 `.git/`、`.codex/`、`projects/`、`config.yaml`、`log/`、本地 `bin/`、本地 `models/`、证书、密钥和构建临时目录。
- 校验 ZIP 名称、SHA-256 文件、`build-info.json` 与实际内容一致；清单不得泄漏绝对路径或环境变量值。
- 为主程序增加无网络、无用户数据写入的打包态健康检查入口，只验证 Python/Qt 启动、核心模块导入、i18n/default prompt/图标资源可读和应用版本一致，然后以确定退出码结束。
- CI 将发布包解压到含空格和非 ASCII 字符的临时路径执行健康检查，覆盖 Windows 路径与运行根目录回退。
- 更新器继续通过隔离临时目录验证替换、用户数据保留、启动确认和回滚；不接触真实安装目录。

### 11.4 A03：更新器、外部下载与原生媒体请求保护

- 为更新包同时检查 GitHub asset `size`、HTTP `Content-Length` 和实际流式下载字节数；任一超过压缩包上限都中止并清理工作区。
- checksum 小文件使用独立的小上限，避免用相同大上限掩盖异常响应。
- 为 FFmpeg、whisper.cpp runtime、Whisper 模型和 llama.cpp 增加按用途区分的下载大小上限、允许的 HTTPS host 和实际流式字节计数。
- 把 `latest` API 与 Hugging Face `/main/` 的可变输入改为受控版本清单；记录上游版本、资产名、URL 和 SHA-256。下载后先校验 hash，再解压或安装。
- 若某上游不发布可验证 checksum，由项目清单固定已审核资产的 SHA-256，并把换版作为显式代码审查，而不是运行时自动信任新资产。
- 在 `utils.ai_model_middleware` 读取和 Base64 编码原生音频前执行大小检查；超过当前 provider/backend 的保守上限时不构造请求体，保留 transcript 主路径并返回可解释 warning。
- 原生视频继续按当前 DashScope 文件引用/采样路径处理；如后续 backend 会内联文件，再复用同一请求体保护，不新增第五种媒体类型。
- 保持现有路径穿越、成员数量、解压体积、临时目录、取消和更新回滚保护；新增保护不能替代旧保护。
- 为缺少 `Content-Length`、伪造较小 header、下载中途超限、hash 不符、原生音频超限、取消和安装失败建立故障测试。

### 11.5 A04：确定性仓库不变量

- 扩展 `scripts/validate_i18n_keys.py`，使用保留键对的 JSON 解析方式直接拒绝重复 key，再比较四语 key 集合。
- 删除或更新未引用的 `project.processing.placeholder.*`，清理四语重复 `project.inputFormat.7z`，并让回归能防止重新引入。
- 新增 Markdown 相对链接和四语“当前状态/主要限制”一致性检查；历史 changelog 和构建示例不因关键字扫描被误判。
- 为进度事件增加信号级不变量：进度单调、完成才可到 100%、前置失败和取消不得显示成功完成。该测试不评价动画或视觉舒适度。
- 将版本元数据、CHANGELOG、资产文件名、更新器解析规则和 Release workflow 的一致性放入同一预检入口。

### 11.6 A05：依赖与许可证库存

- 从 Release 锁定环境生成机器可读的依赖名称、版本、来源和许可证 metadata，作为 `build-info.json` 的派生清单或独立库存文件。
- 自动检查 `requirements.txt` 与 `pyproject.toml` 的直接依赖集合没有无解释漂移，所有直接运行时依赖在 `THIRD_PARTY_NOTICES.md` 中都有条目。
- 发布包继续强制包含 `LICENSE` 和 `THIRD_PARTY_NOTICES.md`；依赖升级导致库存变化时让 CI 给出明确 diff。
- 机器读取的许可证 metadata 只用于发现遗漏，不自动断言分发已满足 GPL、MPL、Qt 或其它许可证义务。
- 漏洞数据库扫描可以作为独立报告接入，但是否阻断 Release 需要固定严重度、忽略到期时间和误报处理规则；在规则确认前不把漂移扫描冒充完整安全审计。

### 11.7 明确不能全自动收口的事项

- Authenticode 证书采购、主体认证、私钥托管方式和 SmartScreen 信誉积累。
- 最终 `v1.0.0` tag、push 和 GitHub Release 发布决定。
- 四语文案的自然度、真人 UI 体验、干净 Windows 上的系统信誉提示和真实素材质量验收。
- 真实 Prompt 拒绝样例是否属于合理安全拒绝，以及调优后的语义边界是否可接受。
- 第三方素材来源证明、GPL/Qt 等许可证履约方式和正式法律判断。

## 12. 三部分里程碑

| 部分 | 里程碑 | 主要结果 |
| --- | --- | --- |
| 第一部分：文档与文本 | M01、M09 | 四语用户文档、Release 文案和经过证据验证的 Prompt 文本收口 |
| 第二部分：全自动验证 | M04、M05、M11、M12、M14、M15 | 锁定构建、CI 门禁、发布包健康检查、确定性不变量和依赖库存 |
| 第三部分：优化与完善 | M02、M03、M06、M07、M08、M13 | 数据耐久、分发信誉、拒绝分类和下载/请求安全加固 |
| 最终集成 | M10 | 三部分汇合后的完整 RC→Release 验收 |

里程碑编号保留既有引用，不代表跨部分的强制顺序；执行时以所属部分和依赖关系为准。

### M01：1.0 用户文档契约

交付：

- 修正四语 README 当前阶段和主要限制。
- 起草 `v1.0.0` changelog/Release 正文结构。
- 在用户可见文档中说明数据备份、API Key、本地模型、模型风险和签名状态。
- 按维护策略提出 `AGENTS.md` 更新内容，取得用户允许后再修改。

验收：

- 四语核心事实一致。
- README 不维护精确版本号。
- 历史 beta 记录和发布参数示例没有被误删。

边界：

- 不把实验项目写成生产工具。
- 不在文档中承诺尚未完成的签名、原子写入或本地模型能力。

### M02：原子写入基础与故障测试

交付：

- 新增标准库原子写入 helper。
- 覆盖写入、替换失败、临时文件清理和并发临时名测试。
- 替换素材预处理中的重复 helper 或记录保留理由。

验收：

- 故障发生时旧文件保持完整。
- helper 不吞掉异常，不记录数据正文。

边界：

- 不修改项目目录结构和 JSON schema。

### M03：关键事实与知识库写入迁移

交付：

- 迁移项目配置、全局配置、角色卡、知识库和拒绝样例写入。
- 为 D0 文件加入单份有效备份与损坏恢复提示。
- 增加旧角色卡扩展字段和旧项目配置回归 fixture。

验收：

- 旧项目和角色卡能加载、保存、重启后再加载。
- 损坏主文件不会被空默认值覆盖。
- preview/full、run 隔离和角色卡母本路径不变。

边界：

- 不备份完整 `raw/`、`materials/` 或全部知识库历史。

### M04：Release 锁定环境

交付：

- 新增 Windows x64/Python 3.12 Release 锁文件。
- 固定 Python patch、PyInstaller 和传递依赖。
- Release CI 只通过锁文件安装构建依赖。

验收：

- 两次干净安装得到相同依赖清单。
- 依赖 hash 缺失时有明确未完成记录，不能静默降级。

边界：

- 不把日常 `requirements.txt` 限死为单一 Release 环境。

### M05：可重建构建与 CI 门禁

交付：

- 设置稳定随机种子和构建时间源。
- 新增无敏感信息的 `build-info.json`。
- 将 Ruff、统一离线回归和包结构检查放在发布前。
- 固定 GitHub Actions action 引用并记录 runner image。

验收：

- 同 tag 两次构建的依赖清单和包结构一致。
- 构建差异能归因到签名、时间戳、ZIP 元数据或真实依赖变化。
- 门禁失败不创建 GitHub Release。

边界：

- 不为了 hash 相同而删除必要的签名时间戳。

### M06：无证书分发信誉基线

交付：

- Release 同步生成 zip、`.sha256`、build manifest。
- Release 正文说明官方来源、校验方式和当前签名状态。
- 评估并接入可用的 GitHub artifact attestation。

验收：

- 用户可以从 Release 页面确认 tag、hash 和构建信息。
- 文案不把 checksum、attestation 和 Authenticode 混为一谈。

边界：

- 不把 artifact attestation 写成 Windows 发布者签名。

### M07：Authenticode 决策与条件实施

交付：

- 记录是否为 1.0 获取证书，以及证书保管和续期责任。
- 若启用，签名并验证主程序和更新器，加入可信时间戳。
- 若不启用，完成未签名披露，不用临时自签名证书冒充公开信誉。

验收：

- 签名路径失败时发布中止。
- 未签名路径的 Release 页面不制造“已签名”印象。

边界：

- 不在仓库或普通 artifact 中保存私钥/PFX。

### M08：拒绝分类与基线

交付：

- 统一失败分类，分离拒绝、unsupported、token、parse 和 transport。
- 为拒绝样例补充 prompt resource version 和有效 prompt 来源。
- 建立合成/脱敏的 purpose 级最小回归集。

验收：

- 已知失败可以归入明确类别。
- 回归数据不包含用户原始隐私内容。

边界：

- 本里程碑不修改默认 prompt 正文。

### M09：定向 Prompt 调优

交付：

- 对确认的合法误拒绝做最小 purpose 级 patch。
- 增加修改前后复跑记录。
- 必要时生成 user override 建议，再判断是否有通用价值。

验收：

- 已知误拒绝改善，JSON、证据和安全边界不回退。
- 默认 prompt 修改由开发者确认，不自动应用。

边界：

- 不使用安全规避指令。
- 不把所有失败都归因于 prompt。

### M10：集成验收与 Release 准备

交付：

- 运行全量离线验证、干净构建、包结构和签名/未签名路径检查。
- 使用隔离测试项目验证配置、角色卡和更新保留。
- 完成 `v1.0.0` changelog、Release 正文和最终文档同步。
- 汇总 M11-M15 的自动化门禁结果；用户验收通过后，将本计划移入 `docs/archive/` 并同步 TODO。

验收：

- 五个主工作流和五个横向自动化批次均有结果记录和未解决风险。
- 当前 tag 构建可启动，用户数据保持，Release 门禁生效。

边界：

- 验收发现的行为 bug 回到对应里程碑修复，不塞入归档收尾。

### M11：Release 预检与 CI 权限分层

交付：

- 新增 Release 静态预检脚本和只读质量 workflow。
- tag 构建依赖 Ruff、统一离线回归和预检成功。
- 测试/构建与发布 job 分离，只有发布 job 持有写权限。

验收：

- 构造版本、CHANGELOG、tag 或 README 状态不一致时，预检稳定失败并指出具体文件。
- PR 与主分支不创建 Release，tag 门禁失败不上传正式附件。

边界：

- 不自动创建 tag、push 或发布 Release。

### M12：发布包契约与打包态健康检查

交付：

- 新增 ZIP/清单/禁止路径验证脚本。
- 新增主程序的无网络健康检查入口。
- 在含空格和非 ASCII 字符的临时路径完成打包态检查。

验收：

- 删除任一必需文件、注入任一禁止路径或篡改清单/hash 时验证失败。
- 健康检查能发现资源、模块、Qt 初始化或版本不一致，并以非零状态退出。

边界：

- 健康检查不创建用户项目、不调用模型，也不替代真人 UI 验收。

### M13：下载、更新与原生请求链路保护

交付：

- 增加更新 ZIP/checksum 的下载上限和故障测试。
- 为 FFmpeg、whisper.cpp、Whisper 模型和 llama.cpp 增加受控来源、大小上限和 hash 校验。
- 为原生音频内联请求增加编码前大小保护和 transcript 降级 warning。
- 更新稳定参考文档中的下载信任边界。

验收：

- 无长度 header、伪造长度、流式超限和 hash 不符均在安装前失败并清理临时文件；原生音频超限不会读入完整请求体。
- 原有取消、路径穿越、解压上限、用户数据保留和回滚测试继续通过。

边界：

- 不自动信任新 upstream `latest` 资产；换版必须修改受审查清单。

### M14：i18n、文档、版本与进度不变量

交付：

- i18n 校验可发现重复 key，并清理当前重复和过期 placeholder。
- 增加相对链接、四语状态、版本/CHANGELOG/资产命名一致性检查。
- 增加进度单调、失败/取消不显示完成的信号级测试。

验收：

- 故意插入重复 key、坏链接、版本错配或错误完成事件时，对应门禁稳定失败。
- 历史 changelog 与 beta 构建示例不会被当前状态检查误伤。

边界：

- 不用自动测试评价翻译自然度或 UI 动画观感。

### M15：依赖与许可证库存漂移

交付：

- 生成 Release 依赖库存并纳入构建清单或独立 artifact。
- 校验直接依赖集合和第三方声明覆盖关系。
- 对依赖升级输出可审查 diff。

验收：

- 新增直接依赖却未更新项目元数据或第三方声明时门禁失败。
- 库存不包含 token、用户目录、环境变量值或私有下载地址。

边界：

- 不把 package metadata 当作正式法律意见，也不自动接受许可证风险。

## 13. 验证与自审查

基础验证：

```powershell
uv run --locked python scripts\validate_multi_material_regression.py
uv run --locked ruff check .
uv run --locked python -m compileall -q core gui utils scripts tests main.py app_updater.py
```

横向自动化实施后增加：

```powershell
uv run --locked python scripts\validate_release_readiness.py
uv run --locked python scripts\validate_release_artifact.py --archive release\<archive>.zip
```

专项验证至少包含：

- 原子写入故障注入单测。
- 旧项目配置与旧角色卡 fixture。
- 四语 README 状态和链接检查。
- Release 锁文件的两次干净安装比较。
- 相同 tag 的两次构建 manifest/目录清单比较。
- 有证书时执行 SignTool verify；无证书时验证 Release 披露与 hash 命令。
- 提示词合成样例离线格式检查，以及经过用户授权的真实供应商复跑。
- 更新与外部运行时下载的 header/流式超限、hash 不符、取消和清理故障测试，以及原生音频编码前大小保护测试。
- 含空格和非 ASCII 路径的打包态健康检查。
- i18n 重复 key、Markdown 坏链接、版本错配和进度错误完成事件的负向 fixture。
- Release 依赖库存与 `THIRD_PARTY_NOTICES.md` 直接依赖覆盖检查。

每个提交分组前自审查：

- 当前分支名称、顺序和范围是否与第 14 节一致，上一个 PR 与分支是否已经完全收尾。
- 提交是否保持单一意图、包含 Signed-off-by，并且没有混入下一分支的工作。
- 是否改变了四媒体类型、run plan、preview/full 或角色卡母本边界。
- 是否把用户数据、API Key、prompt 正文、模型响应或证书内容写入日志/构建清单。
- 是否新增业务代码硬编码 prompt。
- 是否让 GUI 直接承担文件写入、签名或构建业务逻辑。
- 是否引入了新依赖；若有，先停止并向用户说明。
- 是否同步必要 i18n、架构说明和稳定参考文档。
- 是否把 checksum、签名、时间戳和 provenance 混为同一概念。
- PR 是否保留小提交历史；若平台只能 squash，是否已取得用户确认。

## 14. 串行分支与小提交计划

### 14.1 固定执行顺序

| 顺序 | 分支 | 所属部分 | 覆盖内容 | 状态 |
| --- | --- | --- | --- | --- |
| B00 | `docs/rc-release-plan` | 计划固化 | 只提交本计划及其索引；这是实施前的计划 PR，不计入第一部分产品文档分支 | 已合并 PR #18，分支已删除 |
| B01 | `release/v1-automated-validation` | 第二部分：全自动验证 | M04、M05、M11、M12、M14、M15 | 已合并 PR #19，分支已删除 |
| B02 | `release/v1-data-durability` | 第三部分：优化与完善 | M02、M03 | 已合并 PR #20，分支已删除 |
| B03 | `release/v1-refusal-classification` | 第三部分：优化与完善 | M08 | 已合并 PR #21，分支已删除 |
| B04 | `release/v1-download-hardening` | 第三部分：优化与完善 | M13 | 已合并 PR #22，分支已删除 |
| B05 | `release/v1-distribution-trust` | 第三部分：优化与完善 | M06、M07 | 已合并 PR #23，分支已删除 |
| B06 | `release/v1-docs-text` | 第一部分：文档与文本 + 最终集成 | M01、M09 和 M10 的可自动执行部分；计划归档和稳定版本元数据受人工门槛约束 | 已合并 PR #25，分支已删除 |
| B07 | `release/v1.0.0` | 稳定版准备 | 稳定版状态文本、CHANGELOG、版本元数据、最终门禁与候选包验证 | 执行中 |

选择这个顺序的原因：先让自动门禁保护后续实现；优化分支逐项进入 `main`；文档与文本最后根据已经合并的代码写当前事实，并在拒绝分类完成后决定是否调整 Prompt。B06 合并后才进入 tag/Release 决策。

B00 是当前规划工作的必要例外。它只把执行契约放入仓库，不提前修改 README 产品承诺、Prompt 或版本状态；B01-B06 仍严格满足用户规定的三部分分支策略。

### 14.2 每个分支的通用生命周期

1. 确认没有未结束的上一个 PR，远端和本地上一个分支都已删除。
2. 切换到 `main`，拉取最新远端状态，并确认工作区干净。
3. 从最新 `main` 创建本节规定的唯一当前分支；不得同时创建下一分支。
4. 按该分支的小提交清单实现，每次提交使用 Conventional Commits 和 `git commit -s`。
5. 运行该分支要求的局部验证；准备 PR 前再运行统一离线回归、Ruff 和适用的 Release 门禁。
6. push 当前分支并创建 PR；PR 标题说明所属部分，正文列出提交、验证、风险和人工验收点。
7. 修正 CI 或 review 反馈时继续提交到当前分支，直到检查通过且没有未解决的阻断反馈。
8. 使用保留小提交历史的方式合并 PR；默认不 squash。
9. 确认 PR 已合并后删除远端分支；切回 `main` 后删除本地分支并同步最新 `main`。
10. 再次确认工作区干净、上一个分支不存在，才能开始下一顺序分支。

如果 PR 无法合并、CI 未通过、review 未解决或分支删除未完成，流水线保持在当前分支，不得以新分支继续开发。

### 14.3 B00：计划固化分支

建议小提交：

```text
docs: plan v1 release hardening
```

只包含 `docs/plans/rc-to-release-hardening-plan.zh_CN.md` 及必要索引更新。当前工作区中的这批计划文件必须先归入该分支，不能直接提交到 `main`。

### 14.4 B01：全自动验证分支

建议按以下可审查意图拆分，实际文件高度耦合时允许合并相邻两项，但不得做成一个总提交：

```text
build: pin v1 release dependencies
build: record release environment metadata
ci: enforce release quality gates
test: validate release metadata consistency
test: validate packaged release artifacts
test: enforce repository release invariants
build: audit release dependency inventory
```

分支完成条件：PR、主分支和 tag 的门禁权限与依赖关系正确；本地统一离线回归、Ruff、负向 fixture 和一次干净构建验证通过。

### 14.5 B02：数据耐久性分支

建议小提交：

```text
fix: add atomic file write primitives
fix: harden knowledge base writes
fix: preserve critical configuration backups
test: cover persistent data recovery
docs: document persistent data recovery
```

测试和对应实现优先放在同一个小提交或相邻的可通过提交中，不在 PR 历史中长期保留故意失败的测试提交。

### 14.6 B03：拒绝分类分支

建议小提交：

```text
fix: classify model refusal failures
fix: attribute refusal samples to prompt versions
test: cover refusal classification boundaries
docs: document refusal evidence handling
```

本分支不改默认 Prompt 正文，不提交真实用户素材、完整 prompt 或完整模型响应；Prompt 文本调整留到 B06。

### 14.7 B04：下载与请求保护分支

建议小提交：

```text
fix: limit automatic update downloads
fix: verify downloaded runtime artifacts
fix: pin whisper model artifacts
fix: guard native audio request size
test: cover download integrity failures
docs: document runtime download trust
```

上游版本、URL、大小上限和 hash 属于同一资产策略，但 FFmpeg、whisper.cpp/模型、llama.cpp 与更新器仍按独立关注点提交，避免一笔提交混入所有下载器。

### 14.8 B05：分发信誉分支

建议小提交：

```text
build: pin release workflow actions
build: add release provenance checks
build: verify release executable signatures
docs: document release trust boundaries
```

没有证书时不创建伪公开信誉的自签名路径；第三个提交只在真实 Authenticode 条件已满足时存在。无证书基线、attestation 和校验失败阻断仍可完成本分支。

### 14.9 B06：文档与文本及最终集成分支

建议小提交：

```text
docs: align v1 release status and limitations
docs: prepare v1 release notes and trust guidance
fix: clean up release-facing translations
fix: tune extraction prompts from refusal evidence
docs: update v1 third-party notices
docs: archive completed v1 release plan
chore: promote v1.0.0 release
```

Prompt 提交是条件项：只有 B03 已提供明确分类且存在可复现的合法误拒绝证据时才执行；没有证据就不做语义性改写，并在 Release 记录中说明。B06 已完成可自动执行的收口；维护者于 2026-08-29 接受剩余人工风险并授权进入 B07。版本提升提交仍必须最后发生，且提交前所有自动门禁通过；计划在稳定版发布链路完成后归档。

### 14.10 PR 合并和删除验收

- PR 必须能追溯到一个且仅一个计划分支；不把两个分支的内容塞进同一 PR。
- PR 默认保留小提交，不使用 squash；若平台强制 squash，先取得用户确认。
- 合并完成以远端 PR 状态和 `main` 包含对应提交为准，不能只凭本地命令成功判断。
- 删除顺序为远端分支后本地分支；本地删除前必须已切回 `main`，并核对目标就是已合并分支。
- 上一分支的 PR、合并提交和删除结果在开始下一分支前简短汇报。
- B06 已合并并删除，维护者已授权准备稳定版；B07 仍须先完成 PR、检查、合并与分支删除，再进入 `v1.0.0` tag 和 GitHub Release 阶段。

## 15. 用户验收流程

### 15.1 文档与文本验收

1. 阅读四语文档的简中主版本，确认 1.0 承诺、限制、签名状态和风险说明符合预期。
2. 检查 CHANGELOG/Release 正文、第三方声明和 i18n 文本没有把计划能力写成已实现。
3. 用经授权样例复跑已知安全误拒绝，确认 Prompt 调整改善拒绝且输出仍为可解析、可追溯 JSON。

### 15.2 全自动验证验收

1. 查看 CI 门禁记录，确认 Ruff、统一离线回归、Release 预检、发布包契约、健康检查和依赖库存全部通过。
2. 从锁定环境构建两次，比较 build manifest、依赖库存和包结构。
3. 抽查一个负向 fixture，确认坏版本、坏链接、重复 i18n key、坏 ZIP 或 hash 不符会得到非零退出码。

### 15.3 优化与完善验收

1. 用旧项目副本打开、保存并重新启动，检查项目和角色卡数据；模拟写入失败，确认旧文件与备份可恢复。
2. 抽查 FFmpeg、Whisper 或更新包的一个故障 fixture，确认超限/hash 不符不会进入安装阶段。
3. 检查 Release 候选 ZIP、SHA-256、build manifest 和签名状态；若启用 Authenticode，在干净 Windows 环境查看主程序和更新器签名详情。
4. 完成一次打包态启动、项目读写、角色卡导出和更新保留验收。

三部分均通过后，维护者再决定是否创建 `v1.0.0` tag 和发布 GitHub Release。

## 16. 验收后收尾

只有 M01-M15 完成、用户试用通过且已知阻断 bug 修复后，才进行：

- 删除临时构建比较目录、签名测试证书、测试项目副本和一次性日志。
- 确认仓库未混入 `projects/`、`config.yaml`、真实拒绝样例、PFX 或构建 secret。
- 把仍需长期跟踪的 prompt 拒绝、证书续期或字节级复现问题迁入 `TODO.zh_CN.md`。
- 将本文移入 `docs/archive/`，补充完成日期、验证命令和未解决风险。
- 更新 `docs/plans/README.md`、`docs/README.md` 和必要架构索引。
- 最后准备 `v1.0.0` tag 与 GitHub Release；收尾阶段发现行为 bug 时回到对应里程碑。

## 17. 实施前复核点

- Authenticode 证书是否已经取得，以及私钥适合放在何种签名环境；没有证书时走明确的无证书基线，不阻塞其它里程碑。
- GitHub artifact attestation 对当前公开仓库、Actions 权限和 Release 资产是否可用。
- 发布时仍受支持的 Windows runner 标签、Python patch、PyInstaller 版本和 action commit SHA。
- FFmpeg、whisper.cpp、Whisper 模型与 llama.cpp 选定上游版本是否仍可下载，以及上游是否提供可复核 checksum；没有上游 checksum 时记录项目固定 digest 的生成依据。
- `AGENTS.md` 项目快照的具体修改文字；实施者取得用户明确允许后才能编辑。
- 当前是否存在可复现的真实安全误拒绝样例；没有样例时只建立分类和基线，不大改默认 prompt。
