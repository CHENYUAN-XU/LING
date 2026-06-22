# LING 接力计划

更新日期：2026-06-20

这份文件是当前仓库的最高优先级产品接力说明。新一轮开发先读本文件，再读 `README.md`、`docs/DEPLOYMENT_RUNBOOK.md` 与两份 Video Companion 边界文档。历史 Project Mnemosyne 代码和旧阶段名不能覆盖这里的产品定义。

## 产品契约

LING 是作者本人使用的 AI VTB / 具身数字陪伴体。澪是唯一产品主体。

- 第一屏必须先看到澪的形象、在场状态和围绕形象组织的交互。
- Live2D / VTube Studio 是主要身体；静态图只作 preview 或 fallback。
- 文本、普通回复朗读、表情动作、presence 和外部 Video Companion 汇入同一状态层。
- 记忆、成长和会话记录属于底层连续性能力，不是首页信息架构。
- 默认资料保持空白。只有作者填写、绑定或真实相处形成的内容才进入澪的资料。
- 用户知道系统由 AI 驱动，但澪的回答不得把自己讲成模型、机器人、程序或 prompt 执行器。

## 明确不做

- 不把 LING 扩张成多人格列表、群聊成员管理或头像生成产品。
- 不为本地自用流程重新加入登录、注册、游客或人格生成向导。
- 不在主仓库重做实时摄像头、连续视觉理解、麦克风/ASR、视频会话 TTS 状态机或视频会话 UI。
- 不使用 Edge TTS 作为 LING 的语音方向。
- 不把最小可验证闭环写成完整生产级完成。

旧账号、人格、群聊、头像和内部 camera 代码只可作为关闭 `self_use` 后的兼容/调试地基维护。它们不得驱动自用首页，也不得成为新功能的默认入口。

## 仓库边界

主仓库：

```text
E:\澪\project-mnemosyne
```

GitHub 目标：

```text
https://github.com/thefoolsparkle-oss/LING
```

外部 Video Companion：

```text
E:\视觉\video-companion
```

主仓库只负责 Video Companion 的授权、上下文、启动/停止代理、状态反映、观察和摘要回写。`docs/VIDEO_COMPANION_PROJECT_PLAN.md` 是边界声明，必须保留。

## 当前已证实状态

### 自用主体

- 本地启动优先走 `/api/auth/local`，正常路径不显示登录页。
- 自用模式下旧注册、密码登录、游客和游客转账号 API 返回 404；这些入口只在关闭自用模式的兼容部署中开放。
- 自用模式只返回绑定的唯一 companion；人格创建、删除、恢复、群聊和非绑定人格访问被阻止或隐藏。
- 唯一 companion 使用 SQLite 稳定 ID 绑定，改名或保留旧人格数据不会把首页切回旧对象。
- 系统生成的澪摘要、关系、说话方式和形象占位设定已清空。

### 具身首页

- 第一屏为 stage-first workspace，形象区在桌面和窄屏都保持可检查尺寸。
- 对话是围绕身体的 session 面板；历史、资料、管理和接入是次级入口。
- 消息记录在自用模式不再重复联系人头像。
- `live2d_model_id`、`live2d_preview_url`、`fallback_image_url`、`voice_profile` 已进入资料、接口和状态汇总。

### 模型闸门

- `self_use.chat_enabled` 默认关闭。
- API key 存在只表示 configured，不表示 ready。
- 作者必须从本地显式执行路由检测；检测只访问模型目录，不生成文本。
- 成功检测按路由和密钥指纹缓存七天，不保存密钥；模型、地址或密钥变化后重新检测。
- 未验证路由无法打开聊天闸门，`/api/chat` 也会再次拒绝。

### Live2D

- VTube Studio WebSocket 在持久后台事件循环中运行，请求/响应串行化。
- token、当前模型、可用模型、expression 和 hotkey 能力可发现。
- 就绪要求已启用、已连接、已授权、当前模型与澪绑定一致。
- 运行状态映射覆盖 idle、listening、thinking 和 speaking。
- 回复音频通过 Web Audio 分析后向 VTube Studio 的真实 `MouthOpen`（可配置）输入参数注入嘴型值；连续失败会停止采样，结束或打断会归零。
- expression 与 hotkey 按真实 VTS 能力解析；没有 expression 列表时不会臆造文件名覆盖真实 hotkey。
- 启用后应用启动会非阻塞自动连接；关闭应用时释放连接与事件循环。

### 语音与动作

- 主项目普通文字回复使用 OpenAI TTS 适配器；语音默认关闭。
- `voice_profile` 作为真实 provider voice ID 使用，空值回退到 provider 默认 voice。
- 回复播放区分 preparing 与 playing；音频真正开始播放后才进入 Talk 动作。
- 新输入可中断生成中或播放中的语音，结束后回到 idle。
- 实时麦克风、ASR 和视频会话语音仍属于外部 Video Companion。

### Presence

- 本地 Presence 默认启用，不依赖聊天模型、语音或摄像头；idle、thinking、speaking 和 quiet 按用户隔离。
- 第一屏可直接进入“安静模式”或“恢复在场”；quiet 下的 idle 检查不会破坏状态或触发 idle actions。
- quiet 与 proactive 的持久禁止状态双向同步；重启后 Presence 会从 SQLite 恢复，文字中的“别打扰我”也会持久阻止主动消息。
- LLM 回复失败会收尾到 idle/quiet，不会让后端永久停在 speaking。
- Presence 启用不等于主动消息启用；`proactive.enabled` 与 scheduler 仍单独关闭并受授权控制。

