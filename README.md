# LING

LING 是一个面向作者本人使用的 AI VTB / 具身数字陪伴体项目。澪是唯一产品主体：Live2D / VTube Studio 形象、文本与语音回应、表情动作、长期记忆和外部实时感知围绕同一个 companion 状态组织。

它不是多人格聊天平台。仓库中仍保留部分 Project Mnemosyne 的账号、人格、群聊和记忆代码，用于数据兼容与调试；在默认自用模式中，这些旧结构不会驱动首页，也不会创建第二个 companion。

## 当前体验

- 本地打开后直接进入澪的具身 workspace，不经过登录或人格生成向导。
- 第一屏以 Live2D 身体和在场状态为主，文字 session、资料、历史和接入工具是辅助层。
- 本地 Presence 默认开启；第一屏可切换“安静模式 / 恢复在场”，这不会自动开启主动消息。
- 澪的基础资料默认空白，不会用系统生成的人设替作者填写。
- 聊天 API 默认关闭，并要求作者显式检测路由后才能启用。
- Live2D 默认关闭；启用后应用启动会尝试非阻塞连接 VTube Studio。
- 普通文字回复 TTS 默认关闭，使用 OpenAI TTS 适配器，不使用 Edge TTS。
- 实时摄像头、麦克风、ASR、连续视觉理解和视频会话语音由外部 Video Companion 负责。
- 屏幕感知与主动消息默认关闭，资料页必须分别启用配置并授予授权；启用主动能力不会自动启动 scheduler。

## 启动

环境：Python 3.11+，Node.js 仅用于前端语法验证。

```powershell
cd "E:\澪\project-mnemosyne"
py -m pip install -r requirements.txt
scripts\start_local_server.ps1 -OpenBrowser
```

日用关闭：

```powershell
scripts\stop_local_server.ps1
```

启动脚本会自动寻找可用 Python、运行 localhost 自用预检、拒绝占用 8001 的非 LING 进程，并把 PID/state 写到 `data/runtime/`、日志写到 `logs/`。关闭脚本通过 stop request 让 uvicorn 执行应用 shutdown hook；直接运行 uvicorn 只用于前台调试。

打开：

```text
LING workspace: http://127.0.0.1:8001
维护调试台:      http://127.0.0.1:8001/admin
```

默认 `config.yaml` 使用本地自用模式：

```yaml
self_use:
  enabled: true
  username: mio_owner
  default_persona_name: 澪
  chat_enabled: false
```

本地自用身份由应用自动建立并持久化。唯一 companion 使用 SQLite ID 绑定，因此改名不会切换到历史人格数据。

## 模型接入

聊天路由只读取环境变量中的 API key。不要把密钥写入 `config.yaml`、网页输入框或 Git。

默认示例：

```yaml
llm_routes:
  chat:
    provider: kimi
    model: moonshot-v1-auto
    base_url: https://api.moonshot.cn/v1
    api_key_env: MOONSHOT_API_KEY
```

设置环境变量并重启终端后，在 LING 的“接入”面板执行“检测连接”。检测模型目录不会生成聊天文本。只有检测成功后，聊天闸门才允许手动开启；环境变量存在本身不等于 API 已连接。

## Live2D / VTube Studio

LING 通过 VTube Studio Public API 驱动外部 Live2D 身体，本仓库不在网页中重新实现 Live2D 渲染器。

1. 启动 VTube Studio 并开启插件 API。
2. 在 LING“接入”面板设置 VTS WebSocket 地址，默认 `ws://127.0.0.1:8002`。
3. 启用 Live2D，接受 VTube Studio 的首次授权。
4. 将当前 VTS 模型绑定给澪。
5. 从 VTS 实际发现的 expression / hotkey 中设置 Idle、Listen、Think 和 Talk 动作。
6. 确认嘴型输入参数（默认 `MouthOpen`）在接入面板显示 ready；普通回复音频播放时会驱动该参数，结束或打断后归零。

连接就绪要求：

- Live2D 配置已启用；
- WebSocket 已连接并认证；
- VTube Studio 当前加载了模型；
- 当前模型 ID 或名称与澪的 `live2d_model_id` 一致。
- 配置的嘴型输入参数存在于当前 VTube Studio 参数列表中。

应用重启时会后台尝试自动连接，不会因 VTube Studio 未启动而阻塞 LING。静态资源只按以下顺序回退：

```text
Live2D -> live2d_preview_url -> fallback_image_url -> legacy avatar_url
```

