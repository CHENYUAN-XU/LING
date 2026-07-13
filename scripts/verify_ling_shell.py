from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    app_js = read("web/app.js")
    style_css = read("web/style.css")
    index_html = read("web/index.html")
    sw_js = read("web/sw.js")
    icon_svg = read("web/icon.svg")
    server_py = read("app/server.py")
    start_script = read("scripts/start_integrated_video_companion.ps1")
    roadmap = read("docs/LING_ROADMAP.md")

    assert "if (selfUseMode()) return renderSelfUseRail();" in app_js
    assert "function normalizeSelfUseUiState()" in app_js
    assert "normalizeSelfUseUiState();" in app_js
    assert 'state.view === "forge" || state.view === "group" || state.view === "home"' in app_js
    assert "state.groupCreateOpen = false;" in app_js
    assert "if (!selfUseMode() && state.groupCreateOpen) children.push(renderGroupCreateModal());" in app_js
    assert "if (selfUseMode()) {\n    normalizeSelfUseUiState();" in app_js
    assert "return renderSelfUseWorkspace(state.activePersona);" in app_js
    assert "const selfUse = selfUseMode();" in app_js
    assert 'selfUse ? Promise.resolve({ options: {} }) : api("/api/persona-options")' in app_js
    assert 'selfUse ? Promise.resolve({ personas: [] }) : api("/api/personas/deleted")' in app_js
    assert 'selfUse ? Promise.resolve({ group_conversations: [] }) : api("/api/group-conversations?status=active")' in app_js
    assert 'selfUseMode() ? renderVideoCompanionCameraConsentRow() : renderAwarenessConsentRow("camera")' in app_js
    assert 'text: "摄像头采集、预览和连续视觉理解都在外部 Video Companion 中运行。"' in app_js
    assert 'if (s.connecting) return "正在连接 VTube Studio";' in app_js
    assert 'api("/api/live2d/refresh", { method: "POST" })' in app_js
    assert 'text: "刷新 VTS 能力"' in app_js
    assert 'h("h3", { text: "我的资料" })' in app_js
    assert 'selfUse ? null : renderAccountDangerZone()' in app_js
    assert '...(!selfUse ? [' in app_js
    assert 'companionStatusPollTimer = setInterval(pollCompanionStatus, 8000);' in app_js
    assert "function bindCompanionLifecycleRefresh()" in app_js
    assert 'document.addEventListener("visibilitychange", refreshWhenVisible);' in app_js
    assert 'window.addEventListener("pageshow", refreshWhenVisible);' in app_js
    assert 'window.addEventListener("online", refreshWhenVisible);' in app_js
    assert 'window.addEventListener("focus", refreshWhenVisible);' in app_js
    assert "live2d.capabilities_stale" in app_js
    assert "video.recent_summary?.id" in app_js
    assert 'loadCompanionStatus({ preserveOnError: true })' in app_js
    assert 'if (companion.live2d) state.live2dStatus = companion.live2d;' in app_js
    assert 'let avatarValue = selfUseMode() ? persona.avatar_url || "" : avatarUrl.value;' in app_js
    assert 'selfUseMode() ? "Live2D 身体方向" : "期望形象"' in app_js
    assert "function companionRuntimeState()" in app_js
    assert "function renderSelfUseReadinessPanel(persona)" in app_js
    assert "function selfUseApiReadiness()" in app_js
    assert "function renderSelfUseApiGate()" in app_js
    assert "async function setSelfUseChatGate(enabled)" in app_js
    assert 'api("/api/self-use/chat-gate"' in app_js
    assert "state.chatGateSaving" in app_js
    assert "state.chatGateError" in app_js
    assert "state.integrationFlagSaving" in app_js
    assert "state.integrationFlagError" in app_js
    assert "state.integrationConfigSaving" in app_js
    assert "state.integrationConfigFeedback" in app_js
    assert "开启对话" in app_js
    assert "关闭对话" in app_js
    assert "function integrationFlagButtonText(key, enabled)" in app_js
    assert "async function setSelfUseIntegrationFlag(key, enabled)" in app_js
    assert "async function setSelfUseIntegrationConfig(values, statusEl = null, options = {})" in app_js
    assert "function integrationConfigFeedback(key)" in app_js
    assert "function setIntegrationConfigFeedback(key, text, tone = \"\")" in app_js
    assert "function integrationConfigFeedbackKey(values)" in app_js
    assert "function applySelfUseState(data)" in app_js
    assert "function applyCompanionStatus(data)" in app_js
    assert "applySelfUseState(data);" in app_js
    assert "const companion = data?.companion_status || (data?.readiness && data?.chat_gate ? data : null);" in app_js
    assert "async function saveLive2dConfigAndConnect(vtsWsUrl)" in app_js
    assert "async function saveVideoCompanionConfigAndCheck(values)" in app_js
    assert "保存并连接" in app_js
    assert "保存并重连" in app_js
    assert "保存并检测" in app_js
    assert "已保存；外部服务已连接" in app_js
    assert 'api("/api/self-use/integration-flag"' in app_js
    assert 'api("/api/self-use/integration-config"' in app_js
    assert '"live2d.vts_ws_url"' in app_js
    assert '"live2d.idle_expression"' in app_js
    assert '"live2d.listening_expression"' in app_js
    assert '"live2d.thinking_expression"' in app_js
    assert '"live2d.speaking_expression"' in app_js
    assert '"live2d.lip_sync_enabled"' in app_js
    assert '"live2d.lip_sync_parameter"' in app_js
    assert '"live2d.lip_sync_gain"' in app_js
    assert "function live2dLipSyncReady()" in app_js
    assert "async function startLive2dLipSync(audio, playback)" in app_js
    assert 'api("/api/live2d/lip-sync"' in app_js
    assert "createMediaElementSource(audio)" in app_js
    assert "getByteTimeDomainData(samples)" in app_js
    assert "consecutiveFailures >= 3" in app_js
    assert "await sendLive2dLipSyncValue(0);" in app_js
    assert '@app.post("/api/live2d/lip-sync")' in server_py
    assert "async function setPresenceQuietMode(quiet)" in app_js
    assert '"/api/presence/quiet-mode"' in app_js
    assert '"/api/presence/normal-mode"' in app_js
    assert "presenceRuntime().quiet_mode ? \"恢复在场\" : \"安静模式\"" in app_js
    assert "保存动作" in app_js
    assert "保存嘴型" in app_js
    assert '"video_companion.base_url"' in app_js
    assert '"video_companion.ws_url"' in app_js
    assert '"video_companion.project_path"' in app_js
    assert 'setSelfUseIntegrationFlag("live2d", true)' in app_js
    assert 'setSelfUseIntegrationFlag("video_companion", true)' in app_js
    assert 'setSelfUseIntegrationFlag(key, !configEnabled)' in app_js
    assert 'key === "screen" || key === "proactive"' in app_js
    assert 'status?.config_enabled ?? status?.config?.enabled' in app_js
    assert 'enabled ? "关闭屏幕感知" : "启用屏幕感知"' in app_js
    assert 'enabled ? "关闭主动能力" : "启用主动能力"' in app_js
    assert "function renderSelfUseIntegrationModal()" in app_js
    assert "function renderSelfUseApiSetupCard()" in app_js
    assert "function renderSelfUseLive2dSetupCard()" in app_js
    assert "function renderSelfUseVoiceSetupCard()" in app_js
    assert "编辑声音绑定" in app_js
    assert "function renderSelfUseVideoSetupCard()" in app_js
    assert "self-use-integration-modal" in app_js
    assert "self-use-integration-card" in app_js
    assert "state.integrationOpen = true;" in app_js
    assert "state.companionStatus?.chat_gate" in app_js
    assert "apiState.canEnable" in app_js
    assert "function chatGateReasonText(reason)" in app_js
    assert '["状态原因", chatGateReasonText(apiState.reason)]' in app_js
    assert '["可手动开启", apiState.canEnable ? "可以" : "暂不可以"]' in app_js
    assert '"base_url": base_url' in read("app/llm_client.py")
    assert '"chat_gate": chat_gate' in server_py
    assert '"companion_status": companion_status(user)' in server_py
    assert "visual_ready = bool(embodiment.get(\"visual_ready\"))" in server_py
    assert '"key": "visual"' in server_py
    assert "def _companion_visual_readiness_text" in server_py
    assert '@app.post("/api/self-use/chat-gate")' in server_py
    assert '@app.post("/api/self-use/llm-probe")' in server_py
    assert '@app.post("/api/self-use/integration-flag")' in server_py
    assert '@app.post("/api/self-use/integration-config")' in server_py
    assert "set_self_use_chat_enabled(bool(req.enabled))" in server_py
    assert "set_config_section_bool(section, config_key, bool(req.enabled))" in server_py
    assert "set_config_section_value(section, config_key, value)" in server_py
    assert "def _validate_live2d_action_name" in server_py
    assert '"live2d.idle_expression": ("live2d", "idle_expression", _validate_live2d_action_name)' in server_py
    assert '"voice": ("voice", "enabled")' in server_py
    assert '"voice.tts_provider": ("voice", "tts_provider", _validate_voice_provider)' in server_py
    assert "def _validate_env_name" in server_py
    assert '"voice.tts_provider": providerInput.value' in app_js
    assert 'value: "elevenlabs"' not in app_js
    assert "function live2dAvailableActions()" in app_js
    assert "if (status.capabilities_stale === true) return [];" in app_js
    assert "function live2dBindingMatchesCurrent" in app_js
    assert "if (state.live2dStatus?.capabilities_stale === true) return false;" in app_js
    assert "function enqueueLive2dAction" in app_js
    assert "function scheduleLive2dExpressionReset" in app_js
    assert 'await applyLive2dRuntimeState("thinking")' in app_js
    assert 'await applyLive2dRuntimeState("speaking")' in app_js
    assert "function voiceAutoPlayEnabled" in app_js
    assert "function formatMessagePerformance(metrics)" in app_js
    assert "X-LING-TTS-Generation-Ms" in app_js
    assert "X-LING-TTS-Generation-Ms" in server_py
    assert "function incrementalLocalVoiceEnabled(plan)" in app_js
    assert "function playIncrementalLocalVoice" in app_js
    assert 'fetch(`/api/voice/tts-chunk/${chunkIndex}`' in app_js
    assert "function probeSelfUseLlm" in app_js
    assert "llm_unverified" in app_js
    assert "澪的状态档案" in app_js
    assert "告诉澪你的边界或节奏" in app_js
    assert "不需要先给澪套关系或人格模板" in app_js
    assert "以后你就是我的女朋友" not in app_js
    assert "function interruptVoicePlayback" in app_js
    assert "function voicePlaybackIsCurrent(playback)" in app_js
    assert "signal: playback.controller.signal" in app_js
    assert '"voice.auto_play": autoPlayInput.checked' in app_js
    assert "persona_id: state.activePersona?.id || null" in app_js
    assert "def _voice_profile_for_request" in server_py
    assert 'text: "绑定到澪"' in app_js
    assert '"Provider voice ID", fields.voiceProfile' in app_js
    assert '[h("option", { value: "mp3", text: "mp3" })]' in app_js
    assert "def _voice_media_type" in server_py
    assert "available_expressions" in app_js
    assert "available_hotkeys" in app_js
    assert 'text: "Save voice"' in app_js
    assert "def _companion_chat_gate" in server_py
    assert "renderSelfUseApiGate()" in app_js
    assert "self-use-api-gate" in app_js
    assert "保持关闭，避免未接 API 时误触发模型调用" in app_js
    assert "function videoCompanionRecentObservation()" in app_js
    assert "recent_observation" in app_js
    assert "function videoCompanionActivityText(item, emptyText = \"none\")" in app_js
    assert '"Summary writeback"' in app_js
    assert '"Consent sync"' in app_js
    assert '["Observation", recent.text]' in app_js
    assert "function videoCompanionPathState(config)" in app_js
    assert "config.project_path_exists === false" in app_js
    assert "state.companionStatus?.live2d_actions" in app_js
    assert "function renderSelfUseActionControls()" in app_js
    assert "renderSelfUseActionControls()" in app_js
    assert "function renderSelfUseCompanionDock" not in app_js
    assert "function renderSelfUseVideoCompanionControl" not in app_js
    assert '!selfUseMode() && !isUser && !isNotice ? avatar(' in app_js
    assert '!selfUseMode() && isUser ? avatar(' in app_js
    assert "function live2dConnected()" in app_js
    assert "const canTrigger = configured && connected;" in app_js
    assert "live2dActionDisabledReason()" in app_js
    assert "live2dRuntimeResultText(result, runtimeState)" in app_js
    assert 'trigger("idle")' in app_js
    assert 'trigger("thinking")' in app_js
    assert 'trigger("speaking")' in app_js
    assert "actions.idle_expression" in app_js
    assert "actions.thinking_expression" in app_js
    assert "actions.speaking_expression" in app_js
    assert "function renderSelfUseEmbodimentEditor(persona, fields)" in app_js
    assert "renderSelfUseEmbodimentEditor(persona" in app_js
    assert "function renderSelfUseEmbodimentImageUpload(label, kind, urlField, statusEl)" in app_js
    assert 'uploadImageFile(`/api/uploads/embodiment-image?kind=${encodeURIComponent(kind)}`, file)' in app_js
    assert 'h("span", { class: "ghost compact upload-label", text: `上传${label}` })' in app_js
    assert '@app.post("/api/uploads/embodiment-image")' in server_py
    assert 'EMBODIMENT_IMAGE_KINDS = {"preview", "fallback"}' in server_py
    assert "function live2dCurrentModelBinding()" in app_js
    assert "function renderSelfUseLive2dModelPicker(live2dModelIdField, statusEl = null)" in app_js
    assert "renderSelfUseLive2dModelPicker(fields.live2dModelId, bindingStatus)" in app_js
    assert '["live2d_preview_url", live2dPreviewUrl, "Live2D preview", "preview"]' in app_js
    assert '["fallback_image_url", fallbackImageUrl, "Fallback image", "fallback"]' in app_js
    assert '["avatar_url", avatarUrl, "Legacy fallback", "legacy"]' in app_js
    assert "function renderCompanionVisual(persona, embodiment)" in app_js
    assert "state.companionStatus?.embodiment" in app_js
    assert "companion-visual-empty" in app_js
    assert "companion-visual-source" in app_js
    assert "live2dCurrentModelBinding()" in app_js
    assert "Body pending" in app_js
    assert "Bind body" in app_js
    assert ".companion-visual.missing" in style_css
    assert "Live2D pending" in app_js
    assert "使用并保存当前模型" in app_js
    assert "保存形象绑定" in app_js
    assert "async function saveSelfUseEmbodimentBinding(payload, statusEl = null)" in app_js
    assert "function applyUpdatedPersona(persona)" in app_js
    assert "applyUpdatedPersona(data.persona)" in app_js
    assert "state.live2dStatus?.current_model" in app_js
    assert "available_model_count" in app_js
    assert "function renderSelfUseMappingPreview()" in app_js
    assert "Live2D 状态映射" in app_js
    assert "actions.listening_expression" in app_js
    assert "self-use-mapping-preview" in app_js
    assert "Embodiment binding" in app_js
    assert "...(!selfUseMode() ? [" in app_js
    assert "async function loadCompanionStatus(options = {})" in app_js
    assert 'const local = await api("/api/auth/local", { method: "POST" });' in app_js
    assert "function renderLocalStartupError(err)" in app_js
    assert "localSelfUseUnavailable(localErr)" in app_js
    assert "self-use-startup-screen" in app_js
    assert "LING local workspace" in app_js
    assert "不会出现登录、注册或游客入口" in app_js
    assert "async function refreshEmbodimentRuntimeStatus()" in app_js
    assert "await refreshEmbodimentRuntimeStatus();" in app_js
    assert "loadVoiceConfig()" in app_js
    assert "loadLive2dStatus()" in app_js
    assert "loadAwarenessStatus()" in app_js
    assert "/api/companion/status" in app_js
    assert '"live2d_actions": live2d_actions' in server_py
    assert 'FastAPI(title="LING")' in server_py
    assert "state.companionStatus?.readiness?.length" in app_js
    assert "function readinessActionFor(item)" in app_js
    assert "核心就绪" in app_js
    assert "item.required === false" in app_js
    assert "function renderSelfUseReadinessItem(item)" in app_js
    assert "function openSelfUseIntegration()" in app_js
    assert "renderSelfUseReadinessItem(item)" in app_js
    assert "state.companionStatus?.runtime" in app_js
    assert "async function openPersonaEditor()" in app_js
    assert "class: `companion-visual ${embodiment.visualTone}`" in app_js
    assert '"aria-label": "编辑形象"' in app_js
    assert "event.stopPropagation();" in app_js
    assert "openPersonaEditor();" in app_js
    assert "function renderCompanionStageActions({ live2dEnabled, live2dConnected })" in app_js
    assert "self-use-stage-actions" in app_js
    assert "onclick: () => setSelfUseChatGate(false)" in app_js
    assert "onclick: () => setSelfUseChatGate(true)" in app_js
    assert "onclick: () => startVideoCompanion(statusEl)" in app_js
    assert "onclick: openVideoCompanionPage" in app_js
    assert "async function openEasyVtuber()" in app_js
    assert 'api("/api/easyvtuber/open", { method: "POST" })' in app_js
    assert '@app.post("/api/easyvtuber/open")' in server_py
    assert "def easyvtuber_open" in server_py
    assert 'text: "编辑形象", onclick: openPersonaEditor' in app_js
    assert "video.status?.session_active" in app_js
    assert "state.sending" in app_js
    assert "state.voicePlaying" in app_js
    assert 'state.voicePlaybackPhase = "preparing"' in app_js
    assert 'state.voicePlaybackPhase = "playing"' in app_js
    assert 'await applyLive2dRuntimeState("thinking")' in app_js
    assert "state.voicePlan" in app_js
    assert "state.voicePlanMessageId" in app_js
    assert "let voicePlaybackCompleted = false;" in app_js
    assert "voicePlaybackCompleted = !playback.interrupted;" in app_js
    assert "composerFocused" in app_js
    assert "composerDraft" in app_js
    assert "if (selfUseMode()) state.composerDraft = input.value.trim();" in app_js
    assert "state.composerFocused = true;" in app_js
    assert "state.composerFocused = false;" in app_js
    assert "if (state.composerFocused && !chatInputBlocked())" in app_js
    assert 'key: "listening"' in app_js
    assert "function runtimeToLive2dState(runtime)" in app_js
    assert "function voicePlaybackDetail()" in app_js
    assert "function messageExpressionLabels(message)" in app_js
    assert "async function loadVoiceSpeechPlan(text, expressionLabels, messageId, playback = null)" in app_js
    assert "await loadVoiceSpeechPlan(text, expressionLabels, messageId, playback);" in app_js
    assert app_js.count("if (!voicePlaybackIsCurrent(playback)) return;") >= 5
    assert 'api("/api/voice/speech-plan"' in app_js
    assert "async function syncCompanionRuntime(options = {})" in app_js
    assert "refreshRuntimeIndicators()" in app_js
    assert "await syncCompanionRuntime({ applyLive2d: true });" in app_js
    assert "await syncCompanionRuntime({ reload: true, applyLive2d: true });" in app_js
    assert "await applyLive2dRuntimeState(runtimeToLive2dState(runtime));" in app_js
    assert ".self-use-stage-panel {\n  display: grid;\n  grid-template-rows: minmax(0, 1fr);" in style_css
    assert "@media (max-width: 620px)" in style_css
    assert "grid-template-rows: minmax(540px, 68vh) minmax(0, 1fr);" in style_css
    assert "chatInputBlocked()" in app_js
    assert "function applyMessageExpressionsToLive2d(expressions)" in app_js
    assert '"/api/live2d/apply-expression"' in app_js
    assert "appliedReplyExpression = await applyMessageExpressionsToLive2d(data.expressions || [])" in app_js
    assert "await syncCompanionRuntime({ applyLive2d: !appliedReplyExpression });" in app_js
    assert "return !!result.applied;" in app_js
    assert "function applyLive2dRuntimeState(runtimeState, options = {})" in app_js
    assert '"/api/live2d/apply-runtime-state"' in app_js
    assert 'applyLive2dRuntimeState("speaking")' in app_js
    assert 'applyLive2dRuntimeState("idle")' in app_js
    assert 'await syncCompanionRuntime({ applyLive2d: false });' in app_js
    assert 'applyLive2dRuntimeState("thinking")' in app_js
    assert 'trigger("listening")' in app_js
    assert "actions.listening_expression" in app_js
    assert "state.voiceConfig.enabled && state.voiceConfig.available" in app_js
    assert '"available": bool(health.get("available"))' in server_py
    assert '"voice": voice_health' in server_py
    assert "Live2D" in app_js and "Voice" in app_js and "Video" in app_js

    assert ".self-use-shell" in style_css
    assert ".companion-rail" in style_css
    assert ".self-use-integration-modal" in style_css
    assert ".self-use-integration-grid" in style_css
    assert ".self-use-integration-card" in style_css
    assert ".self-use-integration-actions .save-status" in style_css
    assert ".self-use-integration-field" in style_css
    assert ".self-use-integration-field-grid" in style_css
    assert ".self-use-integration-row" in style_css
    assert ".self-use-workspace" in style_css
    assert ".self-use-api-gate" in style_css
    assert ".self-use-api-dot" in style_css
    assert ".companion-runtime-badge" in style_css
    assert ".companion-visual:hover" in style_css
    assert ".companion-visual:focus-visible" in style_css
    assert ".companion-visual-source" in style_css
    assert ".companion-visual-empty" in style_css
    assert ".companion-visual.legacy" in style_css
    assert ".self-use-stage-actions" in style_css
    assert ".companion-stage-action-status" in style_css
    assert ".companion-runtime-badge.listening" in style_css
    assert ".self-use-readiness" in style_css
    assert ".self-use-readiness-copy" in style_css
    assert ".self-use-readiness-item button" in style_css
    assert ".self-use-action-control" in style_css
    assert ".self-use-action-buttons" in style_css
    assert ".self-use-embodiment-editor" in style_css
    assert ".self-use-embodiment-grid" in style_css
    assert ".self-use-embodiment-actions" in style_css
    assert ".self-use-live2d-model-picker" in style_css
    assert ".self-use-embodiment-preview-visual" in style_css
    assert ".self-use-mapping-preview" in style_css
    assert ".self-use-runtime-map" in style_css
    assert ".self-use-expression-map" in style_css
    assert ".local-startup-card" in style_css
    assert ".local-startup-detail" in style_css
    assert "@media (max-width: 1024px)" in style_css

    versions = set(re.findall(r"[?&]v=([0-9a-zA-Z-]+)", index_html + sw_js))
    assert len(versions) == 1, f"expected one PWA asset version, found {versions}"
    cache_match = re.search(r'CACHE_NAME = "([^"]+)"', sw_js)
    assert cache_match, "service worker cache name missing"
    assert "ling-shell-" in cache_match.group(1)
    assert 'aria-label="LING"' in icon_svg
    assert "Starting managed LING" in start_script
    assert "LING PID" in start_script
    assert 'start_local_server.ps1' in start_script
    assert '.venv\\Scripts\\python.exe' in start_script
    assert 'Stop the existing LING process first' in start_script
    assert 'Close the visible Video Companion terminal' in start_script

    assert "personal AI VTB" in roadmap
    assert "embodied workspace" in roadmap
    assert "Video Companion is external" in roadmap
    assert "integration panel" in roadmap
    assert "legacy avatar fallback" in roadmap
    assert "Visual readiness" in roadmap
    assert "old Project Mnemosyne UI paths no longer dominate" in roadmap

    print("LING self-use shell verification passed")


if __name__ == "__main__":
    main()
