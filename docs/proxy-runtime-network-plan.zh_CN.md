# Proxy 运行时网络能力计划（zh_CN）

> 本文档是 P3「内置 proxy 设置」的执行计划；基础实现已于 2026-05-24 按本文落地，当前事实仍以代码、TODO 和运行时中间件文档为准。

## 1. 范围

- 为 CharaPicker 增加内置代理设置。
- 代理开启后，应用内所有运行时网络请求都必须走统一代理配置。
- 覆盖当前已知联网入口：云端模型请求、云端模型列表拉取、FFmpeg 下载、llama.cpp 下载、设置页连通性测试。
- 代理配置通过设置页管理，并持久化到本地 `config.yaml`。
- 实现必须保持当前 `core` / `gui` / `utils` 分层：页面负责配置与反馈，联网细节收口到 `utils` 中间件。
- 后续新增应用内联网入口时，必须复用统一网络中间件，不得直接使用底层 HTTP API 绕过代理偏好。
- 第一版采用全局一致的应用级代理执行入口：所有程序内联网动作都通过 `utils.network_middleware` 获取同一份代理配置、同一套脱敏规则、同一把网络锁和同一套 fail closed 语义。

## 2. 非目标

- 不改变模型预设、API Key、prompt 或知识库结构。
- 不绕过 `utils.ai_model_middleware` 直接发起模型请求。
- 不把普通调试日志展示成洞察流事件。
- 不在第一版引入系统级证书管理、加密存储或操作系统凭据库。
- 不把本地 FFmpeg 转码、抽帧、素材复制等非联网文件操作纳入代理逻辑。

## 3. 已确认决策

- 开启代理后，所有应用内运行时网络请求都要走代理。
- 由系统浏览器或其他外部程序打开的链接不纳入内置代理管理；本计划只管理 CharaPicker 进程内发起的网络请求。
- 第一版同时支持 HTTP、HTTPS 和 SOCKS5 代理。
- SOCKS5 提供远程 DNS 解析开关；实现时可映射为 `socks5` / `socks5h` 或等价行为。
- 代理账号、密码和地址保存到本地 `config.yaml`，安全性管理先交给用户自行负责。
- 设置页需要提供代理连通性测试；测试在未启用内置代理时也可运行，是否可用由用户根据 Google、Cloudflare、Baidu 三个测试结果自行判断。
- 三个固定测试项常驻显示，但初始未测试时不显示成功或失败灯。
- 设置页提供自定义测试入口；自定义测试 URL 保存到本地 `config.yaml`，方便下次继续使用。
- 日志、InfoBar 和错误摘要不得泄露代理账号、密码、API Key 或完整带凭据 URL。

## 4. 计划制定时状态与目标状态

计划制定时状态：

- 设置页当前只有语言、主题和日志等级。
- 全局用户配置统一通过 `utils.global_store` 读写根目录 `config.yaml`。
- OpenAI-compatible 模型请求、云端模型列表、FFmpeg 下载和 llama.cpp 下载使用 `urllib.request`。
- 阿里百炼视频请求走 DashScope SDK；本地 `CharaPicker` conda 环境当前安装 `dashscope==1.24.6`，该版本不支持通过 `session` 参数传入按请求代理。
- DashScope SDK 最新 main 分支已支持给主 HTTP 请求传入 `session`，但多模态本地文件预处理里的 OSS 上传仍会直接创建 `requests.Session()`，因此单靠 `MultiModalConversation.call(..., session=...)` 不能完整覆盖本地视频上传链路。
- `requirements.txt` 已包含 `PySocks>=1.7.1`，但 `pyproject.toml` 尚未同步该依赖。

目标状态：

- 设置页提供清晰的代理开关、类型、主机、端口、账号和密码字段。
- 所有联网代码通过统一网络中间件读取代理偏好。
- CharaPicker 自有 HTTP(S) 请求优先统一到 `requests` 执行路径，并显式传入 `proxies`，避免 `urllib`、环境变量和 SOCKS handler 多套机制并存。
- DashScope 路径明确支持代理；若 SDK 无法可靠接入代理，代理开启时必须 fail closed 并提示用户，不得直连。
- 日志与 UI 错误输出统一走脱敏 helper。

## 5. 数据与持久化

建议新增 `utils/proxy_preferences.py`，封装代理配置读写，避免 UI 和联网模块散落原始 `global_store` key。

