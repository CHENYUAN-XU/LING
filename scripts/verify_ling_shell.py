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
    assert "renderSelfUseApiGate()" in app_js
    assert "self-use-api-gate" in app_js
    assert "保持关闭，避免未接 API 时误触发模型调用" in app_js
    assert "function renderSelfUseVideoCompanionControl()" in app_js
    assert "renderSelfUseVideoCompanionControl()" in app_js
    assert "function renderVideoCompanionPresenceGrid(status, stateInfo, pathState)" in app_js
    assert "self-use-video-presence-grid" in app_js
    assert "self-use-video-presence-item" in app_js
    assert "Presence channel" in app_js
    assert "function videoCompanionPathState(config)" in app_js
    assert "config.project_path_exists === false" in app_js
    assert "self-use-video-path" in app_js
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
    assert 'text: "补形象资料", onclick: openPersonaEditor' in app_js
    assert 'text: "编辑形象", onclick: openPersonaEditor' in app_js
    assert "video.status?.session_active" in app_js
    assert "state.sending" in app_js
    assert "state.voicePlaying" in app_js
    assert "composerFocused" in app_js
    assert "composerDraft" in app_js
    assert "if (selfUseMode()) state.composerDraft = input.value.trim();" in app_js
    assert "state.composerFocused = true;" in app_js
    assert "state.composerFocused = false;" in app_js
    assert "if (state.composerFocused && !chatInputBlocked())" in app_js
    assert 'key: "listening"' in app_js
    assert "refreshRuntimeIndicators()" in app_js
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
    assert ".self-use-workspace" in style_css
    assert ".self-use-api-gate" in style_css
    assert ".self-use-api-dot" in style_css
    assert ".companion-runtime-badge" in style_css
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
    assert "old Project Mnemosyne UI paths no longer dominate" in roadmap

    print("LING self-use shell verification passed")


if __name__ == "__main__":
    main()
