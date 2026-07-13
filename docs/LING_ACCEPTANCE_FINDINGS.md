# LING 真机接入与日用验收问题记录

更新日期：2026-06-23

本文记录作者实际接入和使用 LING 时发现的问题，供后续集中修复。这里的条目不等于已经解决，也不能替代 `scripts/check_acceptance.py` 的验收状态。

## 记录原则

- 不记录 API key、token、完整环境变量值或其他秘密。
- 区分已确认事实、待验证假设和后续处理方向。
- 先测量再优化；自动化通过不代表真实日用体验合格。
- 不借修复这些问题扩张多人格、群聊、头像系统或主仓库内部视频能力。

## 当前问题

### A-001 API 接入入口与说明不清晰

状态：待处理  
影响：高

已确认事实：

- 首页提供“检测”“开启对话”等操作，但没有在操作前清楚说明聊天路由来自 `config.yaml`、真实 key 来自 Windows 环境变量。
- “接入”面板只展示聊天 provider、model、base URL、key 环境变量名和状态，不能编辑聊天路由；这与 Live2D、Voice、Video 卡片可直接编辑部分配置的交互不一致。
- readiness 卡片会截断状态文字，失败时作者难以知道下一步应去哪里处理。

后续方向：

- 在 API 卡片明确写出“密钥只放环境变量，不写入 YAML 或网页”。
- 提供可发现的路由配置说明或安全的本地路由编辑入口，但继续禁止在浏览器保存 key。
- 检测前展示目标 provider、model、base URL 和 key 环境变量名；检测失败时给出明确下一步。

### A-002 模型连接错误信息丢失

状态：待处理  
影响：高

已确认事实：

- 一次真实模型目录检测在约 8 秒后显示 `connection check failed with status unreachable`。
- `app/llm_client.py` 捕获 `requests.RequestException` 后只保留 HTTP 状态码；DNS、TLS、连接超时和读取超时都被折叠成 `unreachable`。
- 请求日志只记录本地 `/api/self-use/llm-probe` 返回 200，不能说明外部请求为何失败。
- 随后的不带 key 连通性检查和真实路由检测均成功，说明此前至少包含一次瞬时失败。

后续方向：

- 将安全、脱敏后的失败类型区分为 DNS、连接、TLS、超时、HTTP 认证和服务端错误。
- 记录 provider、目标主机、耗时、异常类型和 request id，不记录 URL 查询参数、Authorization 或 key。
- UI 对瞬时网络问题提供可理解的重试建议。

### A-003 首次真实聊天响应过慢

状态：待测量  
影响：高

已确认事实：

- Moonshot 中国区路由验证成功，聊天闸门开启，作者已收到一次真实回复。
- 作者主观确认这次回复速度明显过慢，尚未记录精确耗时。
- 当前尚不能判断瓶颈来自模型、网络、prompt/记忆组装、非流式等待、数据库写入还是前端呈现。

后续测量：

1. 记录点击发送到服务端收到请求的时间。
2. 分别记录 prompt/记忆组装、外部模型请求、回复解析、数据库写入和前端渲染耗时。
3. 若 provider 支持流式响应，比较首字时间与完整回复时间；确认当前实现是否必须等待整段完成。
4. 用短提示和正常对话各测多轮，区分冷启动、偶发抖动和稳定慢。
5. 检查超时、重试和错误回退是否无意中增加等待。

完成标准：

- 有可复现的分段耗时数据和基线，而不是只用总耗时猜测。
- 优化后真实多轮对话的首字反馈和完整回复达到作者可接受水平。

### A-004 环境变量生效范围和重启流程不透明

状态：待处理  
影响：中

已确认事实：

- LING 只应读取名为 `MOONSHOT_API_KEY` 的环境变量值，`config.yaml` 仅保存 `api_key_env: MOONSHOT_API_KEY`。
- 接入过程中曾出现 key 只存在于启动进程环境、用户级环境变量未设置的状态。
- UI 只显示 `Env state: present`，不能告诉作者更新环境变量后需要让受管 LING 进程重新继承环境。

后续方向：

- 在接入说明中明确“设置环境变量后重启 LING”。
- 受管启动器应稳定继承当前用户环境，并在不泄露值的前提下报告变量是否存在。
- 避免让作者通过编辑 `config.yaml` 猜测密钥放置位置。

### A-005 配置文件缺少秘密误填防护

状态：待处理  
影响：高

已确认事实：

- 接入过程中，API key 曾被误贴到 `llm_routes.chat` 行，导致 YAML 解析失败。
- 该明文已从 `config.yaml` 清除，配置已恢复，完整自动化验证通过。
- Git 中的 `config.yaml` 内容不包含该明文。

安全跟进：

- 确认误贴过的旧 key 已在 Moonshot 控制台撤销，后续只使用新 key。

后续方向：

- 部署预检检测配置文件中的常见 key/token 形态并给出阻断性错误，但日志必须脱敏。
- YAML 解析错误应报告安全的文件位置和修复提示，不回显包含秘密的原始行。
- README 与接入面板使用同一段简短、明确的密钥放置说明。

### A-006 Live2D 依赖外部 VTube Studio 常驻，不符合作者预期

状态：需要产品与架构调整  
影响：高

已确认事实：

- 当前 LING 只通过 VTube Studio WebSocket API 驱动 Live2D；VTube Studio 关闭后，LING 只能显示 preview、fallback 或占位图。
- 当前仓库没有内置 Live2D 渲染器。
- 作者的明确预期是只启动 LING 就能使用真正的 Live2D，不接受把 VTube Studio 设置为 Windows 开机常驻来掩盖该依赖。
- 接入过程中曾误创建 VTube Studio 开机启动项，该启动项已立即撤销。