建议配置结构：

```yaml
network:
  proxy:
    enabled: true
    scheme: "http" # http / https / socks5
    remote_dns: true
    host: "127.0.0.1"
    port: 7890
    username: ""
    password: ""
    custom_test_url: "https://example.com/"
```

持久化规则：

- 默认 `enabled=false`，保持现有网络行为。
- `host` 为空或 `port` 非法时视为未配置，不静默拼接无效代理 URL。
- `scheme=socks5` 时读取 `remote_dns`；开启后使用代理侧 DNS 解析，关闭后使用本地 DNS 解析。
- 保存密码前不做加密；设置页应明确提示配置保存在本地文件中。
- 读取配置时做类型归一化，避免旧配置或手动编辑导致崩溃。
- `custom_test_url` 只作为设置页连通性测试的用户偏好，不参与代理请求路由。

## 6. UI 与工作流

设置页新增「网络代理」区域：

- 代理开关。
- 类型选择：HTTP、HTTPS、SOCKS5。
- 主机输入。
- 端口输入。
- SOCKS5 远程 DNS 解析开关；仅在类型为 SOCKS5 时启用或显示。
- 用户名输入。
- 密码输入。
- 保存后立即影响后续网络请求。
- 代理连通性测试按钮。
- 自定义测试 URL 输入与测试按钮。

连通性测试规则：

- 测试项固定为 Google、Cloudflare、Baidu 三个地址。
- 三个固定测试项常驻显示，但未测试过时不显示成功灯或失败灯，只显示站点名称和待测状态。
- 每个地址测试完成后独立显示成功或失败，建议使用绿色对勾/圆点和红色叉/圆点表达状态。
- 测试不替用户做最终判断；不同网络环境下，三项结果只作为参考。
- 测试在代理未启用时也可运行；未启用时走当前系统/直连网络路径，启用时走内置代理路径。
- 技术实现应使用应用内 HTTP(S) 轻量请求，而不是系统 ICMP ping；ICMP 不会经过 HTTP/SOCKS 代理，不能验证本计划的代理链路。
- 自定义测试使用用户输入的 URL，结果单独显示；URL 保存到 `config.yaml`，但不影响三个固定测试项和代理请求路由。

所有新增 UI 文案必须同步维护：

- `i18n/zh_CN.json`
- `i18n/zh_TW.json`
- `i18n/en_US.json`
- `i18n/ja_JP.json`

## 7. 代码结构

建议新增：

- `utils/proxy_preferences.py`：代理配置模型、默认值、读写、归一化。
- `utils/network_middleware.py`：统一构造代理 URL、脱敏 URL、封装 HTTP(S) 请求、下载流和连通性测试，并提供受控 DashScope 代理环境执行 helper。
- `gui/workers/` 或设置页内轻量 worker：执行代理连通性测试，避免阻塞 UI。

建议改造：

- `utils/ai_model_middleware.py`：OpenAI-compatible 请求改走 `network_middleware`。
- `utils/cloud_models.py`：模型列表拉取改走 `network_middleware`。
- `utils/ffmpeg_downloader.py`：下载改走 `network_middleware`。
- `utils/llamacpp_downloader.py`：release 查询和下载改走 `network_middleware`。
- `gui/pages/settings_page.py`：新增代理设置控件和保存信号。
- `gui/pages/settings_page.py` 或专用 worker：连通性测试必须通过 `network_middleware` 发起请求，保持与真实联网入口一致的代理规则。
- `utils/ARCHITECTURE.md`、`docs/runtime-middleware.zh_CN.md`：功能落地后补充网络中间件职责边界。

## 8. 里程碑

### M01：代理配置模型与持久化

交付：

- 新增代理偏好封装。
- 支持 HTTP、HTTPS、SOCKS5、远程 DNS、host、port、username、password、enabled、custom_test_url。
- 默认关闭代理。

验收：

- 手动保存和读取配置稳定。
- 无效配置不会让应用启动失败。
- 不需要 UI 也能通过 helper 获取归一化配置。

边界：

- 不直接修改模型预设结构。
- 不在业务模块中散落 `network/proxy/...` key。

### M02：统一网络中间件与脱敏

交付：

