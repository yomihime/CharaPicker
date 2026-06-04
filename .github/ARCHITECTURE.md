# .github 架构说明

## 负责什么

- 放置 GitHub 仓库级自动化配置。
- 管理 GitHub Actions 工作流。
- 在 CI 中执行 Windows 构建、上传构建产物，并在 tag 构建时发布 Release 附件。

## 不负责什么

- 不放应用运行时代码。
- 不放项目业务逻辑、UI 逻辑或用户文案。
- 不保存构建产物、缓存、模型或用户数据。

## 关键文件

- `workflows/build.yml`：Windows 构建工作流。通过手动触发或 `v*` tag 触发；安装 Python 3.12、安装依赖、运行 `build.bat`，上传 `release/*.zip`，并在 tag 触发时从 `CHANGELOG.md` 抽取版本说明作为 Release 正文开头，同时启用 GitHub 自动 release notes 发布附件。

## 与其他目录的关系

- 调用根目录 `build.bat` 执行打包；tag 构建会显式传入当前 tag，确保版本阶段与发布 tag 对齐。
- `build.bat` 调用 `scripts/build_meta.py` 生成版本、阶段、平台和架构信息。
- 打包过程读取 `main.spec`、`i18n/`、`res/` 和应用源码。
- tag 发布时读取根目录 `CHANGELOG.md` 中与 tag 同名的版本小节作为 Release 正文开头，并让 GitHub 自动补充 `What's Changed`、完整 changelog 链接和 contributors 区域。

## 维护注意事项

- 工作流只负责编排，不承载应用逻辑。
- 修改发布命名规则时，同步更新 `build.bat`、`scripts/ARCHITECTURE.md` 和根目录架构说明。
- Build 工作流默认不在普通 `main` push 上运行，避免每次提交都触发完整 Windows 打包；发布构建通过 `v*` tag 或手动触发执行。
- tag 发布规则应与版本规范和 `CHANGELOG.md` 中的版本小节保持一致。
