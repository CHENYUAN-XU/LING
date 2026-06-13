# Video Companion 接入运行手册

Video Companion 已作为外部独立项目放在 `E:\视觉\video-companion`。Project Mnemosyne 不在主仓库内实现实时视频通话、连续摄像头帧理解、麦克风链路或视觉模型抽帧状态机，只通过 HTTP/WebSocket 接入外部服务。

## 推荐端口

| 服务 | 推荐端口 | 说明 |
| --- | --- | --- |
| Project Mnemosyne | `8001` | 主项目、聊天、人格、记忆、接入 UI |
| Video Companion | `8782` | 外部实时视频服务，避免抢主项目的 `8001` |

## 主项目配置

`config.yaml` 保持这组配置：

```yaml
video_companion:
  enabled: true
  base_url: http://127.0.0.1:8782
  ws_url: ws://127.0.0.1:8782/ws
  project_path: "E:\\视觉\\video-companion"
  timeout_seconds: 3
```

开发或验收前可以先保持 `enabled: false`，确认外部服务能跑后再改成 `true`。

## Video Companion 配置

在 `E:\视觉\video-companion` 创建或更新 `config.yaml`：

```yaml
server:
  host: "127.0.0.1"
  port: 8782
  cors_origins:
    - "http://127.0.0.1:8001"

legacy_bridge:
  enabled: true
  api_base: "http://127.0.0.1:8001"
  api_key_env: "MNEMOSYNE_API_KEY"
  timeout: 10
  retries: 2
```

`legacy_bridge.enabled: true` 后，Video Companion 会向主项目调用：

- `GET /api/video/session-context?persona_id=...`
- `POST /api/video/session-summary`
- `POST /api/video/observation`
- `POST /api/video/consent`
- `POST /api/video/turn`

如果环境变量 `MNEMOSYNE_API_KEY` 已设置，主项目会要求这些 `/api/video/*` 回调带 `Authorization: Bearer <MNEMOSYNE_API_KEY>`。Video Companion 的 `legacy_bridge.api_key_env` 默认也是 `MNEMOSYNE_API_KEY`，所以两边用同一个环境变量即可。未设置该变量时，本机开发模式允许无 token 回调。

## 启动

手动启动：

```powershell
cd "E:\澪\project-mnemosyne"
py -m uvicorn app.server:app --host 127.0.0.1 --port 8001
```

```powershell
cd "E:\视觉\video-companion"
py -m app.server
```

或者在主项目中运行：

```powershell
cd "E:\澪\project-mnemosyne"
.\scripts\start_integrated_video_companion.ps1
```

启动脚本不会修改长期 `config.yaml`。它会在启动主项目进程时设置：

- `MNEMOSYNE_VIDEO_COMPANION_ENABLED=true`
- `MNEMOSYNE_VIDEO_COMPANION_BASE_URL=http://127.0.0.1:<VideoPort>`
- `MNEMOSYNE_VIDEO_COMPANION_WS_URL=ws://127.0.0.1:<VideoPort>/ws`

脚本默认查找顺序：

- 显式 `-VideoPath` 参数
- `MNEMOSYNE_VIDEO_COMPANION_PROJECT_PATH`
- 当前盘根目录的 `E:\视觉\video-companion`
- 工作区旁边的 `视觉\video-companion`

启动后默认会等待两个健康检查通过：

- `http://127.0.0.1:<MainPort>/api/health`
- `http://127.0.0.1:<VideoPort>/api/health`

常用参数：

```powershell
.\scripts\start_integrated_video_companion.ps1 -MainPort 8001 -VideoPort 8782
.\scripts\start_integrated_video_companion.ps1 -VideoPath "E:\视觉\video-companion"
.\scripts\start_integrated_video_companion.ps1 -HealthTimeoutSeconds 60
.\scripts\start_integrated_video_companion.ps1 -SkipHealthCheck
.\scripts\start_integrated_video_companion.ps1 -DryRun
```

## 验收

主项目：

```powershell
cd "E:\澪\project-mnemosyne"
py scripts\verify_all.py
```

包含真实双服务桥接的端到端冒烟：

```powershell
cd "E:\澪\project-mnemosyne"
py scripts\verify_all.py --video-e2e
```

这个脚本会在临时端口启动 Project Mnemosyne 和 `E:\视觉\video-companion`，用临时 SQLite 验证：主项目可提供人格上下文、Video Companion 可启动/停止会话、授权允许时 summary 能回写为“视频会话摘要”聊天记录和 `world_observations`。

Video Companion：

```powershell
cd "E:\视觉\video-companion"
py run_tests.py
```

健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8001/api/health -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8782/api/health -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8001/api/video-companion/status -UseBasicParsing
```

保存视频会话摘要需要在 Video Companion 侧显式授权，或在它自己的 `privacy.defaults.save_summary` 中开启：

```powershell
Invoke-WebRequest -Method POST http://127.0.0.1:8782/api/consent/save_summary/grant -UseBasicParsing
Invoke-WebRequest -Method POST http://127.0.0.1:8782/api/consent/save_summary/revoke -UseBasicParsing
```

普通端资料面板里的 `Video Companion` 区块会显示外部服务状态，并提供：

- `打开视频页`：打开外部视频服务页面。
- `启动会话`：主项目调用外部 `/api/session/start?persona_id=...`。
- `停止会话`：主项目调用外部 `/api/session/stop`，并保存返回的摘要。
- 保存摘要时会尊重外部返回的 `consent.save_summary`；如果外部未授权保存摘要，主项目不会自动落库。

## 落地边界

- 主项目负责人格、长期记忆、聊天记录、用户账号、资料页入口和会话摘要落库。
- Video Companion 负责摄像头、麦克风、ASR/TTS、实时视觉理解、视频会话状态和低延迟互动。
- 会话结束后，主项目会把 Video Companion 返回的摘要保存为一条“视频会话摘要”聊天记录，并写入 `world_observations` 作为外部会话观察。
- 视觉观察只有在 payload 带 `persona_id` 时才会落到主项目，避免无法归属的数据污染记忆。