### Video Companion

- 外部服务路径、HTTP/WS 地址和启用状态可在本地接入面板配置。
- 主界面可检查外部服务、启动/停止外部会话并反映 session 状态。
- 授权后的观察与摘要写回 `world_observations` 并进入 companion 状态。
- 自用模式拒绝主仓库旧 `/api/camera/config`、`status` 和 MJPEG `stream`；资料页摄像头授权只服务外部 Video Companion。

### 屏幕感知与主动能力

- 屏幕感知保留在主仓库的最小边界：作者必须分别启用配置和授予授权，默认只允许一次性检查活动窗口标题；截图路径只记录尺寸/模式元数据，不保留像素。
- 自用资料页可显式启停 screen/proactive 配置，但 camera 不在内部配置开关允许列表。
- 主动能力将“配置启用”“用户授权”“最终 active”分开报告；启用能力不会自动开启 scheduler。
- 自用 proactive status、tick、反馈和 quiet 操作全部锁定到 SQLite 稳定绑定的唯一 companion，同账号旧人格不能被选中。
- 后台 scheduler 的候选 SQL 同样只联结自用 owner 的 `self_use_companion_bindings`，不会绕过 HTTP 边界扫描旧人格。

### 工程地基

- SQLite 使用 WAL、busy timeout 和 foreign keys。
- 备份支持创建、检查和旁路恢复演练。
- PWA shell 不缓存 `/api`、`/uploads` 或 `/admin`。
- Windows 日用入口使用受管 local runner：自动 Python 探测、自用预检、LING health/端口归属检查、PID state、UTF-8 日志和 stop-request 正常关闭。
- 部署预检覆盖密钥环境变量、明文密钥、限流、日志、cookie、目录写权限、外部视频路径和主动调度风险。
- `scripts/check_acceptance.py` 只读汇总单 companion 绑定、LING prompt、SQLite、聊天模型、Live2D、语音、外部 Video、备份和长时间真机门槛；它不会调用付费模型 API。
- `scripts/record_acceptance.py` 只在作者完成真实测试后显式写入本地验收凭证；凭证按当前配置证据生成指纹，配置变化会自动失效。
- 管理台保留错误事件和历史系统调试能力，但不是 LING 第一界面。

## 尚未完成的真实门槛

脚本全绿不能证明以下事项已经完成：

1. 使用作者实际的 VTube Studio 模型完成绑定、授权、重启自动连接和连续动作日用测试。
2. 作者明确选择并检测真实聊天模型后，完成一次真实文本往返与记忆连续性观察。
3. 作者明确启用语音并绑定实际 voice ID 后，验证真实 TTS 音频、打断和 Live2D Talk/Idle 联动。
4. 外部 Video Companion 实际运行时，验证授权、会话状态、观察和摘要回写在真实设备链路上成立。
5. 对长期运行做更长时间的断线、重连、休眠唤醒和 SQLite 并发观察。

直播能力是 AI VTB 项目的后续能力，但当前优先级低于作者本人日常陪伴体验。它不能阻塞核心自用闭环，也不能反过来把首页做成直播控制台。

## 继续顺序

在不需要作者提供模型、密钥或硬件的部分，按以下顺序持续推进：

1. 清除仍能从自用模式进入的旧人格、群聊、头像优先或内部视频路径。
2. 加固 Live2D 自动连接、断线恢复、模型切换、动作失败回退和状态一致性。
3. 加固语音播放、打断、错误回退与动作时序。
4. 完善外部 Video Companion 的状态、授权和回写观测，不进入其摄像头/麦克风实现。
5. 加固屏幕感知与主动能力的显式配置、独立授权、唯一 companion 和 scheduler 安全边界。
6. 做桌面、窄屏、PWA、长时间运行和部署验证。
7. 只有在真实外部依赖已由作者明确配置后，执行对应真机验收。

## 运行与验证

开发启动：

```powershell
cd "E:\澪\project-mnemosyne"
py -m uvicorn app.server:app --host 127.0.0.1 --port 8001
```

页面：

```text
LING:  http://127.0.0.1:8001
调试:  http://127.0.0.1:8001/admin
```

每轮代码改动必须运行：

```powershell
py scripts\verify_all.py --video-e2e
git diff --check
```

当前机器若 `py` 找不到已安装解释器，必须使用真实 Python 可执行文件运行验证，不能让后一个成功命令掩盖前一个未执行。

## Git 约定

- 不擅自 commit、push 或上传。
- 只有作者当前明确要求提交或上传时才执行 Git 发布动作。
- `data/`、日志、上传文件、备份、token、`.env*` 和真实 API key 不进入 Git。
- `config.yaml` 只保存路由、功能开关和环境变量名，不保存密钥值。
- 工作树可能包含作者或前序开发的未提交修改；不得回滚不属于当前任务的改动。

## 关键文件

- `docs/LING_ROADMAP.md`：已落地保护和“尚未完成”定义。
- `app/server.py`：自用 API、状态汇总、兼容边界。
- `app/live2d.py`、`app/embodiment.py`：VTube Studio 连接与动作状态。
- `app/voice.py`、`app/tts_service.py`：普通回复语音。
- `app/video_companion.py`、`app/video_bridge.py`：外部 Video Companion 适配。
- `web/app.js`、`web/style.css`：具身 workspace。
- `scripts/verify_all.py`：总验证入口。
