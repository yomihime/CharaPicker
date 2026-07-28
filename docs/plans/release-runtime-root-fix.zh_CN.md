# 打包运行根目录修复计划

> 本文档是执行计划，不代表实现状态。实现前需由用户确认修复计划。

## 1. 范围

本计划只修复打包后的 Windows one-folder 运行时根目录解析问题。目标是让 frozen/packaged 应用始终以 `CharaPicker.exe` 所在目录作为运行根目录，而不是启动进程的当前工作目录。

受影响的运行时路径包括 `config.yaml`、`projects/`、`log/`、`bin/`、`models/`、`res/`、测试媒体、许可证和第三方声明文件读取。

## 2. 非目标

- 不修改正式版无后缀发布规则；正式版 `1.0.0` 的 tag 和文件名继续使用 `v1.0.0` / `CharaPicker-v1.0.0-windows-x64.zip`。
- 不修复 `rc.0` 相关代码。已确认 `rc.0` 表示没有小修订 build 序号，与 `rc` 等价；公开发布优先使用无 `.0` 的规范形式。
- 不在本轮修复自更新下载压缩包大小上限、原生音频大文件请求体限制或目录导入递归深度。
- 不改变 `projects/`、`config.yaml`、`log/`、`bin/`、`models/` 的跨版本保留策略。
- 不引入新依赖，不改变 PyInstaller one-folder 发布形态。

## 3. 已确认决策

- 开发态运行根目录继续是仓库根目录。
- 打包态运行根目录必须是 `Path(sys.executable).resolve().parent`。
- 自更新 relaunch 的工作目录应与安装目录对齐，避免修复后仍由外部 cwd 影响启动行为。
- 本轮只做路径根修复和对应测试，不扩大到发布包结构或更新协议重构。

## 4. 当前状态

- `utils.paths._resolve_app_root()` 在 frozen 环境返回 `Path.cwd().resolve()`。
- `APP_ROOT` 派生出 `PROJECTS_ROOT` 与 `LOGS_ROOT`。
- `utils.global_store`、`utils.env_manager`、`utils.logging_middleware`、关于页、模型页测试媒体路径等模块依赖 `APP_ROOT`。
- `utils.app_update.packaged_install_dir()` 已经用 `sys.executable` 定位安装目录，但 `launch_prepared_update()` 写入的 `relaunch_cwd` 仍来自当前工作目录。

## 5. 目标状态

- frozen/packaged 环境中，`APP_ROOT`、`PROJECTS_ROOT`、`LOGS_ROOT` 与安装目录稳定绑定。
- 从快捷方式、任意终端目录或自更新 relaunch 启动时，不会把配置、日志、项目数据或工具目录写到外部 cwd。
- 开发态路径行为不变。
- 自更新替换目录、保留运行时数据和启动确认流程不变。

## 6. 实施里程碑

### M01：修复运行根目录

交付：
- 将 frozen/packaged 环境下的 `utils.paths._resolve_app_root()` 改为使用 `sys.executable` 所在目录。
- 保持非 frozen 环境继续使用仓库根目录。

验收：
- 单测模拟 `sys.frozen=True`、`sys.executable=<install_dir>/CharaPicker.exe` 和外部 cwd，确认 app root 等于 `<install_dir>`。
- 单测覆盖开发态仍解析到仓库根目录。

边界：
- 不迁移已有错误 cwd 下的用户数据。
- 不改变项目目录结构。

### M02：修复自更新 relaunch cwd

交付：
- `utils.app_update.launch_prepared_update()` 写入请求时，将 `relaunch_cwd` 设置为安装目录。

验收：
- 单测验证生成的 update request 中 `relaunch_cwd == install_dir`。
- 不改变 updater 的备份、回滚、ack 和保留路径逻辑。

边界：
- 不改 `app_updater.py` 的整体替换流程。
- 不调整保留目录列表。

### M03：回归验证

交付：
- 新增或更新针对路径解析与自更新请求的单测。
- 运行静态检查、相关单测和统一离线回归。

验收命令：
- `conda run -n CharaPicker python -m ruff check .`
- `conda run -n CharaPicker python -m unittest tests.test_app_update tests.test_build_meta`
- `conda run -n CharaPicker python scripts\validate_multi_material_regression.py`

边界：
- 不要求在本轮执行完整 PyInstaller 打包；若需要发布前验收，应另行运行 `build.bat --local` 或 tag 构建。

## 7. 代码自审查要求

- 检查所有 `APP_ROOT` 派生路径是否仍符合发布规范。
- 检查是否存在新的 cwd 依赖。
- 检查自更新请求 JSON 中路径均位于安装目录、安装目录父目录或系统临时目录的预期边界内。
- 检查测试没有依赖本机固定路径。

## 8. 提交分组

建议本轮实现只保留一个代码提交：

- `fix: resolve packaged app root from executable`

提交前检查：
- 工作区只包含路径修复、相关测试和必要文档同步。
- 所有验证命令通过，或明确说明无法运行的命令和原因。

