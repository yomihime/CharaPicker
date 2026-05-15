# 打包与发布规范（zh_CN）

本文记录 CharaPicker 的长期打包与发布约束。修改 `build.bat`、`main.spec`、`scripts/build_meta.py` 或 GitHub Actions 时，应同步核对本文。

## 1. 打包入口

当前打包入口：

```powershell
build.bat
```

常用参数：

```powershell
build.bat --tag=v0.1.0-alpha.1
build.bat --version=0.1.0 --stage=release
build.bat --local
```

打包脚本通过 `scripts/build_meta.py` 解析版本、阶段、平台和架构，并调用 PyInstaller。

## 2. PyInstaller 约束

- 打包必须使用 PyInstaller。
- 使用文件夹形式的 one-folder 产物，不使用单文件 exe 作为正式发布形态。
- `main.spec` 负责收集 `i18n/`、`res/` 和 qfluentwidgets 资源。
- 发布前应清理旧的 `build/`、`dist/CharaPicker/`、`release/CharaPicker/` 和目标 zip。

## 3. 发布包结构

发布 zip 内部顶层目录必须是 `CharaPicker/`。

推荐形态：

```text
release/
└── CharaPicker-v<version>-<stage>-<platform>-<arch>.zip
    └── CharaPicker/
        ├── CharaPicker.exe
        ├── README.md
        ├── ...
        └── _internal/
```

用户解压后应看到 `CharaPicker/xxx` 的结构，而不是一堆文件直接散在解压目录下。

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

在 `1.0.0` 之前，公开构建必须使用 `alpha` 或 `beta` 阶段；不要把 `0.x.y` 标记为 `release` 或 `rc`。当一次开发带来明确功能阶段推进时，应提升 `y`，例如从 `0.1.0-alpha.N` 进入 `0.2.0-alpha.1`；bug 修正集或极小补充可以提升 `z`；只为同一版本重新打包、修正构建元数据或补很小的非核心问题时，优先提升 `alpha.N` / `beta.N` 的 build 版本号。

允许通过 Git tag 指示版本与阶段：

- `v0.1.0-alpha` -> `version=0.1.0`，`stage=alpha`
- `v0.1.0-alpha.1` -> `version=0.1.0`，`stage=alpha.1`
- `v0.1.0` -> `version=0.1.0`，`stage=release`

使用 `--local` 或 `local` 参数时，阶段应写为 `local`。

## 5. 文件命名

发布 zip 文件名必须包含版本号、阶段、平台和架构：

```text
CharaPicker-v<version>-<stage>-<platform>-<arch>.zip
```

示例：

```text
CharaPicker-v0.1.0-alpha.1-windows-x64.zip
CharaPicker-v0.1.0-release-windows-x64.zip
```

## 6. 发布内容与排除项

发布包应包含：

- 运行所需程序文件。
- `i18n/`、`res/` 和 qfluentwidgets 运行资源。
- 必要说明文件，例如 `README.md`。

发布包不应包含：

- 源码开发缓存。
- 测试缓存。
- 临时文件。
- 本地日志。
- 用户项目素材、知识库和输出。
- 私有配置，例如 `config.yaml`。
- 未经确认的本地模型权重或大型二进制。

## 7. CI 关系

GitHub Actions 只负责编排构建，不承载应用运行逻辑。当前 Windows workflow 会安装依赖和 PyInstaller，运行 `build.bat`，上传 `release/*.zip`，并在 tag 触发时发布 Release 附件。
