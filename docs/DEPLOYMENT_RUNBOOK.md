# LING 本地运行手册

LING 当前面向作者本人使用。默认部署形态是 Windows 本机、单个 FastAPI 进程、SQLite、VTube Studio，以及可选的外部 Video Companion。它不是多人公网聊天服务，直播能力也不应改变这套默认边界。

## 1. 本地预检

```powershell
cd "E:\澪\project-mnemosyne"
py scripts\check_environment.py
py scripts\check_deployment.py --self-use
py scripts\verify_all.py --video-e2e
```

若当前机器的 `py` 找不到解释器，使用实际 Python：

```powershell
& 'C:\Users\Yue\AppData\Local\Programs\Python\Python314\python.exe' scripts\check_deployment.py --self-use
```

`--self-use` 会确认 localhost 边界、cookie 模式、运行目录写权限和外部 Video Companion 路径。尚未配置的聊天或语音 API key 只会提示，不会把空白自用工作区误判为不可运行。

## 2. 启动

```powershell
scripts\start_local_server.ps1
```

或直接运行：

```powershell
py -m uvicorn app.server:app --host 127.0.0.1 --port 8001
```

- LING：`http://127.0.0.1:8001`
- 调试管理台：`http://127.0.0.1:8001/admin`
- 本地 HTTP 必须保持 `security.secure_cookies: false`。
- `self_use.enabled` 与 `self_use.require_localhost` 应保持 `true`。
- 不要为方便访问改成 `0.0.0.0`；远程访问不是当前默认产品边界。

## 3. Live2D / VTube Studio

1. 先启动 VTube Studio 并开启 Plugin API。
2. 在 LING“接入”面板启用 Live2D。
3. 首次连接时在 VTube Studio 接受授权。
4. 在“编辑形象”中读取并绑定当前模型。
5. 用 Idle、Listen、Think、Talk 控件检查实际动作映射。

LING 会在启动时进行有界重连。主动点击断开后，本进程不会立刻自动连回。切换 VTS 模型后刷新能力；模型、热键和表情快照必须整组刷新成功才会重新标记就绪。

## 4. 普通回复语音

普通文字回复语音由主项目的 OpenAI TTS 适配器负责，默认关闭。启用前设置配置所引用的环境变量，并在澪的形象绑定中填写实际 provider voice ID。

Edge TTS 不属于 LING 的语音方案。实时麦克风、ASR 和视频会话语音属于外部 Video Companion。

## 5. 外部 Video Companion

外部项目位于 `E:\视觉\video-companion`。主项目只负责启动代理、授权/状态展示、上下文提供、观察与摘要回写，不实现摄像头帧循环、麦克风状态机或视频会话 UI。

集成启动：

```powershell
scripts\start_integrated_video_companion.ps1
```

“接入”面板应分别显示：

- 外部服务是否在线；
- `session_state` 是否为 `active`；
- 当前授权项；
- 最近视觉观察及其 freshness；
- 最近摘要回写；
- 最近授权同步。

## 6. SQLite 与备份

本地单进程继续使用 WAL、busy timeout 和 foreign keys。`GET /api/health` 会报告实际 SQLite 状态。

```powershell
py scripts\backup_data.py --label before-change
py scripts\restore_data_backup.py data\backups\mnemosyne-backup-YYYYMMDD-HHMMSS.zip --inspect-only
py scripts\restore_data_backup.py data\backups\mnemosyne-backup-YYYYMMDD-HHMMSS.zip --restore-dir data\restore-drill
```

备份包含 SQLite 一致性快照、上传的形象素材及 manifest。恢复只写入新的旁路目录；确认结果后再人工替换运行数据。

## 7. 日用与休眠检查

每次较大改动或系统更新后观察：

1. 启动 LING，确认首页直接进入澪的 embodied workspace。
2. VTube Studio 晚启动时，确认 LING 能在有界重试内连接。
3. 切换 VTS 模型，确认旧动作不会与新模型混用。
4. 打断生成中和播放中的语音，确认旧播放不会覆盖新一轮状态。
5. 启停外部 Video Companion，确认 8 秒状态轮询不会积压请求或清空正在编辑的表单。
6. Windows 休眠再唤醒后，确认 Live2D/Video 状态会恢复或明确显示断开。
7. 检查 `/api/health`、`logs/app.log`、SQLite 写入和最新备份。

自动化通过不等于上述真机观察已经完成。

## 8. 回滚

1. 停止 FastAPI 与外部 Video Companion。
2. 保留当前日志和数据库副本。
3. 将最近备份恢复到新的旁路目录并检查。
4. 人工切换确认过的数据库与上传目录。
5. 重新运行 `check_deployment.py --self-use` 和 `verify_all.py --video-e2e`。

## 9. 非当前目标：公网部署

若未来明确需要公网或多人访问，再单独设计 HTTPS、secure cookie、反向代理、集中限流、PostgreSQL/MySQL、Redis 和多 worker 一致性。现有 `--production` 预检仍保留这些公网约束，但它不代表当前 LING 自用完成标准。
