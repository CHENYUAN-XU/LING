# 生产部署运行手册

这份手册面向 VPS、云服务器或 PaaS。当前项目仍以单实例 FastAPI + SQLite 为主，适合个人自用、小规模内测或直播展示；多人公开使用前再迁移 PostgreSQL/MySQL，并把限流移动到 Redis 或反向代理层。

## 1. 部署前检查

```powershell
py scripts\check_environment.py --strict
py scripts\check_deployment.py --production
py scripts\verify_all.py --video-e2e
```

`check_deployment.py --production` 会把以下问题视为阻塞：

- 配置引用的 API Key 环境变量缺失。
- `config.yaml` 中出现疑似明文密钥。
- `rate_limit.enabled` 未开启。
- 请求日志未开启。
- HTTPS 部署仍未启用 `security.secure_cookies`。
- `data/`、`data/uploads/` 或 `data/backups/` 不可写。
- 主项目启用 Video Companion 但外部项目路径不存在。

## 2. HTTPS 与 Cookie

正式域名必须走 HTTPS。反向代理确认只转发 HTTPS 后，把 `config.yaml` 改为：

```yaml
security:
  secure_cookies: true
```

本地 `http://127.0.0.1` 开发时保持 `false`，否则浏览器不会发送 session cookie。

## 3. 反向代理建议

FastAPI 进程建议只监听本机：

```powershell
py -m uvicorn app.server:app --host 127.0.0.1 --port 8001
```

公网入口交给 Nginx、Caddy 或云平台反向代理处理 TLS、压缩和访问日志。上传目录 `/uploads` 由应用静态挂载；生产前要确认反向代理请求体大小允许头像上传。
头像上传后端只接受 jpg/png/webp/gif、5MB 以内文件，并校验文件头；手填头像链接只允许 `/uploads/...`、`http://...` 或 `https://...`；反向代理层也建议设置接近的请求体大小上限。

## 4. SQLite 与备份

默认 SQLite 配置：

```yaml
database:
  journal_mode: wal
  busy_timeout_ms: 5000
```

`GET /api/health` 会返回当前 SQLite `journal_mode`、`busy_timeout_ms` 和外键状态。个人/本机使用优先保持 SQLite；只有公开多人、多个 worker 或高并发写入时，再做 MySQL/PostgreSQL 迁移。

上线前先做一次备份：

```powershell
py scripts\backup_data.py --label before-deploy
```

备份 zip 默认写入 `data/backups/`，包含 SQLite 一致性快照、上传文件和 manifest。`data/`、日志、`.env*` 和下载工具目录不应提交到 Git。

检查和旁路恢复：

```powershell
py scripts\restore_data_backup.py data\backups\mnemosyne-backup-YYYYMMDD-HHMMSS.zip --inspect-only
py scripts\restore_data_backup.py data\backups\mnemosyne-backup-YYYYMMDD-HHMMSS.zip --restore-dir data\restore-drill
```

恢复脚本只接受新的空目录作为 `--restore-dir`，输出结构为 `data\restore-drill\data\app.db` 和 `data\restore-drill\data\uploads`。确认恢复结果后，再人工决定是否替换运行中的 `data/app.db` 与上传目录。

## 5. 外部 Video Companion

实时摄像头视频陪伴在外部项目 `E:\视觉\video-companion` 内独立制作和运行。主项目只负责：

- 显示入口和授权状态。
- 提供人格上下文。
- 接收明确授权后的摘要回写。
- 通过 `/api/video-companion/*` 检查外部服务状态。

不要在主项目部署流程里重做连续摄像头帧理解、麦克风状态机、视觉模型成本路由或视频会话 UI。

## 6. 回滚

如果部署后出现异常：

1. 停止 FastAPI 进程。
2. 保留当前 `logs/app.log` 和 `data/app.db` 副本用于排查。
3. 使用 `restore_data_backup.py` 从最近的 `data/backups/*.zip` 恢复到新的旁路目录，确认数据库完整性和上传文件。
4. 人工切换已确认的 `app.db` 与上传目录。
5. 运行 `py scripts\check_deployment.py --production` 和 `py scripts\verify_all.py` 后再恢复流量。
