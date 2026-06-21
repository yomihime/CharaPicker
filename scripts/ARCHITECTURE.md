# scripts 架构说明

## 负责什么

- 放置开发、构建和发布阶段使用的辅助脚本。
- 为 `build.bat` 和 CI 提供可复用的构建元数据计算逻辑。

## 不负责什么

- 不放应用运行时代码。
- 不放 UI 页面、业务推理或用户项目数据。
- 不保存构建产物、日志或临时缓存。

## 关键文件

- `build_meta.py`：解析命令行参数、Git tag、平台和架构，输出 `VERSION`、`STAGE`、`PLATFORM_TAG`、`ARCH_TAG` 等构建变量；默认版本和阶段来自 `utils.app_metadata`。
- `validate_formal_extraction_workflow.py`：执行不联网的正式提取流程边界验证，覆盖 FAST 并发数归一化、正式 JSON 三次重试，以及 FAST episode/season 无输入跳过策略。
- `validate_media_type_support.py`：执行不联网的媒体支持矩阵验证，覆盖四种媒体类型后缀、GIF/压缩包状态、集合内容形态提示和导入过滤。
- `validate_multi_material_scanner.py`：执行不联网的通用素材扫描验证，覆盖视频兼容、字幕关联、文本/音频/图片 unit、GIF warning、漫画/图集页组自然排序、跨文件夹不合并和 run plan 持久化。
- `validate_text_unit_handler.py`：执行不联网的普通文本提取验证，覆盖文本/受控 JSON 解析、预算分块、offset/evidence、超长文本 warning、文本-only 预览与正式聚合，以及视频 unit 不被文本 handler 接管。
- `validate_timed_text_handler.py`：执行不联网的时间文本验证，覆盖 SRT/ASS 解析、视频 episode 关联、独立字幕预览与正式提取、时间/行号/原始文本 evidence、显式 speaker 策略和 VTT 暂不支持反馈。
- `validate_image_unit_handler.py`：执行不联网的静态图片验证，覆盖图片排序、页组章节 metadata、页码/region/像素 evidence、文件上限与签名失败、GIF 跳过、模型能力不足、每张图片预算，以及图片-only 预览和正式聚合。
- `validate_audio_transcript_unit.py`：执行不联网的音频 transcript 验证，覆盖 Whisper 缓存命中、artifact 状态/coverage/source refs、派生 text unit、时间证据、音频-only 预览/正式提取，以及转写失败不阻断普通文本。
- `validate_generic_preview_dispatch.py`：执行不联网的通用预览调度验证，覆盖跨内容形态成本排序、失败候选补位、unsupported 洞察事件、单 unit 隔离计划、音频预览不持久化正式 run plan、视频候选路径，以及 preview/full artifact 隔离。
- `validate_formal_dispatch.py`：执行不联网的正式提取分发验证，覆盖分发表 handler 选择、audio transcript 物化后转入文本 handler、unsupported unit 洞察事件、模型不支持图片时不调用图片 handler、文本继续成功，以及视频旧提取路径回归。

## 与其他目录的关系

- `build.bat` 调用 `scripts/build_meta.py` 生成 zip 文件名所需的版本和阶段信息。
- `utils/app_metadata.py` 提供构建元数据默认版本和运行时 User-Agent 使用的同一份版本/阶段来源。
- `.github/workflows/build.yml` 间接通过 `build.bat` 使用该脚本。
- 发布产物仍写入根目录 `release/`，不写入 `scripts/`。

## 维护注意事项

- 脚本输出应保持机器可读，便于批处理和 CI 解析。
- 版本规则应与 [`../docs/reference/release-packaging.zh_CN.md`](../docs/reference/release-packaging.zh_CN.md) 的发布规范保持一致。
- 升级默认版本或阶段时，同步核对 `utils/app_metadata.py`、`pyproject.toml`、`build.bat` 默认值、README 和 i18n 关于页文案。
- 不要在脚本中硬编码敏感信息。
- 新增脚本时说明调用入口和输出位置。