本地自用界面的预览图和 fallback 图通过独立的形象素材上传入口保存；旧头像上传只服务兼容模式，不是 LING 的形象主路径。

## 普通回复语音

主项目只负责文字回复的普通 TTS 播放：

```yaml
voice:
  enabled: false
  tts_provider: openai_tts
  tts_model: gpt-4o-mini-tts
  api_key_env: OPENAI_API_KEY
  voice_id: alloy
  response_format: mp3
  auto_play: true
```

在“接入”面板配置 provider voice ID，并可将当前 voice ID 绑定到澪的 `voice_profile`。语音真正开始播放后才触发 Live2D Talk，结束或被新输入打断后回到 Idle。

实时麦克风、ASR、低延迟可打断语音和视频会话状态机不在这里实现。

## 外部 Video Companion

外部项目固定边界：

```text
E:\视觉\video-companion
```

主项目通过 `app/video_companion.py` 与 `app/video_bridge.py` 负责：

- 外部服务配置与健康状态；
- 会话启动/停止代理；
- 澪、用户、记忆和授权上下文；
- 授权后的 observation / summary 回写；
- 把外部 session 反映到 LING 的统一在场状态。

主项目自用模式拒绝旧内部 MJPEG camera API。摄像头采集、预览、麦克风和连续理解全部留在外部项目。完整边界见：

- `docs/VIDEO_COMPANION_PROJECT_PLAN.md`
- `docs/VIDEO_COMPANION_INTEGRATION_RUNBOOK.md`

## 数据与安全

- 本地数据库：`data/app.db`
- SQLite：WAL、`busy_timeout`、foreign keys
- 上传：`data/uploads/`
- 备份：`data/backups/`
- 日志：`logs/app.log`

这些运行数据不会进入 Git。完整备份与旁路恢复：

```powershell
py scripts\backup_data.py --label before-change
py scripts\restore_data_backup.py data\backups\ling-backup-YYYYMMDD-HHMMSS.zip --inspect-only
py scripts\restore_data_backup.py data\backups\ling-backup-YYYYMMDD-HHMMSS.zip --restore-dir data\restore-drill
```

本地长期运行与恢复流程见 `docs/DEPLOYMENT_RUNBOOK.md`。当前 SQLite 方案适合个人单实例；公开多人或多 worker 部署不属于当前产品目标。

## 验证

每次代码改动必须运行：

```powershell
py scripts\verify_all.py --video-e2e
git diff --check
```

`--video-e2e` 会临时启动主项目与外部 Video Companion，验证上下文、会话代理、授权观察和摘要回写。全绿只表示自动化覆盖通过，不等于真实 Live2D 模型、真实 TTS 或真实摄像头设备已经完成日用验收。

全量验证还包含本地自用并发 soak：状态轮询与资料写入并行运行后检查唯一澪绑定和 SQLite 完整性。它不替代 Windows 休眠唤醒或真实硬件长时间运行观察。

部署预检：

```powershell
py scripts\check_environment.py
py scripts\check_deployment.py --self-use
```

`--production` 只用于未来明确的 HTTPS 公网部署，不是当前 LING 自用完成标准。

只读日用验收报告（不会调用外部模型 API）：

```powershell
py scripts\check_acceptance.py
py scripts\check_acceptance.py --json
```

报告把自动就绪、待配置、真机人工验收和可选能力分开。`--strict` 仅用于需要“所有必需项连同真机验收都完成才返回成功”的场景。

真实设备测试完成后，由作者显式记录本地验收凭证：

```powershell
py scripts\record_acceptance.py accept live2d --note "VTS 重启重连、Idle/Listen/Think/Talk 均已实测"
py scripts\record_acceptance.py list
py scripts\record_acceptance.py revoke live2d
```

只有自动前置已达到 `MANUAL` 的检查才能记录。凭证绑定当前配置和 companion 绑定证据；模型、voice ID 或连接配置改变后会标记过期，不会继续冒充已验收。

## 目录

```text
app/       FastAPI、记忆、Live2D、语音和外部桥接
web/       LING 具身 workspace 与 PWA shell
admin_web/ 维护与历史调试台
docs/      路线、部署、隐私和 Video Companion 边界
scripts/   受管启动/关闭、回归验证、备份、恢复和部署检查
```

当前完成定义与剩余真实门槛见 `SYSTEM_PLAN.md` 和 `docs/LING_ROADMAP.md`。

## Git 约定

目标仓库为 [thefoolsparkle-oss/LING](https://github.com/thefoolsparkle-oss/LING)。除非作者当前明确要求，否则不要 commit、push 或上传。
