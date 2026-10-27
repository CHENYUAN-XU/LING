# LING 维护记录 · 2026-10-27

本轮修复已确认的问题，完整自动回归及本地部署预检通过。代码验证与真实设备验收分别记录。

## 修复内容

- **启动环境**：主项目使用独立 Python 3.12 环境，启动脚本优先查找项目 `.venv` 并验证版本和依赖。显式指定无效解释器会报错。视频集成使用外部项目自己的解释器。补充 Windows 时区数据和测试依赖。
- **本地语音配置**：前端和后端均支持 `local_http`，允许保存 localhost 服务地址；本地模式不要求云端 API key，也不覆盖云端专属设置。所有输入先验证再保存，避免后续字段无效却已写入前面的配置。
- **语音状态**：健康检查验证服务身份、模型加载和声音配置，避免 HTTP 200 被误判为可用；检查超时限制为 3 秒。验收报告明确标出本地服务未启动。
- **记忆同步**：新事实入库后刷新聊天使用的状态和摘要；撤销最后一条事实后归档旧摘要；按准确的 companion 范围更新摘要，避免误覆盖全局摘要。保留流式聊天的后台记忆处理。
- **错误反馈**：模型检测区分 DNS、TLS、连接、超时和认证失败，并在接入面板显示。YAML 错误提供行列位置，避免回显可能包含密钥的原始配置行。
- **回归可靠性**：更新与现有精简提示词、前端资源版本一致的断言；隔离测试与本机 Live2D、聊天开关及语音服务配置；修复 Windows 虚拟环境子进程 PID 判断和退出清理，避免残留服务占用端口或日志。
- **使用文档**：启动、预检、备份和验收命令统一指向项目环境；前端缓存版本已更新。

## 验证结果

在项目根目录执行：

```powershell
& '.\.venv\Scripts\python.exe' scripts\verify_all.py --video-e2e
& '.\.venv\Scripts\python.exe' scripts\check_deployment.py --self-use
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\start_local_server.ps1 -DryRun
git -c core.safecrlf=false diff --check
```

- 完整回归：42 个验证脚本、Python 编译、两项 JavaScript 语法检查和视频桥接端到端验证全部通过。
- 部署预检：12 项通过，0 警告，0 失败。
- 默认启动预检：自动选中主项目 `.venv\Scripts\python.exe`，通过。
- 完整回归日志：`logs/maintenance-verify.log`。
- 测试期间通过临时网络限制仅允许回环连接；模型与语音行为使用测试替身，不代表真实 API 或硬件验收。
- 测试依赖出现 Starlette/httpx 弃用提示，不影响本轮结果。

## 当前实际完成度

只读命令 `scripts/check_acceptance.py` 返回：6 项 ready、4 项 pending、1 项 manual、1 项 optional。SQLite 完整性和外键检查通过。

尚未完成的实机条件：

- 聊天路由已配置，但尚未通过显式连接检测。
- 尚未给 companion 绑定实际 VTube Studio 模型。
- 检查时本地语音服务未运行，真实语音试听和打断时序尚未验收。
- 检查时外部视频服务未就绪；自动桥接测试通过不等同于摄像头、麦克风实测。
- 长时间运行、休眠唤醒及真实设备断线重连仍需日用验收。

本轮未记录任何人工验收凭证。运行日志、虚拟环境和本机数据保留在本地，不随修复代码提交。
