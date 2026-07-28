# 打包与发布规范（zh_CN）

本文记录 CharaPicker 的长期打包与发布约束。修改 `build.bat`、`main.spec`、`scripts/build_meta.py` 或 GitHub Actions 时，应同步核对本文。

## 1. 打包入口

当前打包入口：

```powershell
build.bat
```

常用参数：

```powershell
build.bat --tag=v0.8.0-beta
build.bat --version=0.8.0 --stage=beta
build.bat --local
```

打包脚本通过 `scripts/build_meta.py` 解析版本、阶段、平台和架构，并调用 PyInstaller。未显式传入版本或 tag 时，默认版本和阶段来自 `utils/app_metadata.py`，与运行时 HTTP User-Agent 使用同一份应用元数据。除本地构建外，解析结果必须与应用源码版本、阶段一致，否则应在进入 PyInstaller 前失败。

## 2. PyInstaller 约束

- 打包必须使用 PyInstaller。
- 使用文件夹形式的 one-folder 产物，不使用单文件 exe 作为正式发布形态。
- 主程序继续使用 one-folder；为在主程序退出后替换安装目录，允许把无第三方运行时依赖的 `CharaPickerUpdater.exe` 构建为独立 one-file 辅助程序，并随主程序目录发布。该辅助程序不是应用的独立分发形态。
- `main.spec` 负责收集 `i18n/`、`res/` 和 qfluentwidgets 资源。
- `updater.spec` 只构建独立更新辅助程序，不收集 PyQt6 或 qfluentwidgets。
- 发布前应清理旧的 `build/`、`dist/CharaPicker/`、`release/CharaPicker/` 和目标 zip。

## 3. 发布包结构

官方构建当前使用单层 `CharaPicker/` 包装目录，方便用户手动解压和识别内容。
这是构建输出约定，不是自动更新协议对目录名称的要求。

推荐形态：

```text
release/
└── CharaPicker-v<version>[-<stage>]-<platform>-<arch>.zip
    └── CharaPicker/
        ├── CharaPicker.exe
        ├── CharaPickerUpdater.exe
        ├── README.md
        ├── ...
        └── _internal/
```

官方构建中，用户解压后应看到 `CharaPicker/xxx` 的结构，而不是一堆文件直接散在解压目录下。
兼容的第三方或历史更新包也可以把应用文件直接放在 ZIP 根目录，或使用其他名称的唯一单层包装目录。

## 4. 版本与阶段

版本号格式使用 `x.y.z`：

- `x`：大版本，用于不兼容变化。
- `y`：小版本，用于功能更新。
- `z`：修订版本，用于 bug 修正集，或不影响核心功能的极小功能更新。

构建阶段：

- `alpha`
- `beta`
- `rc`
- `release`
- `local`

当前构建脚本也支持 `alpha.N`、`beta.N`、`rc.N` 形式。这里的 `N` 是 build 版本号，用于同一 `x.y.z` 与同一阶段下的 rebuild；它可以包含不影响主要功能的 bug 修正或构建修正，但主旨是重新构建，不表达新的功能阶段。

在 `1.0.0` 之前，公开构建必须使用 `alpha` 或 `beta` 阶段；不要把 `0.x.y` 标记为 `release` 或 `rc`。当一次开发带来明确功能阶段推进时，应提升 `y`，例如从 `0.2.0-alpha.N` 进入 `0.3.0-alpha`；bug 修正集或极小补充可以提升 `z`；只为同一版本重新打包、修正构建元数据或补很小的非核心问题时，优先提升 `alpha.N` / `beta.N` 的 build 版本号。

允许通过 Git tag 指示版本与阶段：

- `v0.8.0-beta` -> `version=0.8.0`，`stage=beta`
- `v0.6.0-beta.1` -> `version=0.6.0`，`stage=beta.1`
- `v1.0.0` -> `version=1.0.0`，`stage=release`

构建脚本只读取显式 `--tag` 或当前提交上的精确 Git tag；历史最近 tag 不应覆盖当前默认版本。

使用 `--local` 或 `local` 参数时，阶段应写为 `local`。

升级默认版本或阶段时，应同步核对：

- `utils/app_metadata.py`：运行时应用名、版本阶段和 HTTP User-Agent。
- `pyproject.toml`：Python 项目元数据版本。
- `build.bat`：批处理脚本回退默认值和发布文件名拼接规则。
- `README.md` 和 `docs/readme/README.*.md`：用户可见版本文案；关于页版本由 `utils.app_metadata.py` 动态提供。
- `scripts/build_meta.py`：确认默认值仍从 `utils.app_metadata` 读取，命令行、tag 和 `--local` 覆盖逻辑保持有效。

