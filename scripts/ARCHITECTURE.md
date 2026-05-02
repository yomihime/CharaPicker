# scripts 架构说明

## 负责什么

- 放置开发、构建和发布阶段使用的辅助脚本。
- 为 `build.bat` 和 CI 提供可复用的构建元数据计算逻辑。

## 不负责什么

- 不放应用运行时代码。
- 不放 UI 页面、业务推理或用户项目数据。
- 不保存构建产物、日志或临时缓存。

## 关键文件

- `build_meta.py`：解析命令行参数、Git tag、平台和架构，输出 `VERSION`、`STAGE`、`PLATFORM_TAG`、`ARCH_TAG` 等构建变量。

## 与其他目录的关系

- `build.bat` 调用 `scripts/build_meta.py` 生成 zip 文件名所需的版本和阶段信息。
- `.github/workflows/build.yml` 间接通过 `build.bat` 使用该脚本。
- 发布产物仍写入根目录 `release/`，不写入 `scripts/`。

## 维护注意事项

- 脚本输出应保持机器可读，便于批处理和 CI 解析。
- 版本规则应与 `.codex/CONTENT.md` 的发布规范保持一致。
- 不要在脚本中硬编码敏感信息。
- 新增脚本时说明调用入口和输出位置。
