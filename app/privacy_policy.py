from __future__ import annotations


PRIVACY_POLICY = {
    "version": "2026-06-14",
    "title": "数据与隐私",
    "summary": "LING 默认在本机保存自用 companion 资料、会话、记忆和授权状态；真实设备能力默认关闭，必须由用户显式授权。",
    "data_categories": [
        {
            "name": "账号与资料",
            "detail": "保存本地账号名、昵称、可选图片链接或上传图片、生日、性别、签名和简介。密码只保存哈希，不在导出中返回。",
        },
        {
            "name": "会话与 companion",
            "detail": "保存澪的 companion 资料、会话、消息、未读状态、表达标签和成长记录，用于恢复上下文、记忆和后续调整；旧人格/群聊表仅作为兼容层保留。",
        },
        {
            "name": "记忆与画像",
            "detail": "保存摘要、事实、关系、偏好、冲突审计和召回痕迹，用于让回复遵守用户已经表达过的喜好与边界。",
        },
        {
            "name": "设备感知授权",
            "detail": "Voice、Live2D、Camera、Screen、Proactive 和 Video Companion 均默认关闭；开启后仍按用户授权状态决定是否执行。",
        },
        {
            "name": "运行日志",
            "detail": "请求日志只记录 request id、路径、状态码、耗时、客户端标识和 5xx 异常类型，不记录请求正文。",
        },
    ],
    "retention": [
        "正式账号数据保留到用户主动删除账号、清理 companion 数据或执行维护清理为止。",
        "游客账号默认 3 天后自动删除账号、会话、记忆和上传目录。",
        "旧兼容对象若被软删除，可在维护入口恢复；永久删除需要再次输入名称确认。",
        "本地备份 zip 由维护者手动生成和保管，用户导出 JSON 不包含 password hash 和 session token。",
    ],
    "user_controls": [
        "资料弹窗可导出当前账号数据、转正游客账号、撤销感知授权和彻底删除账号。",
        "账号彻底删除会级联数据库记录并清理 data/uploads/<user_id>。",
        "Camera/Screen/Proactive/Video Companion 授权可撤销；未授权时入口只显示状态，不执行采集。",
        "Video Companion 是外部独立项目，位于 E:\\视觉\\video-companion；主项目只接收摘要、状态和明确授权后的回写。",
    ],
    "external_boundaries": [
        "主项目不保存连续摄像头视频帧，也不在主项目内实现实时视频理解引擎。",
        "Video Companion 可独立使用摄像头、麦克风、视觉模型和语音会话；成本、token 调度和实时媒体处理由外部项目负责。",
        "主项目与外部服务通过本机 API 桥接，默认开发端口为 8782，并使用桥接密钥保护回写接口。",
    ],
}


def get_privacy_policy() -> dict:
    return dict(PRIVACY_POLICY)