## 5. 文件命名

发布 zip 文件名必须包含版本号、平台和架构。预发布与本地构建还应包含阶段；
正式版使用无后缀版本标签，不写入 `release`：

```text
预发布/本地：CharaPicker-v<version>-<stage>-<platform>-<arch>.zip
正式版：CharaPicker-v<version>-<platform>-<arch>.zip
```

示例：

```text
CharaPicker-v0.8.0-beta-windows-x64.zip
CharaPicker-v1.0.0-windows-x64.zip
```

## 6. 发布内容与排除项

发布包应包含：

- 运行所需程序文件。
- 用于退出后替换安装目录和失败回滚的 `CharaPickerUpdater.exe`。
- `i18n/`、`res/` 和 qfluentwidgets 运行资源。
- 必要说明文件：`README.md`、`LICENSE` 和 `THIRD_PARTY_NOTICES.md`。

许可证与第三方声明：

- CharaPicker 自有源码采用 MPL-2.0；发布包必须包含根目录 `LICENSE`。
- 发布包必须包含根目录 `THIRD_PARTY_NOTICES.md`，说明主要第三方依赖、打包工具和运行资源的许可证信息。
- 当前开源构建使用 GPL 许可的 PyQt6 / PyQt6-Fluent-Widgets 组件；发布二进制包时必须同时遵守这些第三方许可证义务。若未来改用商业许可或替代依赖，发布前应更新第三方声明。
- 升级 PyQt6、PyQt6-Fluent-Widgets、Qt、PyInstaller 或运行时依赖时，应复核第三方声明。
- 公开发布二进制包时，优先从 Git tag 发布，确保用户可以找到与二进制对应的源码版本。
- 发布包包含的图片、视频、音频、图标、截图或 AI 生成素材应在 `docs/reference/asset-material-declaration.zh_CN.md` 中记录简要来源、用途和 AI 生成/人工编辑声明；若后续进入正式商用分发、官网宣传或商店上架等高风险场景，再补充更完整来源或替换为来源可核验素材。

发布包不应包含：

- 源码开发缓存。
- 测试缓存。
- 临时文件。
- 本地日志。
- 用户项目素材、知识库和输出。
- 私有配置，例如 `config.yaml`。
- 未经确认的本地模型权重或大型二进制。

## 7. CI 关系

GitHub Actions 只负责编排构建，不承载应用运行逻辑。当前 Windows workflow 会安装依赖和 PyInstaller，运行 `build.bat`，为每个 `release/*.zip` 生成同名 `.sha256`，上传两类产物，并在 tag 触发时发布 Release 附件。自动更新只接受 ZIP 与同名 SHA-256 文件同时存在的 Windows x64 Release。

自动更新流程还必须满足以下约束：

- 未启用“更新测试版”时，只选择无预发布后缀且未标记为 prerelease 的正式 Release；启用后允许 alpha、beta 和 rc，但始终只升级到高于当前版本的最高版本，不允许降级。
- 更新资产必须精确匹配 `CharaPicker-v<version>[-<stage>]-windows-x64.zip` 及其同名 `.sha256`；不使用模糊匹配或任意 Release 附件。
- 主程序通过统一网络中间件下载并校验更新包。自动更新接受应用文件位于 ZIP 根目录，或位于名称任意的唯一单层包装目录；解析出的 payload 必须直接包含主程序和更新器。多层嵌套、多个候选，或包装目录外存在其他内容时必须拒绝。
- 更新器先等待当前主程序退出，再备份并替换安装目录；`projects/`、`config.yaml`、`log/`、`bin/` 和 `models/` 必须跨版本保留。新版未在限定时间内完成启动确认时，更新器应恢复旧版并重新启动。

tag 构建会显式把当前 tag 传给 `build.bat`，让构建产物版本、阶段与发布 tag 对齐；若 tag 与 `utils.app_metadata.py` 不一致，构建必须失败。发布 GitHub Release 前必须先在 `CHANGELOG.md` 中准备同名版本小节；workflow 会抽取该小节作为 Release 正文开头，找不到对应小节时应失败，以避免发布缺少版本说明的二进制包。同时 workflow 必须开启 GitHub 自动 release notes，让 Release 页面保留 `What's Changed`、完整 changelog 链接和 contributors 区域。
