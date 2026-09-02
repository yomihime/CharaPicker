# 打包与发布规范（zh_CN）

本文记录 CharaPicker 的长期打包与发布约束。修改 `build.bat`、`main.spec`、`scripts/build_meta.py` 或 GitHub Actions 时，应同步核对本文。

## 1. 打包入口

当前打包入口：

```powershell
build.bat
```

源码开发与构建环境由 uv 管理。首次构建前运行 `uv sync --locked`；`build.bat` 只通过 `uv run --no-sync` 使用已同步的项目 `.venv`，不会退回 Conda、系统 Python 或临时安装依赖。

常用参数：

```powershell
build.bat --tag=vX.Y.Z-beta
build.bat --version=X.Y.Z --stage=beta
build.bat --local
```

打包脚本通过 `scripts/build_meta.py` 解析版本、阶段、平台和架构，并调用 PyInstaller。未显式传入版本或 tag 时，默认版本和阶段来自 `utils/app_metadata.py`，与运行时 HTTP User-Agent 使用同一份应用元数据。除本地构建外，解析结果必须与应用源码版本、阶段一致，并在清理旧产物和进入 PyInstaller 前核对 Windows Release 锁、目标平台、Python、uv、PyInstaller 和固定环境参数；任一不匹配都应快速失败。`--local` 保持日常开发环境构建语义，不要求匹配 Windows Release 锁。

## 2. PyInstaller 约束

- 打包必须使用 PyInstaller。
- 使用文件夹形式的 one-folder 产物，不使用单文件 exe 作为正式发布形态。
- 主程序继续使用 one-folder；为在主程序退出后替换安装目录，允许把无第三方运行时依赖的 `CharaPickerUpdater.exe` 构建为独立 one-file 辅助程序，并随主程序目录发布。该辅助程序不是应用的独立分发形态。
- 打包后的主程序运行根目录必须以 `CharaPicker.exe` 所在目录为准，不能依赖启动进程的当前工作目录。快捷方式、终端、文件管理器和自更新 relaunch 都可能提供不同 cwd；`config.yaml`、`projects/`、`log/`、`bin/`、`models/` 和运行资源路径不得因此漂移。
- `main.spec` 负责收集 `i18n/`、`res/` 和 qfluentwidgets 资源。
- `updater.spec` 只构建独立更新辅助程序，不收集 PyQt6 或 qfluentwidgets。
- 两个 spec 都通过 `scripts/run_pyinstaller_isolated.py` 启动。PyInstaller 子进程的 `PATH` 只保留项目虚拟环境、基础 Python 和必要的 Windows 系统目录，不继承宿主机其它工具目录，避免外部 DLL 或 UPX 改变收集结果；该隔离不改变后续 uv、Git、签名检查和发布清单所用环境。
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

当前构建脚本也支持 `alpha.N`、`beta.N`、`rc.N` 形式。这里的 `N` 是 build 版本号，用于同一 `x.y.z` 与同一阶段下的 rebuild；它可以包含不影响主要功能的 bug 修正或构建修正，但主旨是重新构建，不表达新的功能阶段。`N=0` 表示没有额外小修订，与无序号阶段等价；公开发布优先使用 `alpha`、`beta`、`rc` 这种无 `.0` 的规范形式，不把 `rc` 与 `rc.0` 作为两个独立候选版本。

在 `1.0.0` 之前，公开构建必须使用 `alpha` 或 `beta` 阶段；不要把 `0.x.y` 标记为 `release` 或 `rc`。当一次开发带来明确功能阶段推进时，应提升 `y`，例如从 `0.2.0-alpha.N` 进入 `0.3.0-alpha`；bug 修正集或极小补充可以提升 `z`；只为同一版本重新打包、修正构建元数据或补很小的非核心问题时，优先提升 `alpha.N` / `beta.N` 的 build 版本号。

允许通过 Git tag 指示版本与阶段：