后续方向：

- 重新评估是否在 LING 内嵌 Live2D 渲染与动作驱动能力，而不是要求作者单独运行 VTube Studio。
- 调研 Cubism SDK 授权、模型文件加载、Web/桌面渲染、参数驱动、动作/表情映射与嘴型输入的实现和分发边界。
- 在新架构落地前，UI 必须明确标注外部 VTube Studio 是当前真实依赖，不能把“Live2D 待接入”写成一次设置后即可独立运行。
- 不用自动启动、后台隐藏或托管 VTube Studio 进程冒充 LING 已具备内置 Live2D。

### A-007 缺少澪的正式 Live2D 模型资产

状态：外部资产阻塞  
影响：高

已确认事实：

- VTube Studio API 与 LING 的 WebSocket 连接已经实际打通。
- 作者目前没有澪自己的 Live2D 模型文件；VTube Studio 中显示的是自带示例模型。
- 没有正式模型时，无法完成模型绑定、Idle/Listen/Think/Talk 动作映射、嘴型参数确认和真实 Live2D 日用验收。
- 示例模型最多用于验证适配器，不能绑定成澪或记录为真实验收通过。
- 澪的外观设定目前仍应保持空白，不能为了推进验收由系统自动生成角色外观、经历或关系设定。

需要取得的交付物：

- 可合法用于个人 AI companion 项目的 Live2D 模型及明确授权。
- 主入口 `.model3.json`、纹理、物理配置，以及模型实际使用的参数定义。
- 可供 LING 映射的待机、倾听、思考、说话动作或表情；若制作方采用其他命名，需要附映射说明。
- 可驱动嘴型的输入参数名称和建议范围，优先确认是否兼容 `MouthOpen` 或提供等价参数。
- 允许在未来的 LING 内置渲染器中加载和运行，而不仅限于 VTube Studio 内使用。

后续方向：

- 先由作者决定澪的视觉方向，再选择定制委托、已有合法模型改造或自行制作；不能由项目代码默认填充外观。
- 在委托或购买前确认源文件、运行文件、修改权、个人使用权、AI companion 使用权和应用内嵌/分发限制。
- 取得模型后重新执行真实绑定、动作、嘴型、断线重连和模型切换验收。

### A-008 Video Companion 集成启动状态与验收脚本口径不一致

状态：待处理  
影响：中

已确认事实：

- 使用 `scripts/start_integrated_video_companion.ps1 -VideoPath "E:\视觉\video-companion"` 启动后，LING 主服务与外部 Video Companion 均可达。
- LING UI 中 `Video · 可选` 显示“外部服务已连接”，启动后显示“视频会话运行中”。
- 外部 Video Companion `/api/status` 返回 `session_state: active`，`mnemosyne.connected: true`，且 session persona_id 为稳定 companion id `5`。
- 摄像头、麦克风、外部视觉、摘要保存等授权默认均为 `false`，符合安全边界。
- 但在新 shell 中运行 `scripts/check_acceptance.py` 时，Video Companion 仍显示 `OPTIONAL: external Video Companion is disabled`。当前原因是集成启动脚本通过进程环境变量临时启用 Video Companion，而验收脚本读取长期 `config.yaml`/当前脚本进程环境，无法感知已运行主服务的临时集成状态。

后续方向：

- 明确 `check_acceptance.py` 的语义：它究竟检查长期配置，还是检查当前运行实例状态。
- 若用于日用验收，应考虑读取运行中 LING 的 `/api/companion/status` 或 Video Companion status，并在报告中区分“长期配置 disabled”和“当前集成启动 enabled”。
- UI 和脚本应使用同一套状态解释，避免作者看到 UI 已连接但命令行仍显示 disabled。
- 保留安全默认：未显式授权前，不应把 camera/microphone/external_vision/save_summary 视为已通过。

### A-009 Video Companion 的应用授权与浏览器媒体权限状态混淆

状态：待处理  
影响：高

已确认事实：

- 作者在外部 Video Companion 页面确认摄像头和麦克风入口看起来可用。
- 通过 REST 打开 `camera` 与 `microphone` consent 后，后端 `/api/status` 显示 `camera: true`、`microphone: true`，session 为 `active`。
- 但前端页面仍显示“摄像头未开启 / 摄像头: 关闭”，指标中 `frames_received=0`、`chunks_received=0`。
- 重新触发前端摄像头开关后，页面返回 `摄像头: Permission denied`。
- 说明当前至少存在三层状态：浏览器站点权限、Video Companion 应用 consent、真实 WebSocket 帧/音频流；它们不同步时，UI 和验收脚本容易误判。

后续方向：

- Video Companion UI 应同时展示“浏览器媒体权限”“应用 consent”“后端是否收到帧/音频 chunk”三种状态，不能只显示一个开关。
- 当前端 `getUserMedia` 返回 `Permission denied` 时，应提供明确操作提示：在浏览器地址栏/站点权限中允许 `127.0.0.1:8782` 使用摄像头和麦克风，然后重新打开开关。
- LING 主项目的 Video Companion 状态不应仅凭 session active 判定真实视频可用；至少要显示最近帧时间、帧数、音频 chunk 或明确的权限错误。
- 未来验收应以“后端实际收到帧/音频数据”为准，而不是只看 consent 或 session 状态。

## 本轮已完成基线

- Moonshot 中国区 `https://api.moonshot.cn/v1` 路由已验证。
- 聊天闸门已开启，真实回复成功返回。
- `scripts/verify_all.py --video-e2e` 已通过。
- 聊天模型验收仍为 `MANUAL`：还需多轮真实回复和记忆连续性观察，不能仅凭一次回复记录为完成。