- 新增统一网络请求入口，优先基于 `requests` 处理 CharaPicker 自有 HTTP(S) 请求。
- 支持从代理偏好构造 HTTP/HTTPS/SOCKS5 proxies dict。
- 支持流式下载，供 FFmpeg 和 llama.cpp 下载器复用。
- 提供 URL、代理 URL 和错误文本脱敏 helper。
- 提供 `run_with_proxy_environment()` 或等价 helper，用于 DashScope SDK 这种无法完整按请求传入代理的第三方调用。

验收：

- 代理关闭时行为与当前一致。
- 代理开启时 CharaPicker 自有 HTTP(S) 请求显式使用配置中的代理。
- 带用户名密码的代理 URL 在日志和 UI 错误中被脱敏。
- DashScope 适配 helper 设置和恢复环境变量时必须成对执行；异常情况下也要恢复原始环境。
- 直接使用 `urllib.request.urlopen` 的旧入口被移除或只保留在 `network_middleware` 内部，业务模块不再直接调用。

边界：

- 第一版不得降级为只支持 HTTP/HTTPS；SOCKS5 和远程 DNS 是必选能力。
- 如果 `requests + PySocks` 无法在不产生不安全全局副作用的前提下满足 SOCKS5，实施者应暂停并提出最小依赖或适配方案，而不是静默改范围。
- 不使用 PySocks 的全局 socket monkey patch 作为默认方案。
- 不把代理环境变量永久设置为进程全局状态；只在 DashScope 这类无法完整按请求传代理的第三方调用中，用锁保护的临时环境变量上下文。

### M03：接入现有联网入口

交付：

- 模型请求、模型列表、FFmpeg 下载、llama.cpp release 查询和下载、连通性测试全部改走网络中间件。

验收：

- 代理关闭时可按现有方式请求。
- 代理开启时上述入口都会使用代理。
- 任何已知联网入口不得在代理开启时静默直连。
- 所有程序内联网动作共享 `network_middleware` 的同一套代理配置、脱敏和锁策略。
- 失败日志不泄露 API Key、代理密码或带凭据 URL。

边界：

- 不改变模型请求 payload、prompt、token 统计和下载解压逻辑。

### M04：DashScope 代理适配验证

交付：

- 将 DashScope 视频请求纳入全局代理策略。
- 由于当前 SDK 版本不支持完整按请求代理，DashScope 调用通过受控环境变量适配：临时设置 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 及小写变体，调用结束后恢复原值。
- DashScope 代理执行必须使用全局网络锁，避免临时环境变量影响并发网络请求。
- 如果受控环境变量方案在本地验证失败，则代理开启时该路径必须 fail closed：停止请求并给出明确用户提示，不得静默直连。

验收：

- 开启代理后，DashScope 请求要么确认走代理，要么被明确阻止并提示当前路径暂不支持代理。
- 不存在代理开启但 DashScope 仍直接联网的路径。
- DashScope 本地视频请求触发的 OSS 上传和最终模型请求都在同一代理环境保护范围内。
- DashScope 调用结束后，进程环境变量恢复到调用前状态。

边界：

- 不为了 DashScope 单一路径引入全局副作用不可控的 monkey patch。
- 若未来升级到支持完整按请求 session 的 SDK，也必须重新核对本地文件 OSS 上传路径是否同样支持代理，不能只验证最终模型请求。

### M05：设置页 UI 与 i18n

交付：

- 设置页新增代理配置区域。
- 设置页新增常驻代理连通性测试区域。
- 四个语系补齐文案。
- 保存后后续网络请求立即使用新配置。

验收：

- 用户能开启、关闭、修改代理配置。
- 用户未运行测试前，Google、Cloudflare、Baidu 三项不显示成功或失败状态灯。
- 用户能分别看到 Google、Cloudflare、Baidu 的测试成功/失败状态。
- 用户能输入自定义 URL、保存到 `config.yaml`，并运行自定义连通性测试。
- 用户重新打开设置页后能看到上次保存的自定义测试 URL。
- 代理关闭时也能运行测试，并明确走当前直连/系统网络路径。
- 密码输入不明文显示。
- UI 文案清晰说明凭据保存在本地 `config.yaml`。

边界：

- 设置页只负责读写偏好、触发测试和展示反馈，不直接散落网络请求细节。

### M06：验证与文档同步

交付：

- 运行可用的静态检查或导入检查。
- 更新运行时中间件文档和 utils 架构说明。
- 根据完成情况更新 `docs/TODO.zh_CN.md`。

