# .github 架构说明

## 负责什么

- 放置 GitHub 仓库级自动化配置。
- 管理 GitHub Actions 工作流。
- 在 CI 中执行质量门禁、Windows 构建、provenance attestation、构建产物上传，并在 tag 构建时发布 Release 附件。

## 不负责什么

- 不放应用运行时代码。
- 不放项目业务逻辑、UI 逻辑或用户文案。
- 不保存构建产物、缓存、模型或用户数据。

## 关键文件

- `workflows/build.yml`：RC/Release 门禁与 Windows 构建工作流。PR 和 `main` push 执行质量门禁；手动触发与 `v*` tag 在门禁后通过固定版本 uv 同步带 hash 的 Windows Release 环境并构建。tag 构建再通过独立最小权限 job attest ZIP/checksum/依赖库存与最终 `build-info.json`，最后发布已 attested 的 Release artifact。

## 与其他目录的关系

- 调用根目录 `build.bat` 执行打包；tag 构建会显式传入当前 tag，确保版本阶段与发布 tag 对齐。
- 质量与构建 job 使用固定 commit 的 `astral-sh/setup-uv`、固定 uv 版本和 Python 3.12.10；依赖继续从 Windows Release 哈希锁精确同步。
- `build.bat` 调用 `scripts/build_meta.py` 生成版本、阶段、平台和架构信息。
- `build.bat` 调用 `scripts/inspect_release_signatures.py` 检查主程序与更新器的实际 Authenticode 状态，再由 `scripts/package_release.py` 写入构建清单。
- 打包过程读取 `main.spec`、`i18n/`、`res/` 和应用源码。
- tag 发布时由 `scripts/prepare_release_notes.py` 读取根目录 `CHANGELOG.md` 中与 tag 同名的版本小节，附加未签名、checksum 和 provenance 边界，再让 GitHub 自动补充 `What's Changed`、完整 changelog 链接和 contributors 区域。

## 维护注意事项

- 工作流只负责编排，不承载应用逻辑。
- 修改发布命名规则时，同步更新 `build.bat`、`scripts/ARCHITECTURE.md` 和根目录架构说明。
- PR 与普通 `main` push 只执行质量门禁，不执行完整 Windows 打包；发布构建通过 `v*` tag 或手动触发执行。
- 所有 `uses:` 必须固定到完整 commit SHA。attestation 权限只授予 tag 使用的独立 job；发布写权限只授予最后的 Release job。
- tag 发布规则应与版本规范和 `CHANGELOG.md` 中的版本小节保持一致。