- `v1.2.3-beta` -> `version=1.2.3`，`stage=beta`
- `v1.2.3-beta.1` -> `version=1.2.3`，`stage=beta.1`
- `v1.0.0-rc` -> `version=1.0.0`，`stage=rc`
- `v1.0.0` -> `version=1.0.0`，`stage=release`

构建脚本只读取显式 `--tag` 或当前提交上的精确 Git tag；历史最近 tag 不应覆盖当前默认版本。

使用 `--local` 或 `local` 参数时，阶段应写为 `local`。

升级默认版本或阶段时，应同步核对：

- `utils/app_metadata.py`：运行时应用名、版本阶段和 HTTP User-Agent。
- `pyproject.toml`：Python 项目元数据版本。
- `build.bat`：批处理脚本回退默认值和发布文件名拼接规则。
- `README.md` 和 `docs/readme/README.*.md`：用户可见阶段、发布入口和构建入口文案；README 不维护精确当前版本号，关于页版本由 `utils.app_metadata.py` 动态提供。
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
CharaPicker-v<version>-beta-windows-x64.zip
CharaPicker-v1.0.0-windows-x64.zip
```

## 6. 发布内容与排除项

发布包应包含：

- 运行所需程序文件。
- 用于退出后备份旧程序文件并覆盖新版 payload 的 `CharaPickerUpdater.exe`。
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

GitHub Actions 只负责编排构建，不承载应用运行逻辑。当前 Windows workflow 使用固定 commit 的 `astral-sh/setup-uv` 安装固定 uv 与 Python 3.12.10，以 `uv pip sync` 从 `requirements-release-windows-py312.txt` 建立带 hash 的精确发布环境，再运行 `build.bat`。`build.bat` 在 PyInstaller 前复核该 job 的实际环境，打包结束时再由发布清单逻辑防御性复核一次。`uv.lock` 服务于日常跨平台开发；Windows Release 哈希锁继续作为官方构建与依赖库存审计输入。workflow 为每个 `release/*.zip` 生成同名 `.sha256`，上传两类产物，并在 tag 触发时发布 Release 附件。自动更新只接受 ZIP 与同名 SHA-256 文件同时存在的 Windows x64 Release。

自动更新流程还必须满足以下约束：

- 未启用“更新测试版”时，只选择无预发布后缀且未标记为 prerelease 的正式 Release；启用后允许 alpha、beta 和 rc，但始终只升级到高于当前版本的最高版本，不允许降级。
- 更新资产必须精确匹配 `CharaPicker-v<version>[-<stage>]-windows-x64.zip` 及其同名 `.sha256`；不使用模糊匹配或任意 Release 附件。
- 更新下载 URL 必须来自本项目 GitHub Releases 的固定下载路径。ZIP 使用独立的 2 GiB 压缩包上限并核对 GitHub asset `size`，同名 checksum 使用 64 KiB 上限；两者都同时检查 HTTP `Content-Length` 与实际流式字节数，失败或取消时清理 staging 文件。
- 主程序通过统一网络中间件下载并校验更新包 SHA-256。自动更新接受应用文件位于 ZIP 根目录，或位于名称任意的唯一单层包装目录；解析出的 payload 必须直接包含主程序和更新器。多层嵌套、多个候选，或包装目录外存在其他内容时必须拒绝。
- 更新器先等待当前主程序退出，把已验证的 ZIP 与 checksum 保留到安装目录的 `download/`，并按照新版 payload 顶层项目把现有程序文件备份到 `update_backup/`，随后把 payload 直接覆盖到原安装目录。`projects/`、`config.yaml`、`log/`、`bin/` 和 `models/` 必须保持原位且不得进入覆盖范围。便携版自动更新不承诺自动回滚；覆盖或启动确认失败时应保留下载包和程序备份，供用户手工恢复。

tag 构建会显式把当前 tag 传给 `build.bat`，让构建产物版本、阶段与发布 tag 对齐；若 tag 与 `utils.app_metadata.py` 不一致，构建必须失败。发布 GitHub Release 前必须先在 `CHANGELOG.md` 中准备同名版本小节；workflow 会抽取该小节作为 Release 正文开头，找不到对应小节时应失败，以避免发布缺少版本说明的二进制包。同时 workflow 必须开启 GitHub 自动 release notes，让 Release 页面保留 `What's Changed`、完整 changelog 链接和 contributors 区域。

## 8. 发布来源、签名与 provenance

### 8.1 当前 v1.0.0 无证书基线

当前仓库和 GitHub Actions 未配置 Authenticode 证书、私钥或时间戳服务，因此 v1.0.0 采用明确的无证书分发基线：

- 构建在压缩前通过 Windows `Get-AuthenticodeSignature` 检查 `CharaPicker.exe` 和 `CharaPickerUpdater.exe`。两者都必须实际返回 `NotSigned`，才能在 `build-info.json` 中声明 unsigned；出现 `Valid`、`UnknownError`、hash 不符或检查失败都会中止构建，避免实际状态与披露不一致。
- 不生成临时自签名证书，不把自签名结果描述为公开发布者信誉，也不在仓库、普通 artifact 或 Release 附件中保存 PFX/私钥。
- Release 正文必须明确说明当前 Windows 二进制未使用 Authenticode，Windows 仍可能显示未知发布者或 SmartScreen 信誉提示。
- 若后续启用正式 Authenticode，必须由维护者先确认证书主体、私钥托管、可信时间戳、续期和吊销责任；主程序与更新器都要在压缩前签名并验证。该路径需要单独实施和审查，不能仅修改披露文案。

### 8.2 GitHub artifact attestation

tag 构建通过独立的 `attest-release` job 生成 GitHub artifact attestation。该 job 只持有 `contents: read`、`id-token: write` 和 `attestations: write`，使用固定到完整 commit SHA 的官方 `actions/attest`：

1. 对 ZIP、同名 `.sha256` 和依赖库存生成一份 SLSA build provenance attestation。
2. 只有 attestation 成功后，才把 GitHub attestation ID、URL 和官方仓库名写入最终 `build-info.json`，并重新执行发布包校验。
3. 再对最终 `build-info.json` 单独生成 attestation，防止写入 provenance 状态后的 manifest 缺少来源证明。
4. `publish-release` 只依赖已 attested 的 artifact；任一 attestation、记录或复核步骤失败，GitHub Release 不会发布。

GitHub artifact attestation 证明产物由本仓库特定 Actions 工作流生成，不等于 Windows Authenticode 发布者签名，也不保证消除 SmartScreen 提示。官方能力、权限和验证方式见 [GitHub artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)。下载 ZIP 后可联网验证：

```powershell
gh attestation verify ".\CharaPicker-v1.0.0-windows-x64.zip" -R yomihime/CharaPicker
```

### 8.3 SHA-256 与构建清单边界

- 同名 `.sha256` 证明下载字节与 Release checksum 一致，不证明发布者身份；checksum 与 ZIP 同时被替换时，这一层不能独立发现账号失守。
- `build-info.json` 记录官方仓库、commit、tag、确定性构建时间源、工具链、依赖锁、包内文件 hash、两个可执行文件的实际签名状态，以及 package attestation ID/URL。
- `dependency-inventory.json` 记录锁定依赖与许可证 metadata；它不是漏洞扫描报告或法律结论。
- 官方分发入口只使用本项目 GitHub Releases。镜像或转存文件即使 hash 相同，也不自动成为项目维护者承诺支持的发布渠道。

Release 正文由 `scripts/prepare_release_notes.py` 从 CHANGELOG 版本段落生成，并自动附加官方入口、未签名披露、PowerShell SHA-256 比较命令和 `gh attestation verify` 命令；不得手工删去这些信任边界后再发布。
