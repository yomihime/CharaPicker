# bin 架构说明

## 负责什么

- 按工具、版本和运行包隔离运行时需要的外部二进制工具。
- 统一使用 `bin/{tool}/{version}/{package_id}/` 作为自动下载工具的安装边界。
- 为离线或本地模式提供工具发现位置。

## 不负责什么

- 不放 Python 源码。
- 不放用户素材、项目数据或导出结果。
- 不放模型权重文件。
- 不放 UI 文案或资源说明。

## 关键文件

- `.gitkeep`：保留空目录。
- `ffmpeg/{version}/win-x64/`：自动下载的 FFmpeg Windows x64 运行时。
- `llama.cpp/{version}/win-x64-cpu/`：自动下载的 llama.cpp Windows x64 CPU 运行时。
- `whisper.cpp/{version}/{package_id}/`：自动下载的 whisper.cpp CPU、BLAS 或 CUDA 运行时。
- `7zip/7z.exe`：可选的用户手动放置位置；应用不自动下载 7-Zip。
- 当前不提交具体二进制文件。

## 与其他目录的关系

- `utils.runtime_layout.py` 定义本目录的工具、版本和运行包路径契约。
- `utils.env_manager.py` 只在 llama.cpp、whisper.cpp 各自的受管目录及兼容旧位置中检测工具。
- `utils.ffmpeg_tool.py` 只在 FFmpeg 受管目录及兼容旧位置中检测工具。
- `utils.ffmpeg_downloader.py` 和 `utils.llamacpp_downloader.py` 可向本目录安装运行时工具。
- `core` 后续媒体解析流程可通过环境检测结果调用这些工具。
- 打包流程应决定哪些工具需要进入发布包。

## 维护注意事项

- 大型二进制文件默认不提交到 Git。
- 新增工具时记录来源、版本和许可信息。
- 临时下载和解压目录只能出现在对应工具目录中，正常结束后必须清理；验证成功后再原子替换目标版本目录。
- 新下载不得继续把 DLL 或可执行文件铺到 `bin/` 根目录；旧根目录文件仅保留发现兼容。
- 发布包只包含运行确实需要的工具。
