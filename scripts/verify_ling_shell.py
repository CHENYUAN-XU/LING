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
    assert "if (selfUseMode()) {\n    normalizeSelfUseUiState();" in app_js
    assert "return renderSelfUseWorkspace(state.activePersona);" in app_js
    assert "const selfUse = selfUseMode();" in app_js
    assert 'selfUse ? Promise.resolve({ options: {} }) : api("/api/persona-options")' in app_js
    assert 'selfUse ? Promise.resolve({ personas: [] }) : api("/api/personas/deleted")' in app_js
    assert 'selfUse ? Promise.resolve({ group_conversations: [] }) : api("/api/group-conversations?status=active")' in app_js
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
    assert "function applyCompanionStatus(data)" in app_js
    assert "async function saveLive2dConfigAndConnect(vtsWsUrl)" in app_js
    assert "async function saveVideoCompanionConfigAndCheck(values)" in app_js
    assert "保存并连接" in app_js
    assert "保存并重连" in app_js
    assert "保存并检测" in app_js
    assert "已保存；外部服务已连接" in app_js
    assert 'api("/api/self-use/integration-flag"' in app_js
    assert 'api("/api/self-use/integration-config"' in app_js
    assert '"live2d.vts_ws_url"' in app_js
    assert '"video_companion.base_url"' in app_js
    assert '"video_companion.ws_url"' in app_js
    assert '"video_companion.project_path"' in app_js
    assert 'setSelfUseIntegrationFlag("live2d", true)' in app_js
    assert 'setSelfUseIntegrationFlag("video_companion", true)' in app_js
    assert "function renderSelfUseIntegrationModal()" in app_js
    assert "function renderSelfUseApiSetupCard()" in app_js
    assert "function renderSelfUseLive2dSetupCard()" in app_js
    assert "function renderSelfUseVoiceSetupCard()" in app_js
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
    assert '@app.post("/api/self-use/chat-gate")' in server_py
    assert '@app.post("/api/self-use/integration-flag")' in server_py
    assert '@app.post("/api/self-use/integration-config")' in server_py
    assert "set_self_use_chat_enabled(bool(req.enabled))" in server_py
    assert "set_config_section_bool(section, config_key, bool(req.enabled))" in server_py
    assert "set_config_section_value(section, config_key, value)" in server_py
    assert "def _companion_chat_gate" in server_py
    assert "renderSelfUseApiGate()" in app_js
    assert "self-use-api-gate" in app_js
    assert "保持关闭，避免未接 API 时误触发模型调用" in app_js
    assert "function renderSelfUseVideoCompanionControl()" in app_js
    assert "renderSelfUseVideoCompanionControl()" in app_js
    assert "function videoCompanionRecentObservation()" in app_js
    assert "recent_observation" in app_js
    assert "最近回写" in app_js
    assert "function renderVideoCompanionPresenceGrid(status, stateInfo, pathState)" in app_js
    assert "self-use-video-presence-grid" in app_js
    assert "self-use-video-presence-item" in app_js
    assert "Presence channel" in app_js
    assert "function videoCompanionPathState(config)" in app_js
    assert "config.project_path_exists === false" in app_js
    assert "self-use-video-path" in app_js
    assert "self-use-video-recent" in app_js
    assert "function companionActionSummary()" in app_js
    assert "function companionVoiceSummary(embodiment)" in app_js
    assert '["Voice", companionVoiceSummary(embodiment)]' in app_js
    assert "state.companionStatus?.live2d_actions" in app_js
    assert '["Actions", companionActionSummary()]' in app_js
    assert "function renderSelfUseActionControls()" in app_js
    assert "renderSelfUseActionControls()" in app_js
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
    assert "function live2dCurrentModelBinding()" in app_js
    assert "function renderSelfUseLive2dModelPicker(live2dModelIdField, statusEl = null)" in app_js
    assert "renderSelfUseLive2dModelPicker(fields.live2dModelId, bindingStatus)" in app_js
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
    assert "async function loadCompanionStatus()" in app_js
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
    assert "state.companionStatus?.runtime" in app_js
    assert "async function openPersonaEditor()" in app_js
    assert 'class: "companion-visual"' in app_js
    assert '"aria-label": "编辑形象"' in app_js
    assert "event.stopPropagation();" in app_js
    assert "openPersonaEditor();" in app_js
    assert "function renderCompanionStageActions({ live2dEnabled, live2dConnected })" in app_js
    assert "self-use-stage-actions" in app_js
    assert "onclick: () => setSelfUseChatGate(false)" in app_js
    assert "onclick: () => setSelfUseChatGate(true)" in app_js
    assert "onclick: () => startVideoCompanion(statusEl)" in app_js
    assert "onclick: openVideoCompanionPage" in app_js
    assert 'text: "补形象资料", onclick: openPersonaEditor' in app_js
    assert 'text: "编辑形象", onclick: openPersonaEditor' in app_js
    assert "video.status?.session_active" in app_js
    assert "state.sending" in app_js
    assert "state.voicePlaying" in app_js
    assert "state.voicePlan" in app_js
    assert "state.voicePlanMessageId" in app_js
    assert "composerFocused" in app_js
    assert "composerDraft" in app_js
    assert "if (selfUseMode()) state.composerDraft = input.value.trim();" in app_js
    assert "state.composerFocused = true;" in app_js
    assert "state.composerFocused = false;" in app_js
    assert "if (state.composerFocused && !chatInputBlocked())" in app_js
    assert 'key: "listening"' in app_js
    assert "function runtimeToLive2dState(runtime)" in app_js
    assert "function voicePlaybackDetail()" in app_js
    assert "function companionSpeechSummary()" in app_js
    assert "function messageExpressionLabels(message)" in app_js
    assert "async function loadVoiceSpeechPlan(text, expressionLabels, messageId)" in app_js
    assert 'api("/api/voice/speech-plan"' in app_js
    assert '["Speech", companionSpeechSummary()]' in app_js
    assert "async function syncCompanionRuntime(options = {})" in app_js
    assert "refreshRuntimeIndicators()" in app_js
    assert "await syncCompanionRuntime({ applyLive2d: true });" in app_js
    assert "await syncCompanionRuntime({ reload: true, applyLive2d: true });" in app_js
    assert "await applyLive2dRuntimeState(runtimeToLive2dState(runtime));" in app_js
    assert ".self-use-dock-cell.runtime-state strong" in app_js
    assert "chatInputBlocked()" in app_js
    assert "function applyMessageExpressionsToLive2d(expressions)" in app_js
    assert '"/api/live2d/apply-expression"' in app_js
    assert "applyMessageExpressionsToLive2d(data.expressions || [])" in app_js
    assert "function applyLive2dRuntimeState(runtimeState, options = {})" in app_js
    assert '"/api/live2d/apply-runtime-state"' in app_js
    assert 'applyLive2dRuntimeState("speaking")' in app_js
    assert 'applyLive2dRuntimeState("idle")' in app_js
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
    assert ".self-use-stage-actions" in style_css
    assert ".companion-stage-action-status" in style_css
    assert ".companion-runtime-badge.listening" in style_css
    assert ".self-use-readiness" in style_css
    assert ".self-use-video-control" in style_css
    assert ".self-use-video-path" in style_css
    assert ".self-use-video-presence-grid" in style_css
    assert ".self-use-video-presence-item" in style_css
    assert ".self-use-action-control" in style_css
    assert ".self-use-action-buttons" in style_css
    assert ".self-use-video-actions" in style_css
    assert ".self-use-embodiment-editor" in style_css
    assert ".self-use-embodiment-grid" in style_css
    assert ".self-use-embodiment-actions" in style_css
    assert ".self-use-live2d-model-picker" in style_css
    assert ".self-use-video-recent" in style_css
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
    assert "Starting LING" in start_script
    assert "LING PID" in start_script

    assert "personal AI VTB" in roadmap
    assert "embodied workspace" in roadmap
    assert "Video Companion is external" in roadmap
    assert "integration panel" in roadmap
    assert "old Project Mnemosyne UI paths no longer dominate" in roadmap

    print("LING self-use shell verification passed")


if __name__ == "__main__":
    main()
