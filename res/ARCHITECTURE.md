# res 架构说明

## 负责什么

- 放置运行时需要的统一资源标识。
- 放置主题、颜色等可复用视觉常量。
- 放置模型调用中间件使用的默认提示词资源。
- 后续可放置图片、图标、贴图等素材文件。

## 不负责什么

- 不放业务逻辑。
- 不放 UI 组件实现。
- 不放 UI 用户可见文案；界面文案应放在 `i18n/`。
- 不放项目数据、缓存或生成结果。

## 关键文件

- `colors.py`：集中定义当前 UI 使用的颜色标识。
- `app_icon.png`、`app_icon.ico`：运行时窗口图标和 Windows 打包图标；`app_icon_source.png` 保留透明源图，便于后续重新生成尺寸。
- `default_prompts.json`：模型调用中间件使用的默认提示词。它不是 UI 可见文案，只能由 `utils/ai_model_middleware.py` 加载和渲染；业务代码不得硬编码或复制这里的 prompt 正文。
- `test_media/`：模型页测试素材目录，存放固定的图片/视频测试文件，例如 `model_test_input.jpg`、`model_test_input.mp4`。
- `__init__.py`：标记 `res` 为 Python 包，便于代码引用资源标识。

## 与其他目录的关系

- `gui/` 从这里读取颜色标识，用于样式表和绘制。
- `utils/ai_model_middleware.py` 从这里读取默认提示词资源。
- `utils/` 仍负责通用工具和主题偏好逻辑，不承载具体颜色表。

## 维护注意事项

- 新增颜色时先命名后使用，避免在界面代码中直接写 RGB、RGBA 或 Hex。
- 新增图片资源时保持文件名语义清晰，并在需要时补充用途说明。
- 测试素材统一放到 `test_media/`，不要散落在项目根目录。
- 新增或修改默认提示词时保持 UTF-8 编码和结构化 JSON；模板中需要输出字面量 `{` / `}` 时必须写成 `{{` / `}}`，避免被格式化器误识别为变量。
- 新增模型任务或 prompt purpose 时，prompt 正文写入 `default_prompts.json`，业务模块只传变量、metadata 和多模态素材 part，不复制、不拼接、不硬编码 prompt 指令文本。
