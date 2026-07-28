# 更新包 Payload 识别修正计划

> 本文档是执行计划，不代表实现状态。用户已确认按本计划修正当前自更新分支。

## 1. 范围

修正自动更新对 ZIP 顶层目录名的错误耦合。更新器不再要求顶层必须名为
`CharaPicker/`，改为根据应用文件结构解析唯一 payload 根目录。

涉及：

- `utils/app_update.py` 的 ZIP 安全校验和 payload 定位。
- `tests/test_app_update.py` 的结构兼容与拒绝场景。
- `docs/reference/release-packaging.zh_CN.md` 的发布约束。

## 2. 非目标

- 不改变 GitHub Release 查询、版本排序、测试版筛选或资产文件名规则。
- 不改变 SHA-256 下载与校验。
- 不改变 `app_updater.py` 的目录替换、用户数据保留、启动确认和回滚流程。
- 不改变 `build.bat` 当前输出单层 `CharaPicker/` 包装目录的行为。
- 不引入更新 manifest、代码签名或新依赖。

## 3. 已确认决策

- `CharaPicker/` 只保留为官方构建的人类可读输出约定，不作为自动更新安全契约。
- 自动更新接受两种 payload 结构：
  - 应用文件直接位于 ZIP 根目录。
  - 应用文件位于唯一单层包装目录，包装目录名称任意。
- payload 根目录必须直接包含 `CharaPicker.exe` 和
  `CharaPickerUpdater.exe`。
- 只检查解压根目录及其直接子目录，不递归搜索更深层目录。
- 必须恰好解析出一个候选 payload。
- 使用单层包装目录时，ZIP 不得存在包装目录之外的其他文件或目录。
- 路径逃逸、符号链接、文件数量和解压容量限制继续保持。

## 4. 当前状态与目标状态

当前实现通过 `UPDATE_ARCHIVE_ROOT = APP_NAME` 同时约束 ZIP 第一层名称和
解压后的 payload 路径。这把构建输出形式重复固化到了运行时。

目标实现先独立完成 ZIP entry 安全校验和解压，再从以下候选中解析 payload：

1. 解压根目录本身。
2. 解压根目录的直接子目录。

候选必须直接包含两个必需 EXE。零个或多于一个候选都应失败。

## 5. 安全与错误处理

- 所有 archive member 必须解析到隔离的解压根目录内。
- 拒绝绝对路径、`..`、符号链接、超量文件和超大解压结果。
- 平铺结构允许多个正常应用文件和目录，但必需 EXE 必须位于根目录。
- 包装结构只允许一个顶层目录，避免忽略或遗留包装目录外的内容。
- 多套应用、缺少必需 EXE、多层嵌套或混合结构均返回
  `UpdateDownloadError`。
- 失败时继续由现有 `prepare_update()` 清理更新工作区。

## 6. 里程碑

### M01：拆分 ZIP 安全校验与 payload 解析

交付：

- 删除固定 `UPDATE_ARCHIVE_ROOT`。
- `_extract_update_archive()` 只负责安全解压。
- 新增纯路径解析 helper，返回唯一 `payload_dir`。
- `prepare_update()` 使用解析结果，不自行拼接目录名。

验收：

- 平铺 ZIP 和任意名称单层包装 ZIP 均能得到正确 payload。
- 独立更新器输入仍是工作区内的绝对 payload 路径。

边界：

- 不放宽现有路径安全与容量限制。
- 不修改独立更新器目录替换协议。

### M02：补齐结构验证矩阵

交付：

- 平铺结构通过。
- `CharaPicker/` 包装结构通过。
- 任意名称单层包装结构通过。
- 缺少主程序、缺少更新器、多个候选、多层嵌套、包装目录外存在额外内容均失败。
- 原有路径逃逸测试继续通过。

验收：

- 更新专项单测全部通过。
- `git diff --check` 和 Ruff 通过。

### M03：同步发布文档并完成回归

交付：

- 发布文档将固定顶层名称降级为官方构建约定。
- 自动更新约束改为结构识别规则。

验收：

- i18n 校验不受影响。
- 完整离线回归通过。
- `build.bat --local` 仍生成当前官方目录结构，ZIP 中包含主程序和更新器。

## 7. 验证与自审查

- 检查 payload 解析不依赖目录名、版本号或 Release 名称。
- 检查候选范围严格限制在根目录和直接子目录。
- 检查包装模式不会静默忽略同级内容。
- 检查解压失败和解析失败都会清理工作区。
- 检查本次 diff 不改版本筛选、下载、SHA-256、替换和回滚逻辑。

验证命令：

```powershell
conda run -n CharaPicker python -m unittest tests.test_app_update
conda run -n CharaPicker python -m ruff check utils\app_update.py tests\test_app_update.py
conda run -n CharaPicker python scripts\validate_multi_material_regression.py
conda run -n CharaPicker cmd.exe /d /c build.bat --local
```

## 8. 提交分组

本修正作为一个可独立审查的提交：

```text
fix: decouple update payload from archive root name
```

提交前必须完成 M01-M03 的全部验证。