验收：

- 代理相关代码路径经过手动或脚本验证。
- 文档与实际实现范围一致。

## 9. 验证与自审查

验证建议：

- 代理关闭：模型列表、模型测试和下载功能保持原行为。
- HTTP/HTTPS 代理开启：确认模型列表和 OpenAI-compatible 请求走代理。
- SOCKS5 代理开启：确认至少一个模型列表或下载请求走 SOCKS5。
- SOCKS5 远程 DNS 开启/关闭：确认构造出的代理行为符合开关含义。
- 连通性测试：未测试前不显示成功/失败灯；测试后 Google、Cloudflare、Baidu 三项能独立显示成功或失败，且代理关闭时也可运行。
- 自定义测试：用户输入一个 HTTP(S) URL 后能保存、单独测试并显示结果。
- 代理凭据错误：UI 反馈可读，日志不泄露密码。
- DashScope 视频请求：单独记录验证结论。
- 运行 `python -m ruff check .`，若当前环境安装 Ruff。

自审查重点：

- 所有联网入口是否收口到网络中间件。
- DashScope 代理环境 helper 是否和其他网络请求共享同一把锁，避免并发时环境变量串扰。
- 日志是否包含代理密码、API Key 或完整 Authorization 信息。
- UI 文案是否四语系同步。
- `requirements.txt` 与 `pyproject.toml` 依赖是否一致；如果项目代码直接使用 `requests`，应显式声明 `requests`，不要只依赖 DashScope 的传递依赖。
- 是否有全局 opener 或环境变量副作用影响测试、构建或非联网本地操作。

## 10. 提交分组

建议提交 1：`feat: add proxy preference storage`

- 覆盖 M01。
- 提交前检查配置读写和默认值。

建议提交 2：`feat: route urllib requests through network middleware`

- 覆盖 M02、M03。
- 提交前检查模型请求、模型列表和下载器调用点。

建议提交 3：`feat: expose proxy settings and connectivity test`

- 覆盖 M05。
- 提交前检查四语系文案和设置页布局。

建议提交 4：`docs: document runtime proxy behavior`

- 覆盖 M04、M06。
- 提交前确认 TODO 状态与实际实现范围一致。

## 11. 验收后收尾

仅在用户试用通过、已知代理 bug 修复后进行：

- 删除临时调试日志和手动测试入口。
- 清理未使用 import、重复脱敏逻辑和未用 i18n key。
- 检查打包依赖与 CI 安装依赖是否一致。
- 若功能范围稳定，再考虑把长期事实沉淀到 `AGENTS.md` 或普通架构文档。

## 12. 固定测试目标

第一版固定测试目标：

- Google：`https://www.google.com/generate_204`
- Cloudflare：`https://www.cloudflare.com/cdn-cgi/trace`
- Baidu：`https://www.baidu.com/`

测试规则：

- 每项设置短超时，建议 5 秒。
- 优先使用轻量请求；如果使用 `HEAD` 遇到不支持的站点，可回退到 `GET`。
- 能完成 TCP/TLS 握手并收到 HTTP 响应即视为网络可达；实现可把 2xx、3xx 和 4xx 视为成功，把超时、DNS 失败、代理连接失败、TLS 失败和 5xx 视为失败。
- UI 可显示简短错误原因，但必须先脱敏。

## 13. DashScope 代理接入结论

- 当前项目环境 `dashscope==1.24.6`：`HttpRequest` 内部直接创建 `requests.Session()`，`_get_protocol_params()` 不接收 `session`，因此不能按请求传入代理 session。
- DashScope SDK main 分支：`api_request_factory.py` 已读取 `session` 并传给 `HttpRequest`，但 `utils/oss_utils.py` 的 OSS 上传仍直接创建 `requests.Session()`；多模态本地视频会先经过该上传链路。因此只传 `session` 仍不能完整覆盖 CharaPicker 当前 DashScope 视频路径。
- `requests` 在未显式传 `proxies` 时会读取 `http_proxy`、`https_proxy`、`all_proxy` 及大写变体；SOCKS 需要额外依赖，且 `socks5` 为本地 DNS、`socks5h` 为代理端 DNS。
- 第一版 DashScope 适配采用受控环境变量方案，并由 `network_middleware` 提供锁、设置、恢复、脱敏和 fail closed 语义。
