from __future__ import annotations

import json
import hmac
import os
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import (
    GUEST_SECONDS,
    SESSION_COOKIE,
    SESSION_SECONDS,
    authenticate_user,
    clear_session,
    cleanup_expired_guest_users,
    convert_guest_user,
    create_session,
    create_guest_user,
    create_user,
    current_admin,
    current_user,
    delete_user_account,
    get_or_create_local_user,
    public_user,
    request_session_token,
    set_session_cookie,
)
from .archivist import recall_memories
from .config import load_config, set_config_section_bool, set_config_section_value, set_self_use_chat_enabled
from .database import dict_from_row, get_db, init_db, now_ts, sqlite_runtime_status
from .db_chat import db_chat, normalize_existing_assistant_messages
from .expression_assets import active_expression_labels, expression_assets_public, update_expression_asset_setting
from .voice import load_voice_config, voice_enabled
from .tts_service import (
    generate_tts_audio,
    generate_tts_reply_audio,
    generate_tts_single_chunk,
    get_last_tts_error,
    stream_local_http_tts_wav,
    tts_health_check,
)
from .speech_planner import build_tts_request_params, split_reply_into_utterances
from .live2d import load_live2d_config, live2d_enabled
from .embodiment import (
    apply_expression_to_live2d,
    apply_runtime_state_to_live2d,
    expression_to_live2d,
    live2d_connection_status,
    start_live2d_autoconnect,
    stop_live2d_connection,
)
from .expression_mapper import get_expression_categories, map_expression_to_body
from .runtime_state import get_runtime_state, presence_enabled
from .presence_loop import (
    detect_quiet_mode_request,
    get_presence_summary,
    on_idle,
    on_quiet_mode_enter,
    on_quiet_mode_exit,
    on_reply_end,
    on_reply_start,
    on_user_message,
)
from .camera_perception import camera_enabled, get_camera_config, get_camera_status, iter_camera_mjpeg
from .perception import get_perception_summary, run_perception_cycle
from .world_state import get_recent_world_observations, get_world_state_summary
from .screen_perception import (
    get_screen_config,
    get_screen_perception_status,
    run_screen_perception_cycle,
    screen_enabled,
)
from .proactive import (
    detect_quiet_request as proactive_detect_quiet,
    get_proactive_controller,
    get_proactive_scheduler_status,
    get_proactive_status,
    proactive_enabled,
    run_proactive_tick,
    start_proactive_scheduler,
    stop_proactive_scheduler,
)
from .video_companion import (
    VideoCompanionError,
    get_video_companion_status,
    public_video_companion_config,
    start_video_companion_session,
    stop_video_companion_session,
)
from .easyvtuber import EasyVtuberError, easyvtuber_status, open_easyvtuber
from .video_bridge import (
    build_video_session_context,
    build_video_turn_response,
    save_video_observation,
    save_video_session_summary,
    sync_video_consent,
)
from .user_consent import (
    CONSENT_KEYS,
    get_all_consents,
    get_user_consent,
    grant_consent,
    revoke_consent,
    user_has_consent,
)
from .user_export import export_user_data
from .group_chat import (
    create_group_conversation,
    group_chat,
    group_messages,
    list_group_conversations,
    mark_group_conversation_read,
    update_group_conversation,
)
from .conversation_memory import refresh_conversation_summary
from .identity import is_identity_polluted_boundary, scrub_identity_text
from .layered_memory import (
    apply_memory_decay,
    recall_layered_memory,
    refresh_memory_state,
    refresh_memory_summaries,
    store_layered_memories,
)
from .llm_client import LLMProviderError, llm_runtime_status, probe_llm_runtime
from .memory_review import context_traces, get_memory_item, memory_review, update_memory_item
from .memory_judge import update_judgement_status
from .memory_conflicts import update_conflict_status
from .memory_eval import (
    list_memory_eval_runs,
    run_chat_context_evaluation,
    run_live_answer_evaluation,
    run_memory_evaluation,
    run_memory_policy_evaluation,
    run_profile_context_evaluation,
    run_profile_live_answer_evaluation,
    run_state_expiry_evaluation,
    run_state_resolution_evaluation,
    seed_memory_eval_data,
)
from .memory_rag import semantic_memory_recall, sync_memory_embeddings
from .memory_policy import policy_snapshot
from .mirror import get_user_insight, update_user_insight
from .persona_forge import build_ling_prompt, build_prompt, forge_persona
from .privacy_policy import get_privacy_policy
from .rate_limit import InMemoryRateLimiter, client_identifier, rate_limit_enabled
from .error_monitor import list_error_events, record_error_event
from .embodiment_profile import persona_embodiment_profile
from .request_logging import (
    configure_request_logging,
    elapsed_ms,
    log_request,
    request_client_id,
    request_log_enabled,
)
from .growth_demo import clear_growth_demo_data, seed_growth_demo_data
from .growth_guidance import deactivate_guidance, supersede_conflicting_guidance
from .sculptor import (
    apply_revision_suggestion,
    dismiss_revision_suggestion,
    generate_revision_suggestion,
    list_revision_suggestions,
    maybe_auto_review_revision,
)


BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
ADMIN_WEB_DIR = BASE_DIR / "admin_web"
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
AVATAR_MAX_BYTES = 5 * 1024 * 1024
AVATAR_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
EMBODIMENT_IMAGE_KINDS = {"preview", "fallback"}

init_db()
try:
    cleanup_expired_guest_users()
except Exception as exc:
    print("[GuestCleanup] expired guest cleanup skipped:", exc)
try:
    normalize_existing_assistant_messages()
except Exception as exc:
    print("[MessagePresentation] legacy normalization skipped:", exc)
try:
    with get_db() as db:
        pending_chat_revisions = db.execute(
            """
            SELECT persona_revision_suggestions.id, persona_revision_suggestions.user_id
            FROM persona_revision_suggestions
            JOIN personas ON personas.id = persona_revision_suggestions.persona_id
            WHERE persona_revision_suggestions.status = 'pending'
              AND persona_revision_suggestions.origin = 'explicit_feedback'
              AND persona_revision_suggestions.base_version = personas.version
              AND personas.status = 'active'
            ORDER BY persona_revision_suggestions.id ASC
            """
        ).fetchall()
    for pending_revision in pending_chat_revisions:
        maybe_auto_review_revision(int(pending_revision["user_id"]), int(pending_revision["id"]))
except Exception as exc:
    print("[AdaptiveRuntime] pending chat preference reconciliation skipped:", exc)

app = FastAPI(title="LING")
rate_limiter = InMemoryRateLimiter(enabled=rate_limit_enabled())
request_logger = configure_request_logging()
_chat_stream_cancellations: dict[str, tuple[int, threading.Event]] = {}
_chat_stream_cancellations_lock = threading.Lock()


@app.middleware("http")
async def _request_logging_middleware(request: Request, call_next):
    if not request_log_enabled():
        return await call_next(request)
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    start = time.perf_counter()
    client_id = request_client_id(request)
    try:
        response = await call_next(request)
    except Exception as exc:
        log_request(
            request_logger,
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=500,
            duration_ms=elapsed_ms(start),
            client_id=client_id,
            error=exc.__class__.__name__,
        )
        record_error_event(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=500,
            error_type=exc.__class__.__name__,
            error_text=str(exc),
            client_id=client_id,
        )
        raise
    response.headers["X-Request-ID"] = request_id
    log_request(
        request_logger,
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=elapsed_ms(start),
        client_id=client_id,
    )
    if response.status_code >= 500:
        record_error_event(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            error_type="HTTPResponse",
            client_id=client_id,
        )
    return response


@app.middleware("http")
async def _rate_limit_middleware(request: Request, call_next):
    result = rate_limiter.check(
        client_id=client_identifier(request),
        method=request.method,
        path=request.url.path,
    )
    if not result.get("allowed", True):
        retry_after = int(result.get("retry_after") or 60)
        return JSONResponse(
            status_code=429,
            content={
                "detail": "rate limit exceeded",
                "rule": result.get("rule"),
                "retry_after": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
    return await call_next(request)


@app.on_event("startup")
def _startup_proactive_scheduler() -> None:
    status = start_proactive_scheduler()
    if status.get("scheduler_enabled"):
        print("[ProactiveScheduler]", status)
    live2d_status = start_live2d_autoconnect(force=True)
    if live2d_status.get("started"):
        print("[Live2D] startup connection scheduled")


@app.on_event("shutdown")
def _shutdown_proactive_scheduler() -> None:
    stop_proactive_scheduler()
    stop_live2d_connection()

PERSONA_OPTIONS = {
    "atmosphere": [
        "\u6e29\u67d4\u966a\u4f34",
        "\u51b7\u9759\u514b\u5236",
        "\u6d3b\u6cfc\u5410\u69fd",
        "\u6210\u719f\u53ef\u9760",
    ],
    "relationship": [
        "\u50cf\u670b\u53cb\u4e00\u6837",
        "\u7a33\u5b9a\u966a\u4f34",
        "\u7ed9\u6211\u5f15\u5bfc",
    ],
    "style": [
        "\u77ed\u53e5",
        "\u5c11\u8ffd\u95ee",
        "\u4f1a\u4e3b\u52a8\u5173\u5fc3",
        "\u53ef\u4ee5\u5410\u69fd",
    ],
    "boundaries": [
        "\u73b0\u5b9e\u611f\u5f3a",
        "\u4e0d\u8981\u592a\u9ecf\u4eba",
        "\u4e0d\u8981\u8bf4\u6559",
        "\u5c11\u7528\u8868\u60c5",
    ],
}


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=40)
    password: str = Field(..., min_length=8, max_length=200)
    nickname: str | None = Field(default=None, max_length=60)
    tab_session: bool = False


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=40)
    password: str = Field(..., min_length=8, max_length=200)
    tab_session: bool = False


class GuestConvertRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=40)
    password: str = Field(..., min_length=8, max_length=200)
    nickname: str | None = Field(default=None, max_length=60)
    tab_session: bool = False


class AccountDeleteRequest(BaseModel):
    confirm_username: str = Field(..., min_length=1, max_length=40)
    password: str | None = Field(default=None, max_length=200)


class ProfileUpdateRequest(BaseModel):
    nickname: str | None = Field(default=None, max_length=60)
    avatar_url: str | None = Field(default=None, max_length=500)
    gender: str | None = Field(default=None, max_length=20)
    birthday: str | None = Field(default=None, max_length=20)
    timezone: str | None = Field(default=None, max_length=80)
    signature: str | None = Field(default=None, max_length=200)
    bio: str | None = Field(default=None, max_length=1000)
    preferences: dict[str, Any] | None = None


class PersonaCreateRequest(BaseModel):
    selections: dict[str, list[str]] = Field(default_factory=dict)
    description: str = Field(default="", max_length=2000)
    preferred_name: str | None = Field(default=None, max_length=40)


class PersonaUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    summary: str | None = Field(default=None, max_length=1000)
    relationship: str | None = Field(default=None, max_length=120)
    speaking_style: str | None = Field(default=None, max_length=300)
    avatar_url: str | None = Field(default=None, max_length=500)
    appearance_description: str | None = Field(default=None, max_length=2000)
    desired_image: str | None = Field(default=None, max_length=2000)
    live2d_model_id: str | None = Field(default=None, max_length=120)
    live2d_preview_url: str | None = Field(default=None, max_length=500)
    fallback_image_url: str | None = Field(default=None, max_length=500)
    voice_profile: str | None = Field(default=None, max_length=200)


class ExpressionPreferenceUpdateRequest(BaseModel):
    enabled: bool | None = None
    mode: str | None = Field(default=None, max_length=20)


class ExpressionAssetUpdateRequest(BaseModel):
    enabled: bool
    cooldown_turns: int | None = Field(default=None, ge=0, le=20)
    admin_note: str | None = Field(default="", max_length=500)


class PersonaAvatarGenerateRequest(BaseModel):
    desired_image: str | None = Field(default=None, max_length=2000)


class PersonaDeleteRequest(BaseModel):
    confirm_name: str = Field(..., min_length=1, max_length=40)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    persona_id: int
    conversation_id: int | None = None
    retry_user_message_id: int | None = None
    client_message_id: str | None = Field(default=None, max_length=80)
    stream_id: str | None = Field(default=None, max_length=64)


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, max_length=20)
    pinned: bool | None = None


class GroupConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    persona_ids: list[int] = Field(..., min_length=2, max_length=6)


class GroupConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, max_length=20)
    pinned: bool | None = None


class GroupChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    group_conversation_id: int
    client_message_id: str | None = Field(default=None, max_length=80)


class MemoryUpdateRequest(BaseModel):
    priority: str | None = None
    locked: bool | None = None
    archived: bool | None = None


class PersonaRevisionRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


class PersonaRevisionDecisionRequest(BaseModel):
    note: str = Field(default="", max_length=1000)


class PersonaGrowthFeedbackRequest(BaseModel):
    reaction: str = Field(..., max_length=32)
    detail: str = Field(default="", max_length=500)


class PersonaPreferenceRequest(BaseModel):
    detail: str = Field(..., min_length=1, max_length=500)


class PersonaGrowthFeedbackResolutionRequest(BaseModel):
    reviewed_version: int = Field(..., ge=1)
    note: str = Field(default="", max_length=1000)


class InsightUpdateRequest(BaseModel):
    profile_summary: str | None = Field(default=None, max_length=1200)
    interaction_style: list[str] | None = None
    emotional_patterns: list[str] | None = None
    inferred_profile: dict[str, Any] | None = None
    topic_model: dict[str, Any] | None = None
    guidance: dict[str, Any] | None = None


class JudgementStatusRequest(BaseModel):
    status: str = Field(..., max_length=20)


class ConflictStatusRequest(BaseModel):
    status: str = Field(..., max_length=20)


class MemoryEvalRequest(BaseModel):
    reset_seed: bool = True
    include_semantic: bool = False


class SelfUseChatGateRequest(BaseModel):
    enabled: bool


class SelfUseIntegrationFlagRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=40)
    enabled: bool


class SelfUseIntegrationConfigRequest(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


@app.get("/api/health")
def health():
    return {"ok": True, "database": "sqlite", "db_initialized": True, "sqlite": sqlite_runtime_status()}


@app.get("/api/llm/status")
def llm_status(user: dict = Depends(current_user), task: str = "chat"):
    return {"llm": llm_runtime_status(task)}


@app.get("/api/companion/status")
def companion_status(user: dict = Depends(current_user), persona_id: int | None = None):
    self_use = _self_use_public(user)
    persona = _companion_status_persona(user, persona_id)
    embodiment = persona_embodiment_profile(persona)
    llm = llm_runtime_status("chat")
    video = _video_companion_status_for_user(int(user["id"]))
    live2d_config = load_live2d_config()
    voice_config = load_voice_config()
    voice_health = tts_health_check()
    live2d_status = live2d_connection_status()
    live2d_actions = _companion_live2d_actions(live2d_config)
    chat_gate = _companion_chat_gate(self_use, llm)

    api_ready = bool(chat_gate.get("ready"))
    visual_ready = bool(embodiment.get("visual_ready"))
    live2d_ready = _companion_live2d_ready(embodiment, live2d_config, live2d_status)
    lip_sync_ready = _companion_lip_sync_ready(live2d_config, live2d_status)
    voice_ready = bool(embodiment.get("voice_bound")) and bool(voice_health.get("available"))
    video_ready = bool(video.get("enabled")) and bool(video.get("connected"))
    runtime = _companion_runtime_state(self_use, llm, video, embodiment, live2d_status)
    readiness = [
        {
            "key": "api",
            "label": "API",
            "required": True,
            "ready": api_ready,
            "text": _companion_api_readiness_text(self_use, llm),
        },
        {
            "key": "visual",
            "label": "Visual",
            "required": False,
            "ready": visual_ready,
            "text": _companion_visual_readiness_text(embodiment),
        },
        {
            "key": "live2d",
            "label": "Live2D",
            "required": True,
            "ready": live2d_ready,
            "text": _companion_live2d_readiness_text(embodiment, live2d_config, live2d_status),
        },
        {
            "key": "voice",
            "label": "Voice",
            "required": True,
            "ready": voice_ready,
            "text": _companion_voice_readiness_text(embodiment, voice_config, voice_health),
        },
        {
            "key": "lip_sync",
            "label": "Lip sync",
            "required": True,
            "ready": lip_sync_ready,
            "text": _companion_lip_sync_readiness_text(live2d_config, live2d_status),
        },
        {
            "key": "video",
            "label": "Video",
            "required": False,
            "ready": video_ready,
            "text": _companion_video_readiness_text(video),
        },
    ]
    required_readiness = [item for item in readiness if item["required"]]
    optional_readiness = [item for item in readiness if not item["required"]]
    ready_count = sum(1 for item in required_readiness if item["ready"])
    return {
        "self_use": self_use,
        "persona_id": int(persona["id"]) if persona else None,
        "name": persona.get("name") if persona else None,
        "embodiment": embodiment,
        "llm": llm,
        "video_companion": video,
        "voice": voice_health,
        "live2d": live2d_status,
        "live2d_actions": live2d_actions,
        "chat_gate": chat_gate,
        "runtime": runtime,
        "readiness": readiness,
        "ready_count": ready_count,
        "total_count": len(required_readiness),
        "optional_ready_count": sum(1 for item in optional_readiness if item["ready"]),
        "optional_total_count": len(optional_readiness),
    }


@app.post("/api/self-use/chat-gate")
def self_use_chat_gate(req: SelfUseChatGateRequest, request: Request, user: dict = Depends(current_user)):
    self_use = _require_self_use_local_config_change(request, user)

    llm = llm_runtime_status("chat")
    current_gate = _companion_chat_gate(self_use, llm)
    if req.enabled and not bool(current_gate.get("can_enable")) and not bool(current_gate.get("ready")):
        raise HTTPException(
            status_code=400,
            detail={
                "reason": current_gate.get("reason"),
                "missing": current_gate.get("missing", []),
                "text": current_gate.get("text"),
            },
        )

    set_self_use_chat_enabled(bool(req.enabled))
    updated_self_use = _self_use_public(user)
    updated_gate = _companion_chat_gate(updated_self_use, llm_runtime_status("chat"))
    return {
        "self_use": updated_self_use,
        "chat_gate": updated_gate,
        "companion_status": companion_status(user),
    }


@app.post("/api/self-use/llm-probe")
def self_use_llm_probe(request: Request, user: dict = Depends(current_user)):
    _require_self_use_local_config_change(request, user)
    probe = probe_llm_runtime("chat")
    return {
        "probe": probe,
        "companion_status": companion_status(user),
    }


@app.post("/api/self-use/integration-flag")
def self_use_integration_flag(req: SelfUseIntegrationFlagRequest, request: Request, user: dict = Depends(current_user)):
    _require_self_use_local_config_change(request, user)
    allowed = {
        "live2d": ("live2d", "enabled"),
        "voice": ("voice", "enabled"),
        "video_companion": ("video_companion", "enabled"),
        "screen": ("screen", "enabled"),
        "proactive": ("proactive", "enabled"),
    }
    key = str(req.key or "").strip()
    if key not in allowed:
        raise HTTPException(status_code=400, detail="unsupported LING integration flag")
    section, config_key = allowed[key]
    set_config_section_bool(section, config_key, bool(req.enabled))
    if key == "live2d":
        if req.enabled:
            start_live2d_autoconnect(force=True)
        else:
            stop_live2d_connection()
    elif key == "proactive" and not req.enabled:
        stop_proactive_scheduler()
    return {
        "key": key,
        "enabled": bool(req.enabled),
        "companion_status": companion_status(user),
    }


@app.post("/api/self-use/integration-config")
def self_use_integration_config(req: SelfUseIntegrationConfigRequest, request: Request, user: dict = Depends(current_user)):
    _require_self_use_local_config_change(request, user)
    allowed = {
        "live2d.vts_ws_url": ("live2d", "vts_ws_url", _validate_ws_url),
        "live2d.idle_expression": ("live2d", "idle_expression", _validate_live2d_action_name),
        "live2d.listening_expression": ("live2d", "listening_expression", _validate_live2d_action_name),
        "live2d.thinking_expression": ("live2d", "thinking_expression", _validate_live2d_action_name),
        "live2d.speaking_expression": ("live2d", "speaking_expression", _validate_live2d_action_name),
        "live2d.lip_sync_enabled": ("live2d", "lip_sync_enabled", _validate_config_bool),
        "live2d.lip_sync_parameter": ("live2d", "lip_sync_parameter", _validate_voice_name),
        "live2d.lip_sync_gain": ("live2d", "lip_sync_gain", _validate_lip_sync_gain),
        "voice.tts_provider": ("voice", "tts_provider", _validate_voice_provider),
        "voice.tts_model": ("voice", "tts_model", _validate_voice_name),
        "voice.api_key_env": ("voice", "api_key_env", _validate_env_name),
        "voice.voice_id": ("voice", "voice_id", _validate_voice_name),
        "voice.response_format": ("voice", "response_format", _validate_voice_response_format),
        "voice.instructions": ("voice", "instructions", _validate_optional_config_text),
        "voice.rate": ("voice", "rate", _validate_voice_rate),
        "voice.max_chunk_length": ("voice", "max_chunk_length", _validate_voice_chunk_length),
        "voice.auto_play": ("voice", "auto_play", _validate_config_bool),
        "video_companion.base_url": ("video_companion", "base_url", _validate_http_url),
        "video_companion.ws_url": ("video_companion", "ws_url", _validate_ws_url),
        "video_companion.project_path": ("video_companion", "project_path", _validate_local_path_text),
    }
    saved: dict[str, str] = {}
    for raw_key, raw_value in (req.values or {}).items():
        key = str(raw_key or "").strip()
        if key not in allowed:
            raise HTTPException(status_code=400, detail=f"unsupported LING integration config: {key}")
        section, config_key, validator = allowed[key]
        value = validator(raw_value, key)
        set_config_section_value(section, config_key, value)
        saved[key] = value
    return {"saved": saved, "companion_status": companion_status(user)}


def _require_self_use_local_config_change(request: Request, user: dict[str, Any]) -> dict[str, Any]:
    self_use = _self_use_public(user)
    if not bool(self_use.get("enabled")):
        raise HTTPException(status_code=403, detail="LING self-use mode is not enabled for this user")

    config = _self_use_config()
    if bool(config.get("require_localhost", True)) and not _is_local_request(request):
        raise HTTPException(status_code=403, detail="local LING configuration changes are only allowed from localhost")
    return self_use


def _validate_http_url(value: Any, key: str) -> str:
    text = str(value or "").strip()
    if not (text.startswith("http://") or text.startswith("https://")):
        raise HTTPException(status_code=400, detail=f"{key} must start with http:// or https://")
    return _bounded_config_text(text.rstrip("/"), key, 300)


def _validate_ws_url(value: Any, key: str) -> str:
    text = str(value or "").strip()
    if not (text.startswith("ws://") or text.startswith("wss://")):
        raise HTTPException(status_code=400, detail=f"{key} must start with ws:// or wss://")
    return _bounded_config_text(text, key, 300)


def _validate_live2d_action_name(value: Any, key: str) -> str:
    text = str(value or "").strip()
    if any(char in text for char in ("\n", "\r", "\t")):
        raise HTTPException(status_code=400, detail=f"{key} must be a single action name")
    return _bounded_config_text(text, key, 80)


def _validate_voice_provider(value: Any, key: str) -> str:
    provider = str(value or "").strip().lower()
    if provider != "openai_tts":
        raise HTTPException(status_code=400, detail=f"{key} must be openai_tts")
    return provider


def _validate_config_bool(value: Any, key: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise HTTPException(status_code=400, detail=f"{key} must be true or false")


def _validate_voice_response_format(value: Any, key: str) -> str:
    fmt = str(value or "").strip().lower()
    if fmt != "mp3":
        raise HTTPException(status_code=400, detail=f"{key} must be mp3 for LING reply playback")
    return fmt


def _validate_voice_name(value: Any, key: str) -> str:
    text = str(value or "").strip()
    if any(char in text for char in ("\n", "\r", "\t", " ")):
        raise HTTPException(status_code=400, detail=f"{key} must be a compact identifier")
    return _bounded_config_text(text, key, 120)


def _validate_env_name(value: Any, key: str) -> str:
    text = str(value or "").strip()
    if not text or not (text[0].isalpha() or text[0] == "_"):
        raise HTTPException(status_code=400, detail=f"{key} must be an environment variable name")
    if any(not (char.isalnum() or char == "_") for char in text):
        raise HTTPException(status_code=400, detail=f"{key} must contain only letters, numbers, and underscores")
    return _bounded_config_text(text, key, 80)


def _validate_optional_config_text(value: Any, key: str) -> str:
    text = str(value or "").strip()
    if "\r" in text:
        raise HTTPException(status_code=400, detail=f"{key} cannot contain carriage returns")
    if len(text) > 1000:
        raise HTTPException(status_code=400, detail=f"{key} is too long")
    return text


def _validate_voice_rate(value: Any, key: str) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{key} must be a number") from None
    if parsed < 0.25 or parsed > 4.0:
        raise HTTPException(status_code=400, detail=f"{key} must be between 0.25 and 4.0")
    return f"{parsed:g}"


def _validate_voice_chunk_length(value: Any, key: str) -> str:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{key} must be an integer") from None
    if parsed < 20 or parsed > 500:
        raise HTTPException(status_code=400, detail=f"{key} must be between 20 and 500")
    return str(parsed)


def _validate_lip_sync_gain(value: Any, key: str) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{key} must be numeric") from exc
    if parsed < 0.1 or parsed > 10.0:
        raise HTTPException(status_code=400, detail=f"{key} must be between 0.1 and 10")
    return str(parsed)


def _validate_local_path_text(value: Any, key: str) -> str:
    return _bounded_config_text(str(value or "").strip(), key, 500)


def _bounded_config_text(text: str, key: str, max_length: int) -> str:
    if not text:
        raise HTTPException(status_code=400, detail=f"{key} cannot be empty")
    if "\n" in text or "\r" in text:
        raise HTTPException(status_code=400, detail=f"{key} cannot contain newlines")
    if len(text) > max_length:
        raise HTTPException(status_code=400, detail=f"{key} is too long")
    return text


@app.get("/api/privacy")
def privacy_policy():
    return {"policy": get_privacy_policy()}


@app.get("/api/memory/policy")
def memory_policy(user: dict = Depends(current_user)):
    return {"policy": policy_snapshot()}


@app.get("/api/state")
def state(user: dict = Depends(current_user)):
    return {
        "auth": {"logged_in": True, "user": public_user(user)},
        "profile": _get_profile(int(user["id"])),
    }


def _start_authenticated_session(
    response: Response,
    user: dict[str, Any],
    *,
    tab_session: bool = False,
    max_age: int = SESSION_SECONDS,
) -> dict[str, Any]:
    token = create_session(int(user["id"]), max_age=max_age)
    payload = {"user": public_user(user), "profile": _get_profile(int(user["id"]))}
    payload["self_use"] = _self_use_public(user)
    if tab_session:
        payload["tab_session_token"] = token
    else:
        set_session_cookie(response, token, max_age=max_age)
    return payload


def _self_use_config() -> dict[str, Any]:
    config = load_config().get("self_use", {}) or {}
    return config if isinstance(config, dict) else {}


def _self_use_public(user: dict[str, Any]) -> dict[str, Any]:
    config = _self_use_config()
    enabled = bool(config.get("enabled", False)) and str(user.get("username") or "") == str(config.get("username") or "mio_owner")
    return {"enabled": enabled, "chat_enabled": bool(config.get("chat_enabled", False)) if enabled else True}


def _reject_legacy_auth_in_self_use() -> None:
    if bool(_self_use_config().get("enabled")):
        raise HTTPException(status_code=404, detail="LING self-use mode only accepts local owner authentication")


def _self_use_group_disabled(user: dict[str, Any]) -> bool:
    return bool(_self_use_public(user).get("enabled"))


def _reject_self_use_internal_camera(user: dict[str, Any]) -> None:
    if _self_use_public(user).get("enabled"):
        raise HTTPException(
            status_code=404,
            detail="LING self-use mode delegates camera and realtime video to the external Video Companion",
        )


def _self_use_bound_persona_id(user: dict[str, Any]) -> int | None:
    if not _self_use_public(user).get("enabled"):
        return None
    config = _self_use_config()
    user_id = int(user["id"])
    with get_db() as db:
        row = db.execute(
            """
            SELECT personas.id
            FROM self_use_companion_bindings
            JOIN personas ON personas.id = self_use_companion_bindings.persona_id
            WHERE self_use_companion_bindings.user_id = ?
              AND personas.user_id = ?
              AND personas.status = 'active'
            """,
            (user_id, user_id),
        ).fetchone()
    if row:
        return int(row["id"])
    persona = _ensure_self_use_default_persona(user_id, config)
    return int(persona["id"]) if persona else None


def _require_self_use_bound_persona(user: dict[str, Any], persona_id: int) -> None:
    bound_id = _self_use_bound_persona_id(user)
    if bound_id is not None and int(persona_id) != bound_id:
        raise HTTPException(status_code=404, detail="companion not found in LING self-use mode")


def _companion_status_persona(user: dict[str, Any], persona_id: int | None = None) -> dict[str, Any] | None:
    target_persona_id = persona_id
    if _self_use_public(user).get("enabled"):
        bound_id = _self_use_bound_persona_id(user)
        if bound_id is None:
            return None
        if target_persona_id is not None and int(target_persona_id) != int(bound_id):
            raise HTTPException(status_code=404, detail="companion not found in LING self-use mode")
        target_persona_id = bound_id

    with get_db() as db:
        if target_persona_id is not None:
            row = db.execute(
                "SELECT * FROM personas WHERE id = ? AND user_id = ? AND status = 'active'",
                (int(target_persona_id), int(user["id"])),
            ).fetchone()
        else:
            row = db.execute(
                """
                SELECT * FROM personas
                WHERE user_id = ? AND status = 'active'
                ORDER BY updated_at DESC, id ASC
                LIMIT 1
                """,
                (int(user["id"]),),
            ).fetchone()
    persona = _public_persona(dict_from_row(row))
    if target_persona_id is not None and not persona:
        raise HTTPException(status_code=404, detail="persona not found")
    return persona


def _companion_api_readiness_text(self_use: dict[str, Any], llm: dict[str, Any]) -> str:
    if not bool(llm.get("configured")):
        missing = ", ".join(str(item) for item in llm.get("missing") or [])
        return f"缺少 {missing}" if missing else "模型未配置"
    if not bool(llm.get("verified")):
        verification = llm.get("verification") if isinstance(llm.get("verification"), dict) else {}
        error = str(verification.get("error") or "").strip()
        return error or "路由已配置，尚未检测连接"
    if bool(self_use.get("chat_enabled", True)):
        provider = str(llm.get("provider") or "").strip()
        model = str(llm.get("model") or "").strip()
        return " / ".join(part for part in (provider, model) if part) or "连接已验证"
    return "连接已验证，仍保持手动关闭"


def _companion_chat_gate(self_use: dict[str, Any], llm: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(self_use.get("chat_enabled", True))
    self_use_enabled = bool(self_use.get("enabled", False))
    llm_configured = bool(llm.get("configured"))
    llm_verified = bool(llm.get("verified"))
    missing = [str(item) for item in (llm.get("missing") or []) if str(item).strip()]
    reason = "ready"
    if not llm_configured and missing:
        reason = "missing_api_key"
    elif not llm_configured:
        reason = "llm_not_configured"
    elif not llm_verified:
        reason = "llm_unverified"
    elif self_use_enabled and not enabled:
        reason = "disabled_by_config"
    elif not self_use_enabled:
        reason = "legacy_mode"
    return {
        "enabled": enabled,
        "self_use_enabled": self_use_enabled,
        "llm_configured": llm_configured,
        "llm_verified": llm_verified,
        "ready": enabled and llm_configured and llm_verified,
        "can_enable": self_use_enabled and not enabled and llm_configured and llm_verified,
        "reason": reason,
        "provider": str(llm.get("provider") or ""),
        "model": str(llm.get("model") or ""),
        "base_url": str(llm.get("base_url") or ""),
        "api_key_env": str(llm.get("api_key_env") or ""),
        "requires_api_key": bool(llm.get("requires_api_key")),
        "missing": missing,
        "verification": llm.get("verification") or {"state": "unverified", "checked_at": None},
        "text": _companion_api_readiness_text(self_use, llm),
    }


def _video_companion_status_for_user(user_id: int) -> dict[str, Any]:
    status = dict(get_video_companion_status())
    recent = get_recent_world_observations(user_id, source="video_companion", limit=50)
    observation = next(
        (item for item in recent if item.get("observation_type") not in {"session_summary", "consent_sync"}),
        None,
    )
    summary = next((item for item in recent if item.get("observation_type") == "session_summary"), None)
    consent_sync = next((item for item in recent if item.get("observation_type") == "consent_sync"), None)
    status["recent_observation"] = _video_activity_public(observation, fresh_seconds=300)
    status["recent_summary"] = _video_activity_public(summary)
    status["recent_consent_sync"] = _video_activity_public(consent_sync)
    return status


def _video_activity_public(item: dict[str, Any] | None, *, fresh_seconds: int | None = None) -> dict[str, Any] | None:
    if not item:
        return None
    created_at = int(item.get("created_at") or 0)
    age_seconds = max(0, now_ts() - created_at) if created_at else None
    result = {
        "id": item.get("id"),
        "observation_type": item.get("observation_type"),
        "content": str(item.get("content") or "")[:500],
        "confidence": item.get("confidence"),
        "created_at": created_at or None,
        "age_seconds": age_seconds,
    }
    if fresh_seconds is not None:
        result["fresh"] = age_seconds is not None and age_seconds <= fresh_seconds
    return result


def _companion_live2d_ready(
    embodiment: dict[str, Any],
    config: dict[str, Any],
    status: dict[str, Any],
) -> bool:
    return bool(
        embodiment.get("live2d_bound")
        and config.get("enabled")
        and status.get("connected")
        and status.get("authenticated")
        and not status.get("last_error")
        and not status.get("capabilities_stale")
        and _companion_live2d_model_matches(embodiment, status)
    )


def _companion_live2d_model_matches(embodiment: dict[str, Any], status: dict[str, Any]) -> bool:
    model_id = str(embodiment.get("live2d_model_id") or "").strip().casefold()
    current = status.get("current_model") if isinstance(status.get("current_model"), dict) else {}
    if not model_id or current.get("modelLoaded") is False:
        return False
    candidates = {
        str(current.get(key) or "").strip().casefold()
        for key in ("modelID", "modelName", "vtsModelName", "modelFileName")
    }
    return model_id in candidates


def _companion_live2d_model_label(status: dict[str, Any]) -> str:
    current = status.get("current_model") if isinstance(status.get("current_model"), dict) else {}
    for key in ("modelName", "vtsModelName", "modelFileName", "modelID"):
        value = str(current.get(key) or "").strip()
        if value:
            return value
    return ""


def _companion_live2d_readiness_text(
    embodiment: dict[str, Any],
    config: dict[str, Any],
    status: dict[str, Any],
) -> str:
    model_id = str(embodiment.get("live2d_model_id") or "").strip()
    if not model_id:
        return "未绑定模型"
    if not bool(config.get("enabled", False)):
        return "形象已绑定，Live2D 适配器未启用"
    if not bool(status.get("connected")):
        return "模型已绑定，VTube Studio 未连接"
    if not bool(status.get("authenticated")):
        return "VTube Studio 已连接但未授权"
    error = str(status.get("last_error") or "").strip()
    if error:
        return f"VTube Studio 错误：{error[:160]}"
    if bool(status.get("capabilities_stale")):
        return "VTube Studio 已连接，模型与动作状态需刷新"
    current_label = _companion_live2d_model_label(status)
    if not current_label:
        return "VTube Studio 已连接，但当前未加载模型"
    if not _companion_live2d_model_matches(embodiment, status):
        return f"当前模型 {current_label} 与绑定 {model_id} 不一致"
    return f"{current_label} 已连接"


def _require_self_use_live2d_ready(user: dict[str, Any]) -> None:
    self_use = _self_use_public(user)
    if not bool(self_use.get("enabled")):
        return
    persona = _companion_status_persona(user, None)
    embodiment = persona_embodiment_profile(persona)
    config = load_live2d_config()
    status = live2d_connection_status()
    if not _companion_live2d_ready(embodiment, config, status):
        detail = _companion_live2d_readiness_text(embodiment, config, status)
        raise HTTPException(status_code=409, detail=f"LING Live2D 尚未就绪：{detail}")


def _companion_lip_sync_ready(config: dict[str, Any], status: dict[str, Any]) -> bool:
    if not bool(config.get("enabled")) or not bool(config.get("lip_sync_enabled", True)):
        return False
    if not bool(status.get("connected")) or not bool(status.get("authenticated")):
        return False
    if status.get("last_error") or status.get("capabilities_stale"):
        return False
    parameter = str(config.get("lip_sync_parameter") or "MouthOpen").strip().casefold()
    return parameter in {
        str(item.get("name") or "").strip().casefold()
        for item in status.get("available_parameters", [])
        if isinstance(item, dict)
    }


def _companion_lip_sync_readiness_text(config: dict[str, Any], status: dict[str, Any]) -> str:
    parameter = str(config.get("lip_sync_parameter") or "MouthOpen").strip()
    if not bool(config.get("enabled")):
        return "Live2D 未启用"
    if not bool(config.get("lip_sync_enabled", True)):
        return "音频驱动嘴型已关闭"
    if not bool(status.get("connected")) or not bool(status.get("authenticated")):
        return f"等待 VTube Studio 连接后检测 {parameter}"
    if status.get("capabilities_stale"):
        return "VTube Studio 参数状态需刷新"
    if not _companion_lip_sync_ready(config, status):
        return f"当前 VTube Studio 未提供 {parameter} 输入参数"
    return f"{parameter} 可由回复音频驱动"


def _companion_visual_readiness_text(embodiment: dict[str, Any]) -> str:
    if bool(embodiment.get("visual_ready")):
        return str(embodiment.get("visual_label") or "Visual bound")
    if bool(embodiment.get("visual_legacy_only")):
        return "仅旧头像 fallback，建议绑定 Live2D preview 或 fallback 图像"
    return "未绑定 Live2D preview / fallback 图像"


def _companion_voice_readiness_text(
    embodiment: dict[str, Any],
    config: dict[str, Any],
    health: dict[str, Any],
) -> str:
    profile = str(embodiment.get("voice_profile") or "").strip()
    if not profile:
        provider_voice = str(config.get("voice_id") or health.get("voice_id") or "").strip()
        if provider_voice and bool(config.get("enabled", False)):
            return f"Voice profile unbound; provider voice {provider_voice}"
        return "Voice profile unbound"
    if not bool(config.get("enabled", False)):
        return "声音已绑定，TTS 未启用"
    if not bool(health.get("available")):
        error = str(health.get("error") or "").strip()
        return error or "声音已绑定，语音 provider 未就绪"
    return profile


def _companion_video_readiness_text(video: dict[str, Any]) -> str:
    if not bool(video.get("enabled")):
        return "未启用"
    if bool(video.get("connected")):
        external = video.get("status") if isinstance(video.get("status"), dict) else {}
        return "视频会话运行中" if bool(external.get("session_active")) else "外部服务已连接，会话未启动"
    reason = str(video.get("reason") or "").strip()
    return reason or "未连接"


def _companion_live2d_actions(config: dict[str, Any]) -> dict[str, Any]:
    idle_expressions = config.get("idle_expressions") or []
    if isinstance(idle_expressions, list):
        idle_expression = str(idle_expressions[0]) if idle_expressions else "Default"
    else:
        idle_expression = str(idle_expressions)
    expression_map = config.get("expression_map") or {}
    if not isinstance(expression_map, dict):
        expression_map = {}
    return {
        "idle_expression": idle_expression,
        "listening_expression": str(config.get("listening_expression") or "Listening"),
        "speaking_expression": str(config.get("speaking_expression") or "Talking"),
        "thinking_expression": str(config.get("thinking_expression") or "Thinking"),
        "expression_map": expression_map,
        "expression_map_count": len(expression_map),
    }


def _companion_runtime_state(
    self_use: dict[str, Any],
    llm: dict[str, Any],
    video: dict[str, Any],
    embodiment: dict[str, Any],
    live2d_status: dict[str, Any],
) -> dict[str, Any]:
    video_status = video.get("status") if isinstance(video.get("status"), dict) else {}
    if bool(video.get("enabled")) and bool(video.get("connected")) and bool(video_status.get("session_active")):
        return {
            "key": "video",
            "label": "视频会话中",
            "detail": "Video Companion 正在接管实时感知",
            "ready": True,
        }
    if not bool(self_use.get("chat_enabled", True)) or not bool(llm.get("configured")):
        return {
            "key": "offline",
            "label": "模型未启用",
            "detail": "接好 API 后再开始对话",
            "ready": False,
        }
    if live2d_enabled():
        config = load_live2d_config()
        if _companion_live2d_ready(embodiment, config, live2d_status):
            return {"key": "present", "label": "在场", "detail": "Live2D 已连接", "ready": True}
        if bool(embodiment.get("live2d_bound")):
            detail = _companion_live2d_readiness_text(embodiment, config, live2d_status)
            return {"key": "waiting", "label": "待连接", "detail": detail, "ready": False}
        if bool(live2d_status.get("connected")):
            return {"key": "waiting", "label": "待绑定", "detail": "VTube Studio 已连接，当前模型尚未绑定给澪", "ready": False}
    return {"key": "idle", "label": "待机", "detail": "基础陪伴状态", "ready": True}


def _is_local_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host in {"127.0.0.1", "::1", "localhost"}:
        return True
    return host.startswith("127.")


def _default_self_use_persona(name: str) -> dict[str, Any]:
    persona = {
        "name": scrub_identity_text(name.strip() or "澪"),
        "summary": "",
        "traits": [],
        "relationship": "",
        "speaking_style": "",
        "appearance_description": "",
        "desired_image": "",
        "live2d_model_id": "",
        "live2d_preview_url": "",
        "fallback_image_url": "",
        "voice_profile": "",
        "psychological_fit_notes": "",
        "psychological_profile": {
            "primary_needs": [],
            "comfort_strategy": [],
            "avoid_patterns": [],
            "growth_direction": [],
        },
        "growth_notes": "",
        "boundaries": [],
        "memory_profile": {},
    }
    persona["prompt"] = build_ling_prompt(persona)
    return persona


def _refresh_self_use_prompt(db, persona: dict[str, Any]) -> dict[str, Any]:
    prompt = build_ling_prompt(persona)
    if str(persona.get("prompt") or "") == prompt:
        return persona
    db.execute("UPDATE personas SET prompt = ?, updated_at = ? WHERE id = ?", (prompt, now_ts(), persona["id"]))
    refreshed = dict(persona)
    refreshed["prompt"] = prompt
    return refreshed


def _set_self_use_companion_binding(db, user_id: int, persona_id: int) -> None:
    ts = now_ts()
    db.execute(
        """
        INSERT INTO self_use_companion_bindings (user_id, persona_id, bound_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            persona_id = excluded.persona_id,
            updated_at = excluded.updated_at
        """,
        (user_id, persona_id, ts, ts),
    )


def _should_reset_legacy_self_use_persona(db, persona: dict[str, Any]) -> bool:
    if str(persona.get("name") or "") != "澪":
        return False
    summary = str(persona.get("summary") or "")
    relationship = str(persona.get("relationship") or "")
    if not summary and not relationship:
        return False
    generated_summaries = {
        "基础设定待填写。",
        "一个以 Live2D 形象在场的长期陪伴体，安静、机敏、低压迫，重视真实相处中的节奏和边界。",
    }
    generated_relationships = {"未设定", "自用长期陪伴体", ""}
    if summary not in generated_summaries or relationship not in generated_relationships:
        return False
    version = db.execute(
        """
        SELECT change_type
        FROM persona_versions
        WHERE persona_id = ?
        ORDER BY version DESC, id DESC
        LIMIT 1
        """,
        (persona["id"],),
    ).fetchone()
    return bool(version and str(version["change_type"] or "") in {"self_use_default", "self_use_default_reset"})


def _reset_self_use_persona_to_blank(db, persona: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    ts = now_ts()
    blank = _default_self_use_persona(str(config.get("default_persona_name") or persona.get("name") or "澪"))
    next_version = int(persona.get("version") or 1) + 1
    db.execute(
        """
        UPDATE personas
        SET name = ?, summary = ?, prompt = ?, traits_json = ?, relationship = ?,
            speaking_style = ?, boundaries_json = ?, memory_profile_json = ?,
            psychological_profile_json = ?, psychological_fit_notes = ?,
            appearance_description = ?, desired_image = ?, live2d_model_id = ?,
            live2d_preview_url = ?, fallback_image_url = ?, voice_profile = ?, growth_notes = ?,
            version = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            blank["name"],
            blank["summary"],
            blank["prompt"],
            json.dumps(blank["traits"], ensure_ascii=False),
            blank["relationship"],
            blank["speaking_style"],
            json.dumps(blank["boundaries"], ensure_ascii=False),
            json.dumps(blank.get("memory_profile", {}), ensure_ascii=False),
            json.dumps(blank.get("psychological_profile", {}), ensure_ascii=False),
            blank.get("psychological_fit_notes", ""),
            blank.get("appearance_description", ""),
            blank.get("desired_image", ""),
            blank.get("live2d_model_id", ""),
            blank.get("live2d_preview_url", ""),
            blank.get("fallback_image_url", ""),
            blank.get("voice_profile", ""),
            blank.get("growth_notes", ""),
            next_version,
            ts,
            persona["id"],
        ),
    )
    db.execute(
        """
        INSERT INTO persona_versions (
            persona_id, version, name, summary, prompt, traits_json,
            relationship, speaking_style, boundaries_json,
            psychological_profile_json, psychological_fit_notes,
            appearance_description, desired_image, live2d_model_id,
            live2d_preview_url, fallback_image_url, voice_profile, growth_notes,
            reason, change_type, change_notes_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            persona["id"],
            next_version,
            blank["name"],
            blank["summary"],
            blank["prompt"],
            json.dumps(blank["traits"], ensure_ascii=False),
            blank["relationship"],
            blank["speaking_style"],
            json.dumps(blank["boundaries"], ensure_ascii=False),
            json.dumps(blank.get("psychological_profile", {}), ensure_ascii=False),
            blank.get("psychological_fit_notes", ""),
            blank.get("appearance_description", ""),
            blank.get("desired_image", ""),
            blank.get("live2d_model_id", ""),
            blank.get("live2d_preview_url", ""),
            blank.get("fallback_image_url", ""),
            blank.get("voice_profile", ""),
            blank.get("growth_notes", ""),
            "clear generated self-use defaults",
            "self_use_default_reset",
            json.dumps(["清空系统预置的澪基础设定，等待用户自行填写"], ensure_ascii=False),
            ts,
        ),
    )
    row = db.execute("SELECT * FROM personas WHERE id = ?", (persona["id"],)).fetchone()
    return dict_from_row(row) or {}


def _ensure_self_use_default_persona(user_id: int, config: dict[str, Any]) -> dict[str, Any] | None:
    if not bool(config.get("seed_default_persona", True)):
        return None
    default_name = str(config.get("default_persona_name") or "澪").strip() or "澪"
    with get_db() as db:
        bound_existing = db.execute(
            """
            SELECT personas.*
            FROM self_use_companion_bindings
            JOIN personas ON personas.id = self_use_companion_bindings.persona_id
            WHERE self_use_companion_bindings.user_id = ?
              AND personas.user_id = ?
              AND personas.status = 'active'
            """,
            (user_id, user_id),
        ).fetchone()
        if bound_existing:
            bound_persona = dict_from_row(bound_existing) or {}
            if _should_reset_legacy_self_use_persona(db, bound_persona):
                bound_persona = _reset_self_use_persona_to_blank(db, bound_persona, config)
            bound_persona = _refresh_self_use_prompt(db, bound_persona)
            _set_self_use_companion_binding(db, user_id, int(bound_persona["id"]))
            return bound_persona

        named_existing = db.execute(
            """
            SELECT * FROM personas
            WHERE user_id = ? AND status = 'active' AND name = ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (user_id, default_name),
        ).fetchone()
        if named_existing:
            named_persona = dict_from_row(named_existing) or {}
            if _should_reset_legacy_self_use_persona(db, named_persona):
                named_persona = _reset_self_use_persona_to_blank(db, named_persona, config)
            named_persona = _refresh_self_use_prompt(db, named_persona)
            _set_self_use_companion_binding(db, user_id, int(named_persona["id"]))
            return named_persona

        existing_rows = db.execute(
            "SELECT * FROM personas WHERE user_id = ? AND status = 'active' ORDER BY id ASC",
            (user_id,),
        ).fetchall()
        if len(existing_rows) == 1:
            existing_persona = dict_from_row(existing_rows[0]) or {}
            if _should_reset_legacy_self_use_persona(db, existing_persona):
                existing_persona = _reset_self_use_persona_to_blank(db, existing_persona, config)
            existing_persona = _refresh_self_use_prompt(db, existing_persona)
            _set_self_use_companion_binding(db, user_id, int(existing_persona["id"]))
            return existing_persona

        ts = now_ts()
        persona = _default_self_use_persona(default_name)
        cursor = db.execute(
            """
            INSERT INTO personas (
                user_id, name, summary, prompt, traits_json, relationship,
                speaking_style, boundaries_json, memory_profile_json,
                psychological_profile_json, psychological_fit_notes,
                appearance_description, desired_image, live2d_model_id,
                live2d_preview_url, fallback_image_url, voice_profile, growth_notes,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                persona["name"],
                persona["summary"],
                persona["prompt"],
                json.dumps(persona["traits"], ensure_ascii=False),
                persona["relationship"],
                persona["speaking_style"],
                json.dumps(persona["boundaries"], ensure_ascii=False),
                json.dumps(persona.get("memory_profile", {}), ensure_ascii=False),
                json.dumps(persona.get("psychological_profile", {}), ensure_ascii=False),
                persona.get("psychological_fit_notes", ""),
                persona.get("appearance_description", ""),
                persona.get("desired_image", ""),
                persona.get("live2d_model_id", ""),
                persona.get("live2d_preview_url", ""),
                persona.get("fallback_image_url", ""),
                persona.get("voice_profile", ""),
                persona.get("growth_notes", ""),
                ts,
                ts,
            ),
        )
        persona_id = int(cursor.lastrowid)
        db.execute(
            """
            INSERT INTO persona_versions (
                persona_id, version, name, summary, prompt, traits_json,
                relationship, speaking_style, boundaries_json,
                psychological_profile_json, psychological_fit_notes,
                appearance_description, desired_image, live2d_model_id,
                live2d_preview_url, fallback_image_url, voice_profile, growth_notes,
                reason, change_type, change_notes_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                persona_id,
                1,
                persona["name"],
                persona["summary"],
                persona["prompt"],
                json.dumps(persona["traits"], ensure_ascii=False),
                persona["relationship"],
                persona["speaking_style"],
                json.dumps(persona["boundaries"], ensure_ascii=False),
                json.dumps(persona.get("psychological_profile", {}), ensure_ascii=False),
                persona.get("psychological_fit_notes", ""),
                persona.get("appearance_description", ""),
                persona.get("desired_image", ""),
                persona.get("live2d_model_id", ""),
                persona.get("live2d_preview_url", ""),
                persona.get("fallback_image_url", ""),
                persona.get("voice_profile", ""),
                persona.get("growth_notes", ""),
                "self-use default companion",
                "self_use_default",
                json.dumps(["自用模式默认创建澪陪伴体"], ensure_ascii=False),
                ts,
            ),
        )
        row = db.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
        _set_self_use_companion_binding(db, user_id, persona_id)
        return dict_from_row(row)


def _clear_generated_self_use_profile(user_id: int) -> None:
    with get_db() as db:
        row = db.execute("SELECT nickname FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
        if row and str(row["nickname"] or "").strip() == "澪的工作区":
            db.execute(
                "UPDATE user_profiles SET nickname = '', updated_at = ? WHERE user_id = ?",
                (now_ts(), user_id),
            )


@app.post("/api/auth/local")
def local_login(request: Request, response: Response):
    config = _self_use_config()
    if not config.get("enabled", False):
        raise HTTPException(status_code=404, detail="local self-use mode is not enabled")
    if bool(config.get("require_localhost", True)) and not _is_local_request(request):
        raise HTTPException(status_code=403, detail="local self-use mode only accepts localhost requests")

    user = get_or_create_local_user(
        username=str(config.get("username") or "mio_owner"),
        nickname=str(config.get("nickname") or ""),
    )
    _clear_generated_self_use_profile(int(user["id"]))
    _ensure_self_use_default_persona(int(user["id"]), config)
    return _start_authenticated_session(response, user)


@app.post("/api/auth/register")
def register(req: RegisterRequest, response: Response):
    _reject_legacy_auth_in_self_use()
    user = create_user(req.username, req.password, req.nickname)
    return _start_authenticated_session(response, user, tab_session=req.tab_session)


@app.post("/api/auth/login")
def login(req: LoginRequest, response: Response):
    _reject_legacy_auth_in_self_use()
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="invalid username or password")

    return _start_authenticated_session(response, user, tab_session=req.tab_session)


@app.post("/api/auth/guest")
def guest_login(response: Response, tab_session: bool = False):
    _reject_legacy_auth_in_self_use()
    user = create_guest_user()
    return _start_authenticated_session(response, user, tab_session=tab_session, max_age=GUEST_SECONDS)


@app.post("/api/auth/guest/convert")
def convert_guest(req: GuestConvertRequest, response: Response, user: dict = Depends(current_user)):
    _reject_legacy_auth_in_self_use()
    converted = convert_guest_user(
        user_id=int(user["id"]),
        username=req.username,
        password=req.password,
        nickname=req.nickname,
    )
    return _start_authenticated_session(response, converted, tab_session=req.tab_session)


@app.post("/api/auth/logout")
def logout(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    authorization: str | None = Header(default=None),
):
    clear_session(response, request_session_token(session_token, authorization))
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return {"user": public_user(user), "profile": _get_profile(int(user["id"])), "self_use": _self_use_public(user)}


@app.get("/api/profile")
def profile(user: dict = Depends(current_user)):
    return {"profile": _get_profile(int(user["id"]))}


@app.get("/api/account/export")
def account_export(user: dict = Depends(current_user)):
    return export_user_data(int(user["id"]))


@app.post("/api/account/delete")
def account_delete(req: AccountDeleteRequest, response: Response, user: dict = Depends(current_user)):
    if _self_use_public(user).get("enabled"):
        raise HTTPException(status_code=403, detail="LING local owner data is managed through export and backup, not account deletion")
    result = delete_user_account(
        user_id=int(user["id"]),
        confirm_username=req.confirm_username,
        password=req.password,
    )
    clear_session(response)
    return result


@app.put("/api/profile")
def update_profile(req: ProfileUpdateRequest, user: dict = Depends(current_user)):
    if _self_use_public(user).get("enabled") and req.avatar_url is not None:
        raise HTTPException(status_code=400, detail="LING self-use mode does not use owner avatar fields")
    user_id = int(user["id"])
    current = _get_profile(user_id)
    preferences = req.preferences if req.preferences is not None else current.get("preferences", {})
    timezone_name = _clean_timezone(req.timezone) if req.timezone is not None else current.get("timezone", "")
    avatar_url = _clean_avatar_url(req.avatar_url) if req.avatar_url is not None else current.get("avatar_url")
    ts = now_ts()

    with get_db() as db:
        db.execute(
            """
            UPDATE user_profiles
            SET nickname = ?, avatar_url = ?, gender = ?, birthday = ?, timezone = ?, signature = ?, bio = ?,
                preferences_json = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (
                req.nickname if req.nickname is not None else current.get("nickname"),
                avatar_url,
                req.gender if req.gender is not None else current.get("gender"),
                req.birthday if req.birthday is not None else current.get("birthday"),
                timezone_name,
                req.signature if req.signature is not None else current.get("signature"),
                req.bio if req.bio is not None else current.get("bio"),
                json.dumps(preferences, ensure_ascii=False),
                ts,
                user_id,
            ),
        )

    return {"profile": _get_profile(user_id)}


def _clean_timezone(value: str | None) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    try:
        ZoneInfo(cleaned)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=400, detail="invalid timezone") from exc
    return cleaned


def _clean_avatar_url(value: str | None) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    if any(ch.isspace() for ch in cleaned):
        raise HTTPException(status_code=400, detail="invalid avatar url")
    if cleaned.startswith("/uploads/"):
        return cleaned
    parsed = urlparse(cleaned)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return cleaned
    raise HTTPException(status_code=400, detail="invalid avatar url")


def _clean_visual_asset_url(value: str | None, field_name: str) -> str:
    try:
        return _clean_avatar_url(value)
    except HTTPException as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"invalid {field_name}") from exc


@app.get("/api/persona-options")
def persona_options():
    return {"options": PERSONA_OPTIONS, "max_per_group": 4}


@app.get("/api/expression-assets")
def expression_assets(user: dict = Depends(current_user)):
    return {"assets": expression_assets_public()}


@app.get("/api/admin/expression-assets")
def admin_expression_assets(admin: dict = Depends(current_admin)):
    return {"assets": expression_assets_public(include_disabled=True, include_admin_metadata=True)}


@app.patch("/api/admin/expression-assets/{expression_type}/{label}")
def admin_update_expression_asset(
    expression_type: str,
    label: str,
    req: ExpressionAssetUpdateRequest,
    admin: dict = Depends(current_admin),
):
    try:
        asset = update_expression_asset_setting(
            expression_type,
            label,
            enabled=req.enabled,
            cooldown_turns=req.cooldown_turns,
            admin_note=req.admin_note or "",
            updated_by_user_id=int(admin["id"]),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "asset": asset,
        "assets": expression_assets_public(include_disabled=True, include_admin_metadata=True),
    }


@app.post("/api/uploads/avatar")
async def upload_avatar(file: UploadFile = File(...), user: dict = Depends(current_user)):
    if _self_use_public(user).get("enabled"):
        raise HTTPException(status_code=404, detail="LING self-use mode uses embodiment preview/fallback uploads")
    content_type, data = await _read_uploaded_image(file)
    user_dir = UPLOAD_DIR / str(user["id"])
    user_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{AVATAR_CONTENT_TYPES[content_type]}"
    path = user_dir / filename
    path.write_bytes(data)
    return {"url": f"/uploads/{user['id']}/{filename}"}


@app.post("/api/uploads/embodiment-image")
async def upload_embodiment_image(
    request: Request,
    file: UploadFile = File(...),
    kind: str = "fallback",
    user: dict = Depends(current_user),
):
    if not _self_use_public(user).get("enabled"):
        raise HTTPException(status_code=404, detail="LING embodiment upload is only available in self-use mode")
    config = _self_use_config()
    if bool(config.get("require_localhost", True)) and not _is_local_request(request):
        raise HTTPException(status_code=403, detail="LING embodiment upload only accepts localhost requests")

    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind not in EMBODIMENT_IMAGE_KINDS:
        raise HTTPException(status_code=400, detail="kind must be preview or fallback")

    content_type, data = await _read_uploaded_image(file)
    user_dir = UPLOAD_DIR / str(user["id"]) / "embodiment" / normalized_kind
    user_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{AVATAR_CONTENT_TYPES[content_type]}"
    path = user_dir / filename
    path.write_bytes(data)
    return {
        "url": f"/uploads/{user['id']}/embodiment/{normalized_kind}/{filename}",
        "kind": normalized_kind,
    }


async def _read_uploaded_image(file: UploadFile) -> tuple[str, bytes]:
    content_type = (file.content_type or "").lower()
    if content_type not in AVATAR_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="only jpg, png, webp or gif images are allowed")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    if len(data) > AVATAR_MAX_BYTES:
        raise HTTPException(status_code=400, detail="image must be smaller than 5MB")
    if not _avatar_header_matches(content_type, data):
        raise HTTPException(status_code=400, detail="image content does not match its declared type")
    return content_type, data


def _avatar_header_matches(content_type: str, data: bytes) -> bool:
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if content_type == "image/gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    return False


@app.get("/api/voice/config")
def voice_config(user: dict = Depends(current_user)):
    config = load_voice_config()
    health = tts_health_check()
    safe = {
        "enabled": bool(config.get("enabled", False)),
        "auto_play": bool(config.get("auto_play", True)),
        "tts_provider": config.get("tts_provider", "openai_tts"),
        "tts_model": config.get("tts_model") or config.get("model") or "",
        "api_key_env": config.get("api_key_env") or "OPENAI_API_KEY",
        "voice_id": config.get("voice_id", ""),
        "response_format": config.get("response_format", "mp3"),
        "instructions": config.get("instructions", ""),
        "rate": config.get("rate", 1.0),
        "pitch": config.get("pitch", 1.0),
        "split_long_replies": bool(config.get("split_long_replies", True)),
        "max_chunk_length": config.get("max_chunk_length", 80),
        "available": bool(health.get("available")),
        "error": health.get("error"),
    }
    return {"voice": safe}


@app.get("/api/voice/health")
def voice_health(user: dict = Depends(current_user)):
    return tts_health_check()


class VoiceTTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice_id: str | None = Field(default=None, max_length=80)
    rate: float | None = None
    pitch: float | None = None
    expression_labels: list[str] | None = None


class VoiceTTSReplyRequest(BaseModel):
    reply_text: str = Field(..., min_length=1, max_length=2000)
    expression_labels: list[str] | None = None
    persona_id: int | None = None


def _non_empty_voice_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="语音文本不能为空")
    return cleaned


def _voice_response_format() -> str:
    return str(load_voice_config().get("response_format") or "mp3").strip().lower()


def _voice_media_type() -> str:
    return {
        "mp3": "audio/mpeg",
        "opus": "audio/ogg",
        "aac": "audio/aac",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "pcm": "application/octet-stream",
    }.get(_voice_response_format(), "application/octet-stream")


def _voice_profile_for_request(user: dict[str, Any], persona_id: int | None) -> str | None:
    if bool(_self_use_public(user).get("enabled")):
        persona = _companion_status_persona(user, persona_id)
    elif persona_id is not None:
        with get_db() as db:
            row = db.execute(
                "SELECT * FROM personas WHERE id = ? AND user_id = ? AND status = 'active'",
                (int(persona_id), int(user["id"])),
            ).fetchone()
        persona = _public_persona(dict_from_row(row))
    else:
        persona = None
    voice_profile = str((persona or {}).get("voice_profile") or "").strip()
    return voice_profile or None


@app.post("/api/voice/tts")
def voice_tts(req: VoiceTTSRequest, user: dict = Depends(current_user)):
    text = _non_empty_voice_text(req.text)
    if not voice_enabled():
        raise HTTPException(status_code=400, detail="语音功能已在配置中关闭。如需使用请在 config.yaml 中设置 voice.enabled: true")
    audio = generate_tts_audio(
        text=text,
        voice_id=req.voice_id,
        rate=req.rate if req.rate is not None else 1.0,
        pitch=req.pitch if req.pitch is not None else 1.0,
    )
    if audio is None:
        error = get_last_tts_error() or "unknown error"
        raise HTTPException(
            status_code=503,
            detail=f"语音生成失败：{error}。请检查主程序的 OpenAI TTS 配置；实时视频语音会话仍由 Video Companion 负责。",
        )
    return Response(content=audio, media_type=_voice_media_type())


@app.post("/api/voice/tts-reply")
def voice_tts_reply(req: VoiceTTSReplyRequest, user: dict = Depends(current_user)):
    reply_text = _non_empty_voice_text(req.reply_text)
    if not voice_enabled():
        raise HTTPException(status_code=400, detail="语音功能已在配置中关闭。如需使用请在 config.yaml 中设置 voice.enabled: true")
    if _voice_response_format() != "mp3":
        raise HTTPException(status_code=400, detail="LING 整段回复朗读当前只支持 MP3；请在 Voice 设置中选择 mp3")

    voice_profile = _voice_profile_for_request(user, req.persona_id)
    started = time.perf_counter()
    result = generate_tts_reply_audio(reply_text, req.expression_labels, voice_id=voice_profile)

    if result["audio"] is None or not result["success"]:
        failed_count = sum(1 for c in result.get("chunks", []) if not c["audio_available"])
        failed_errors = [str(c.get("error")) for c in result.get("chunks", []) if c.get("error")]
        error_hint = failed_errors[0] if failed_errors else (result.get("error") or "unknown error")
        raise HTTPException(
            status_code=503,
            detail=f"语音生成部分失败：{failed_count}/{len(result.get('chunks',[]))} 句未生成。原因：{error_hint}",
        )

    return Response(
        content=result["audio"],
        media_type="audio/mpeg",
        headers={"X-LING-TTS-Generation-Ms": str(elapsed_ms(started))},
    )


@app.post("/api/voice/tts-stream")
def voice_tts_stream(req: VoiceTTSReplyRequest, user: dict = Depends(current_user)):
    """Return local GPT-SoVITS PCM WAV chunks without waiting for a complete MP3."""
    reply_text = _non_empty_voice_text(req.reply_text)
    if not voice_enabled():
        raise HTTPException(status_code=400, detail="语音功能已在配置中关闭。")
    voice_config = load_voice_config()
    provider = str(voice_config.get("tts_provider") or "").strip().lower()
    if provider != "local_http":
        raise HTTPException(status_code=400, detail="实时语音流仅支持本机 local_http 语音服务。")

    request_id = uuid.uuid4().hex
    voice_profile = _voice_profile_for_request(user, req.persona_id)
    try:
        chunks = stream_local_http_tts_wav(
            reply_text,
            voice_id=voice_profile,
            request_id=request_id,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"本机流式语音启动失败：{exc}") from exc

    return StreamingResponse(
        chunks,
        media_type="audio/wav",
        headers={
            "X-LING-TTS-Stream": "pcm-wav",
            "X-Request-ID": request_id,
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/voice/tts-chunk/{chunk_index}")
def voice_tts_chunk(chunk_index: int, req: VoiceTTSReplyRequest, user: dict = Depends(current_user)):
    reply_text = _non_empty_voice_text(req.reply_text)
    if not voice_enabled():
        raise HTTPException(status_code=400, detail="语音功能已在配置中关闭。")

    voice_profile = _voice_profile_for_request(user, req.persona_id)
    started = time.perf_counter()
    audio, metadata = generate_tts_single_chunk(
        reply_text,
        chunk_index,
        req.expression_labels,
        voice_id=voice_profile,
    )

    if audio is None:
        error = str(metadata.get("error") or "")
        status_code = 400 if "chunk_index" in error and "out of range" in error else 503
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": "chunk generation failed",
                "metadata": metadata,
            },
        )

    return Response(
        content=audio,
        media_type=_voice_media_type(),
        headers={"X-LING-TTS-Generation-Ms": str(elapsed_ms(started))},
    )


@app.post("/api/voice/speech-plan")
def voice_speech_plan(req: VoiceTTSReplyRequest, user: dict = Depends(current_user)):
    reply_text = _non_empty_voice_text(req.reply_text)
    utterances = split_reply_into_utterances(reply_text)
    params = build_tts_request_params(utterances, req.expression_labels)
    styles = [str(param.get("style")) for param in params if param.get("style")]
    return {
        "utterances": utterances,
        "tts_params": params,
        "chunk_count": len(utterances),
        "styles": styles,
        "expression_labels": [str(label) for label in (req.expression_labels or []) if str(label).strip()],
    }


@app.get("/api/live2d/config")
def live2d_config(user: dict = Depends(current_user)):
    config = load_live2d_config()
    safe = {
        "enabled": config.get("enabled", False),
        "vts_plugin_name": config.get("vts_plugin_name", ""),
        "expression_map": config.get("expression_map", {}),
    }
    return {"live2d": safe}


@app.get("/api/live2d/status")
def live2d_status(user: dict = Depends(current_user)):
    return live2d_connection_status()


@app.post("/api/live2d/refresh")
def live2d_refresh(user: dict = Depends(current_user)):
    if not live2d_enabled():
        raise HTTPException(status_code=400, detail="live2d is disabled in config")
    from .embodiment import get_live2d_connection

    connection = get_live2d_connection()
    if not connection.is_connected or not connection.is_authenticated:
        raise HTTPException(status_code=409, detail="connect VTube Studio before refreshing model capabilities")
    refreshed = connection.refresh_capabilities()
    status = live2d_connection_status()
    if not refreshed:
        raise HTTPException(status_code=503, detail=status.get("last_error") or "VTube Studio capability refresh failed")
    return {"refreshed": True, "status": status}


@app.get("/api/live2d/expression-mappings")
def live2d_expression_mappings(user: dict = Depends(current_user)):
    if not live2d_enabled():
        return {"mappings": [], "enabled": False}
    categories = get_expression_categories()
    return {"mappings": categories, "enabled": True}


class Live2DExpressionRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=40)
    expression_type: str = Field(default="mood", max_length=40)


class Live2DRuntimeStateRequest(BaseModel):
    state: str = Field(..., min_length=1, max_length=40)


class Live2DLipSyncRequest(BaseModel):
    value: float = Field(..., ge=0.0, le=1.0)


@app.post("/api/live2d/apply-expression")
def live2d_apply_expression(req: Live2DExpressionRequest, user: dict = Depends(current_user)):
    if not live2d_enabled():
        raise HTTPException(status_code=400, detail="live2d is disabled in config")
    _require_self_use_live2d_ready(user)
    result = apply_expression_to_live2d(req.label, req.expression_type)
    return result


@app.post("/api/live2d/apply-runtime-state")
def live2d_apply_runtime_state(req: Live2DRuntimeStateRequest, user: dict = Depends(current_user)):
    if not live2d_enabled():
        raise HTTPException(status_code=400, detail="live2d is disabled in config")
    _require_self_use_live2d_ready(user)
    return apply_runtime_state_to_live2d(req.state)


@app.post("/api/live2d/lip-sync")
def live2d_lip_sync(req: Live2DLipSyncRequest, user: dict = Depends(current_user)):
    config = load_live2d_config()
    if not bool(config.get("enabled", False)):
        raise HTTPException(status_code=400, detail="live2d is disabled in config")
    if not bool(config.get("lip_sync_enabled", True)):
        return {"applied": False, "reason": "lip_sync_disabled"}
    _require_self_use_live2d_ready(user)

    from .embodiment import get_live2d_connection

    connection = get_live2d_connection()
    parameter = str(config.get("lip_sync_parameter") or "MouthOpen").strip()
    available = {
        str(item.get("name") or "").strip().casefold()
        for item in connection.get_connection_status().get("available_parameters", [])
        if isinstance(item, dict)
    }
    if parameter.casefold() not in available:
        return {
            "applied": False,
            "reason": "parameter_unavailable",
            "parameter": parameter,
        }
    applied = connection.inject_parameter(parameter, req.value)
    if not applied and not connection.is_connected:
        start_live2d_autoconnect()
    return {
        "applied": applied,
        "reason": None if applied else "injection_failed",
        "parameter": parameter,
        "value": req.value,
    }


@app.post("/api/live2d/connect")
def live2d_connect(user: dict = Depends(current_user)):
    if not live2d_enabled():
        raise HTTPException(status_code=400, detail="live2d is disabled in config")
    start_live2d_autoconnect(force=True)
    status = live2d_connection_status()
    return {"connected": bool(status.get("connected")), "connecting": bool(status.get("connecting")), "status": status}


@app.post("/api/live2d/disconnect")
def live2d_disconnect(user: dict = Depends(current_user)):
    if not live2d_enabled():
        raise HTTPException(status_code=400, detail="live2d is disabled in config")
    status = stop_live2d_connection(pause_autoconnect=True)
    return {"connected": False, "connecting": False, "status": status}


@app.get("/api/presence/state")
def presence_state(user: dict = Depends(current_user)):
    _sync_self_use_presence_quiet(user)
    return get_presence_summary(int(user["id"]))


@app.post("/api/presence/user-message")
def presence_user_message(user: dict = Depends(current_user)):
    if not presence_enabled():
        return {"transition": "disabled"}
    return on_user_message(int(user["id"]))


@app.post("/api/presence/reply-start")
def presence_reply_start(user: dict = Depends(current_user)):
    if not presence_enabled():
        return {"transition": "disabled"}
    return on_reply_start(int(user["id"]))


@app.post("/api/presence/reply-end")
def presence_reply_end(user: dict = Depends(current_user)):
    if not presence_enabled():
        return {"transition": "disabled"}
    return on_reply_end(int(user["id"]))


@app.post("/api/presence/idle")
def presence_idle(user: dict = Depends(current_user)):
    if not presence_enabled():
        return {"transition": "disabled"}
    return on_idle(int(user["id"]))


@app.post("/api/presence/quiet-mode")
def presence_quiet_mode(user: dict = Depends(current_user)):
    if not presence_enabled():
        return {"transition": "disabled"}
    result = on_quiet_mode_enter(int(user["id"]))
    _sync_self_use_presence_quiet(user, True)
    return result


@app.post("/api/presence/normal-mode")
def presence_normal_mode(user: dict = Depends(current_user)):
    if not presence_enabled():
        return {"transition": "disabled"}
    result = on_quiet_mode_exit(int(user["id"]))
    _sync_self_use_presence_quiet(user, False)
    return result


def _sync_self_use_presence_quiet(user: dict[str, Any], quiet: bool | None = None) -> None:
    if not _self_use_public(user).get("enabled"):
        return
    persona_id = _self_use_bound_persona_id(user)
    if persona_id is None:
        return
    controller = get_proactive_controller(int(user["id"]), int(persona_id))
    effective_quiet = controller.is_quiet if quiet is None else bool(quiet)
    if quiet is not None and controller.is_quiet != effective_quiet:
        controller.set_quiet_mode(effective_quiet)
    get_runtime_state(int(user["id"])).set_quiet_mode(effective_quiet)


class PresenceQuietCheckRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)


@app.post("/api/presence/check-quiet")
def presence_check_quiet(req: PresenceQuietCheckRequest, user: dict = Depends(current_user)):
    return {"should_enter_quiet": detect_quiet_mode_request(req.text)}


@app.get("/api/camera/config")
def camera_config(user: dict = Depends(current_user)):
    _reject_self_use_internal_camera(user)
    return {"camera": get_camera_config()}


@app.get("/api/camera/status")
def camera_status(user: dict = Depends(current_user)):
    _reject_self_use_internal_camera(user)
    return get_camera_status(int(user["id"]))


@app.get("/api/camera/stream")
def camera_stream(user: dict = Depends(current_user)):
    _reject_self_use_internal_camera(user)
    user_id = int(user["id"])
    if not camera_enabled(user_id):
        raise HTTPException(status_code=400, detail="camera is disabled or not authorized")

    status = get_camera_status(user_id)
    if not status.get("stream", {}).get("available"):
        error = (status.get("system") or {}).get("error") or "camera stream is not available"
        raise HTTPException(status_code=503, detail=error)

    return StreamingResponse(
        iter_camera_mjpeg(user_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/perception/summary")
def perception_summary(user: dict = Depends(current_user)):
    _reject_self_use_internal_camera(user)
    return get_perception_summary(int(user["id"]))


@app.post("/api/perception/cycle")
def perception_cycle(user: dict = Depends(current_user)):
    _reject_self_use_internal_camera(user)
    return run_perception_cycle(int(user["id"]))


@app.get("/api/world-state/observations")
def world_observations(
    user: dict = Depends(current_user),
    source: str | None = None,
    observation_type: str | None = None,
    limit: int = 20,
):
    return {
        "observations": get_recent_world_observations(
            int(user["id"]),
            source=source,
            observation_type=observation_type,
            limit=limit,
        )
    }


@app.get("/api/world-state/summary")
def world_state_summary(user: dict = Depends(current_user)):
    return get_world_state_summary(int(user["id"]))


@app.get("/api/screen/config")
def screen_config(user: dict = Depends(current_user)):
    return {"screen": get_screen_config()}


@app.get("/api/screen/status")
def screen_status(user: dict = Depends(current_user)):
    return get_screen_perception_status(int(user["id"]))


@app.post("/api/screen/perception-cycle")
def screen_perception_cycle(user: dict = Depends(current_user)):
    return run_screen_perception_cycle(int(user["id"]))


class VideoCompanionSessionRequest(BaseModel):
    persona_id: int | str | None = None


@app.get("/api/video-companion/config")
def video_companion_config(user: dict = Depends(current_user)):
    return {"video_companion": public_video_companion_config()}


@app.get("/api/easyvtuber/status")
def easyvtuber_runtime_status(user: dict = Depends(current_user)):
    if not _self_use_public(user).get("enabled"):
        raise HTTPException(status_code=404, detail="EasyVtuber control is only available in LING self-use mode")
    return {"easyvtuber": easyvtuber_status()}


@app.post("/api/easyvtuber/open")
def easyvtuber_open(request: Request, user: dict = Depends(current_user)):
    _require_self_use_local_config_change(request, user)
    try:
        return open_easyvtuber()
    except EasyVtuberError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/video-companion/status")
def video_companion_status(user: dict = Depends(current_user)):
    return _video_companion_status_for_user(int(user["id"]))


@app.post("/api/video-companion/session/start")
def video_companion_start(req: VideoCompanionSessionRequest, user: dict = Depends(current_user)):
    persona_id = req.persona_id
    if _self_use_public(user).get("enabled"):
        bound_id = _self_use_bound_persona_id(user)
        if bound_id is None:
            raise HTTPException(status_code=503, detail="LING companion binding is unavailable")
        if persona_id is not None:
            try:
                requested_id = int(str(persona_id).strip())
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="invalid companion id") from exc
            if requested_id != bound_id:
                raise HTTPException(status_code=404, detail="companion not found in LING self-use mode")
        persona_id = bound_id
    try:
        return start_video_companion_session(persona_id)
    except VideoCompanionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/video-companion/session/stop")
def video_companion_stop(user: dict = Depends(current_user)):
    try:
        result = stop_video_companion_session()
    except VideoCompanionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    stop_result = result.get("result") if isinstance(result.get("result"), dict) else {}
    summary = stop_result.get("summary") if isinstance(stop_result, dict) else None
    if isinstance(summary, dict):
        consent = stop_result.get("consent") if isinstance(stop_result, dict) else None
        if isinstance(consent, dict) and not bool(consent.get("save_summary")):
            result["mnemosyne_save"] = {"saved": False, "reason": "save_summary_not_granted"}
        else:
            summary_payload = dict(summary)
            bound_id = _self_use_bound_persona_id(user)
            if bound_id is not None:
                summary_payload["persona_id"] = bound_id
            result["mnemosyne_save"] = save_video_session_summary(
                summary_payload,
                fallback_user_id=int(user["id"]),
            )
    return result


def _require_video_bridge_auth(request: Request, authorization: str | None = Header(default=None)) -> None:
    expected = (
        os.environ.get("LING_VIDEO_BRIDGE_API_KEY", "").strip()
        or os.environ.get("MNEMOSYNE_API_KEY", "").strip()
    )
    if not expected:
        if _is_local_request(request):
            return
        raise HTTPException(status_code=403, detail="tokenless video bridge callbacks are localhost-only")
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="video bridge authorization required")
    token = authorization[len(prefix):].strip()
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="invalid video bridge token")


def _require_self_use_video_persona(persona_id: int | str | None) -> None:
    config = _self_use_config()
    if not bool(config.get("enabled", False)):
        return
    username = str(config.get("username") or "mio_owner")
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE username = ? AND status = 'active'", (username,)).fetchone()
    user = dict_from_row(row)
    if not user:
        raise HTTPException(status_code=503, detail="LING self-use owner is unavailable")
    bound_id = _self_use_bound_persona_id(user)
    if bound_id is None:
        raise HTTPException(status_code=503, detail="LING companion binding is unavailable")
    try:
        requested_id = int(str(persona_id or "").strip())
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="video bridge callback requires the bound LING companion id") from exc
    if requested_id != bound_id:
        raise HTTPException(status_code=404, detail="companion not found in LING self-use mode")


@app.get("/api/video/session-context")
def video_session_context(persona_id: int | str | None = None, auth: None = Depends(_require_video_bridge_auth)):
    _require_self_use_video_persona(persona_id)
    return build_video_session_context(persona_id)


@app.post("/api/video/session-summary")
def video_session_summary(payload: dict[str, Any], auth: None = Depends(_require_video_bridge_auth)):
    _require_self_use_video_persona(payload.get("persona_id"))
    return save_video_session_summary(payload)


@app.post("/api/video/observation")
def video_observation(payload: dict[str, Any], auth: None = Depends(_require_video_bridge_auth)):
    _require_self_use_video_persona(payload.get("persona_id"))
    return save_video_observation(payload)


@app.post("/api/video/consent")
def video_consent(payload: dict[str, Any], auth: None = Depends(_require_video_bridge_auth)):
    _require_self_use_video_persona(payload.get("persona_id"))
    return sync_video_consent(payload)


@app.post("/api/video/turn")
def video_turn(payload: dict[str, Any], auth: None = Depends(_require_video_bridge_auth)):
    _require_self_use_video_persona(payload.get("persona_id"))
    return build_video_turn_response(payload)


@app.get("/api/proactive/status")
def proactive_status(user: dict = Depends(current_user), persona_id: int | None = None):
    user_id = int(user["id"])
    pid = _resolve_self_use_proactive_persona(user, persona_id)
    if pid is None:
        with get_db() as db:
            row = db.execute(
                "SELECT id FROM personas WHERE user_id = ? AND status = 'active' ORDER BY updated_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if row:
                pid = int(row["id"])
    if pid is None:
        return {"enabled": proactive_enabled(user_id), "persona_required": True}
    _require_active_persona_for_user(pid, user_id)
    return get_proactive_status(user_id, pid)


@app.get("/api/proactive/scheduler")
def proactive_scheduler_status(user: dict = Depends(current_user)):
    return get_proactive_scheduler_status()


class ProactiveCheckRequest(BaseModel):
    persona_id: int


class ProactiveTickRequest(BaseModel):
    persona_id: int | None = None
    dry_run: bool = False


def _require_active_persona_for_user(persona_id: int, user_id: int) -> None:
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM personas WHERE id = ? AND user_id = ? AND status = 'active'",
            (persona_id, user_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="persona not found")


def _resolve_self_use_proactive_persona(user: dict[str, Any], persona_id: int | None) -> int | None:
    if not _self_use_public(user).get("enabled"):
        return persona_id
    bound_id = _self_use_bound_persona_id(user)
    if bound_id is None:
        raise HTTPException(status_code=404, detail="companion not found in LING self-use mode")
    if persona_id is not None and int(persona_id) != int(bound_id):
        raise HTTPException(status_code=404, detail="companion not found in LING self-use mode")
    return int(bound_id)


@app.post("/api/proactive/can-send")
def proactive_can_send(req: ProactiveCheckRequest, user: dict = Depends(current_user)):
    user_id = int(user["id"])
    persona_id = _resolve_self_use_proactive_persona(user, req.persona_id)
    assert persona_id is not None
    if not proactive_enabled(user_id):
        return {"allowed": False, "reason": "proactive_disabled"}
    _require_active_persona_for_user(persona_id, user_id)
    controller = get_proactive_controller(user_id, persona_id)
    return controller.can_send_proactive()


@app.post("/api/proactive/on-sent")
def proactive_on_sent(req: ProactiveCheckRequest, user: dict = Depends(current_user)):
    user_id = int(user["id"])
    persona_id = _resolve_self_use_proactive_persona(user, req.persona_id)
    assert persona_id is not None
    if not proactive_enabled(user_id):
        raise HTTPException(status_code=400, detail="proactive is disabled")
    _require_active_persona_for_user(persona_id, user_id)
    controller = get_proactive_controller(user_id, persona_id)
    try:
        controller.on_proactive_sent()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return controller.get_status()


class ProactiveFeedbackRequest(BaseModel):
    persona_id: int
    positive: bool


@app.post("/api/proactive/feedback")
def proactive_feedback(req: ProactiveFeedbackRequest, user: dict = Depends(current_user)):
    user_id = int(user["id"])
    persona_id = _resolve_self_use_proactive_persona(user, req.persona_id)
    assert persona_id is not None
    if not proactive_enabled(user_id):
        raise HTTPException(status_code=400, detail="proactive is disabled")
    _require_active_persona_for_user(persona_id, user_id)
    controller = get_proactive_controller(user_id, persona_id)
    controller.record_user_feedback(req.positive)
    return controller.get_status()


class ProactiveQuietRequest(BaseModel):
    persona_id: int
    quiet: bool


@app.post("/api/proactive/quiet-mode")
def proactive_quiet_mode(req: ProactiveQuietRequest, user: dict = Depends(current_user)):
    user_id = int(user["id"])
    persona_id = _resolve_self_use_proactive_persona(user, req.persona_id)
    assert persona_id is not None
    if not proactive_enabled(user_id):
        raise HTTPException(status_code=400, detail="proactive is disabled")
    _require_active_persona_for_user(persona_id, user_id)
    controller = get_proactive_controller(user_id, persona_id)
    controller.set_quiet_mode(req.quiet)
    if _self_use_public(user).get("enabled"):
        get_runtime_state(user_id).set_quiet_mode(req.quiet)
    return controller.get_status()


@app.post("/api/proactive/check-quiet")
def proactive_check_quiet(req: PresenceQuietCheckRequest, user: dict = Depends(current_user)):
    return {"should_enter_quiet": proactive_detect_quiet(req.text)}


@app.post("/api/proactive/tick")
def proactive_tick(req: ProactiveTickRequest, user: dict = Depends(current_user)):
    user_id = int(user["id"])
    persona_id = _resolve_self_use_proactive_persona(user, req.persona_id)
    if not proactive_enabled(user_id):
        return {"enabled": False, "sent": 0, "skipped": [{"reason": "proactive_disabled"}]}
    if persona_id is not None:
        _require_active_persona_for_user(persona_id, user_id)
    return run_proactive_tick(user_id=user_id, persona_id=persona_id, dry_run=req.dry_run)


class ConsentUpdateRequest(BaseModel):
    consent_key: str = Field(..., min_length=1, max_length=40)


@app.get("/api/consents")
def user_consents(user: dict = Depends(current_user)):
    return {"consents": get_all_consents(int(user["id"]))}


@app.post("/api/consents/grant")
def consent_grant(req: ConsentUpdateRequest, user: dict = Depends(current_user)):
    if req.consent_key not in CONSENT_KEYS:
        raise HTTPException(status_code=400, detail=f"unknown consent key: {req.consent_key}")
    return {"consent": grant_consent(int(user["id"]), req.consent_key)}


@app.post("/api/consents/revoke")
def consent_revoke(req: ConsentUpdateRequest, user: dict = Depends(current_user)):
    if req.consent_key not in CONSENT_KEYS:
        raise HTTPException(status_code=400, detail=f"unknown consent key: {req.consent_key}")
    return {"consent": revoke_consent(int(user["id"]), req.consent_key)}


@app.get("/api/memories")
def memories(user: dict = Depends(current_user), persona_id: int | None = None, q: str = ""):
    return {"memories": recall_memories(int(user["id"]), persona_id, q, limit=50)}


@app.get("/api/memory/layered")
def layered_memories(
    user: dict = Depends(current_user),
    persona_id: int | None = None,
    q: str = "",
    include_history: bool = False,
):
    return {"memory": recall_layered_memory(int(user["id"]), persona_id, q, limit=50, include_history=include_history)}


@app.post("/api/memory/summaries/refresh")
def refresh_summaries(user: dict = Depends(current_user), persona_id: int | None = None):
    return {"summaries": refresh_memory_summaries(int(user["id"]), persona_id)}


@app.post("/api/memory/state/refresh")
def refresh_state(user: dict = Depends(current_user), persona_id: int | None = None):
    return {"state": refresh_memory_state(int(user["id"]), persona_id)}


@app.post("/api/memory/decay/apply")
def apply_decay(user: dict = Depends(current_user), persona_id: int | None = None):
    return {"decay": apply_memory_decay(int(user["id"]), persona_id)}


@app.get("/api/admin/memory/links")
def admin_memory_links(
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
    uid: str | None = None,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    query = "SELECT * FROM memory_links WHERE user_id = ?"
    params: list[Any] = [owner_id]
    if uid:
        query += " AND (from_uid = ? OR to_uid = ?)"
        params.extend([uid, uid])
    query += " ORDER BY id ASC"
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return {"links": [dict_from_row(row) for row in rows]}


@app.get("/api/admin/chat-context-traces")
def admin_context_traces(
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
    persona_id: int | None = None,
    limit: int = 10,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    _assert_persona_owner(owner_id, persona_id)
    return {"traces": context_traces(owner_id, persona_id, limit)}


@app.get("/api/admin/expression-usage")
def admin_expression_usage(
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
    persona_id: int | None = None,
    limit: int = 12,
    usage_limit: int = 80,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    _assert_persona_owner(owner_id, persona_id)
    limit = max(1, min(int(limit or 12), 50))
    usage_limit = max(limit, min(int(usage_limit or 80), 500))
    persona_filter = int(persona_id) if persona_id else None
    params: list[Any] = [owner_id]
    persona_clause = ""
    if persona_filter:
        persona_clause = "AND message_expressions.persona_id = ?"
        params.append(persona_filter)
    params.append(usage_limit)
    with get_db() as db:
        preference_row = None
        if persona_filter:
            preference_row = db.execute(
                """
                SELECT enabled, mode, source_message_id, updated_at
                FROM expression_preferences
                WHERE user_id = ? AND persona_id = ?
                """,
                (owner_id, persona_filter),
            ).fetchone()
        single_rows = db.execute(
            f"""
            SELECT message_expressions.*, messages.content, messages.created_at AS message_created_at,
                   conversations.title AS conversation_title,
                   personas.name AS persona_name,
                   'single' AS scope
            FROM message_expressions
            JOIN messages ON messages.id = message_expressions.message_id
            JOIN conversations ON conversations.id = message_expressions.conversation_id
            JOIN personas ON personas.id = message_expressions.persona_id
            WHERE message_expressions.user_id = ?
              {persona_clause}
            ORDER BY message_expressions.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        group_params: list[Any] = [owner_id]
        group_persona_clause = ""
        if persona_filter:
            group_persona_clause = "AND group_message_expressions.persona_id = ?"
            group_params.append(persona_filter)
        group_params.append(usage_limit)
        group_rows = db.execute(
            f"""
            SELECT group_message_expressions.*, group_messages.content,
                   group_messages.created_at AS message_created_at,
                   group_conversations.title AS conversation_title,
                   personas.name AS persona_name,
                   'group' AS scope
            FROM group_message_expressions
            JOIN group_messages ON group_messages.id = group_message_expressions.group_message_id
            JOIN group_conversations ON group_conversations.id = group_message_expressions.group_conversation_id
            JOIN personas ON personas.id = group_message_expressions.persona_id
            WHERE group_message_expressions.user_id = ?
              {group_persona_clause}
            ORDER BY group_message_expressions.id DESC
            LIMIT ?
            """,
            group_params,
        ).fetchall()
    asset_map = {
        (str(asset.get("expression_type") or ""), str(asset.get("label") or "")): asset
        for asset in expression_assets_public(include_disabled=True, include_admin_metadata=True)
    }
    usage_rows = [_with_expression_asset_metadata(dict_from_row(row), asset_map) for row in [*single_rows, *group_rows]]
    usage_rows.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
    recent = usage_rows[:limit]
    counts: dict[str, dict[str, Any]] = {}
    summary = {
        "window": len(usage_rows),
        "single": 0,
        "group": 0,
        "disabled_asset": 0,
        "medium_risk": 0,
    }
    for item in usage_rows:
        scope = "group" if item.get("scope") == "group" else "single"
        summary[scope] += 1
        if item.get("asset_enabled") is False:
            summary["disabled_asset"] += 1
        if item.get("risk_level") == "medium":
            summary["medium_risk"] += 1
        key = f"{item.get('expression_type') or 'gesture'}:{item.get('label') or ''}"
        if key not in counts:
            counts[key] = {
                "tag": key,
                "count": 0,
                "label": item.get("label") or "",
                "expression_type": item.get("expression_type") or "gesture",
                "display_text": item.get("display_text") or item.get("label") or "",
                "asset_enabled": item.get("asset_enabled", False),
                "risk_level": item.get("risk_level") or "unknown",
                "group": item.get("group") or "unknown",
                "cooldown_turns": int(item.get("cooldown_turns") or 0),
            }
        counts[key]["count"] += 1
    sorted_counts = sorted(counts.values(), key=lambda item: (-int(item["count"]), str(item["tag"])))
    insights: list[dict[str, Any]] = []
    if summary["disabled_asset"]:
        insights.append({
            "kind": "disabled_asset_history",
            "severity": "watch",
            "text": f"{summary['disabled_asset']} 条历史记录来自当前已禁用资源，普通端已隐藏，管理端仍保留审查。",
        })
    if summary["medium_risk"]:
        insights.append({
            "kind": "medium_risk_usage",
            "severity": "watch",
            "text": f"{summary['medium_risk']} 条中风险轻表达出现在统计窗口内，可结合冷却轮数继续观察。",
        })
    if sorted_counts and summary["window"]:
        top = sorted_counts[0]
        share = int(top["count"]) / max(1, int(summary["window"]))
        if int(top["count"]) >= 3 and share >= 0.5:
            insights.append({
                "kind": "concentrated_label",
                "severity": "tune",
                "text": f"{top['display_text']} 占最近统计窗口 {share:.0%}，可考虑提高冷却或改写用途说明。",
                "tag": top["tag"],
            })
    preference = {"enabled": True, "mode": "normal", "explicit": False}
    if preference_row:
        row = dict_from_row(preference_row) or {}
        mode = _normalize_expression_mode(row.get("mode"), bool(int(row.get("enabled", 1) or 0)))
        preference = {
            "enabled": mode != "off",
            "mode": mode,
            "explicit": True,
            "updated_at": int(row.get("updated_at") or 0),
            "source_message_id": row.get("source_message_id"),
        }
    return {
        "preference": preference,
        "summary": summary,
        "insights": insights,
        "recent": recent,
        "counts": sorted_counts,
        "counted": len(usage_rows),
    }


@app.post("/api/admin/rag/sync")
def admin_rag_sync(
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
    persona_id: int | None = None,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    _assert_persona_owner(owner_id, persona_id)
    return {"sync": sync_memory_embeddings(owner_id, persona_id)}


@app.get("/api/admin/rag/search")
def admin_rag_search(
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
    persona_id: int | None = None,
    q: str = "",
    limit: int = 8,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    _assert_persona_owner(owner_id, persona_id)
    return {"results": semantic_memory_recall(owner_id, persona_id, q, limit)}


@app.patch("/api/admin/insight")
def admin_update_insight(
    req: InsightUpdateRequest,
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    return {
        "insight": update_user_insight(
            owner_id,
            profile_summary=req.profile_summary,
            interaction_style=req.interaction_style,
            emotional_patterns=req.emotional_patterns,
            inferred_profile=req.inferred_profile,
            topic_model=req.topic_model,
            guidance=req.guidance,
        )
    }


@app.patch("/api/admin/memory/judgements/{judgement_id}")
def admin_update_judgement(
    judgement_id: int,
    req: JudgementStatusRequest,
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    try:
        return {"judgement": update_judgement_status(owner_id, judgement_id, req.status)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/admin/memory/conflicts/{conflict_id}")
def admin_update_conflict(
    conflict_id: int,
    req: ConflictStatusRequest,
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    try:
        return {"conflict": update_conflict_status(owner_id, conflict_id, req.status)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/memory/review")
def admin_review_memory(
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
    persona_id: int | None = None,
    include_history: bool = True,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    _assert_persona_owner(owner_id, persona_id)
    return {"review": memory_review(owner_id, persona_id, include_history)}


@app.post("/api/admin/evaluations/memory/seed")
def admin_seed_memory_eval(admin: dict = Depends(current_admin)):
    return {"seed": seed_memory_eval_data(reset=True)}


@app.post("/api/admin/evaluations/memory/run")
def admin_run_memory_eval(req: MemoryEvalRequest, admin: dict = Depends(current_admin)):
    return {"run": run_memory_evaluation(reset_seed=req.reset_seed, include_semantic=req.include_semantic)}


@app.post("/api/admin/evaluations/chat-context/run")
def admin_run_chat_context_eval(req: MemoryEvalRequest, admin: dict = Depends(current_admin)):
    return {"run": run_chat_context_evaluation(reset_seed=req.reset_seed, include_semantic=req.include_semantic)}


@app.post("/api/admin/evaluations/live-answer/run")
def admin_run_live_answer_eval(req: MemoryEvalRequest, admin: dict = Depends(current_admin)):
    return {"run": run_live_answer_evaluation(reset_seed=req.reset_seed)}


@app.post("/api/admin/evaluations/profile-context/run")
def admin_run_profile_context_eval(req: MemoryEvalRequest, admin: dict = Depends(current_admin)):
    return {"run": run_profile_context_evaluation(reset_seed=req.reset_seed)}


@app.post("/api/admin/evaluations/profile-live-answer/run")
def admin_run_profile_live_answer_eval(req: MemoryEvalRequest, admin: dict = Depends(current_admin)):
    return {"run": run_profile_live_answer_evaluation(reset_seed=req.reset_seed)}


@app.post("/api/admin/evaluations/state-resolution/run")
def admin_run_state_resolution_eval(req: MemoryEvalRequest, admin: dict = Depends(current_admin)):
    return {"run": run_state_resolution_evaluation(reset_seed=req.reset_seed)}


@app.post("/api/admin/evaluations/state-expiry/run")
def admin_run_state_expiry_eval(req: MemoryEvalRequest, admin: dict = Depends(current_admin)):
    return {"run": run_state_expiry_evaluation(reset_seed=req.reset_seed)}


@app.post("/api/admin/evaluations/memory-policy/run")
def admin_run_memory_policy_eval(req: MemoryEvalRequest, admin: dict = Depends(current_admin)):
    return {"run": run_memory_policy_evaluation(reset_seed=req.reset_seed)}


@app.get("/api/admin/evaluations/memory/runs")
def admin_memory_eval_runs(admin: dict = Depends(current_admin), limit: int = 10):
    return {"runs": list_memory_eval_runs(limit)}


@app.post("/api/admin/demos/persona-growth/seed")
def admin_seed_growth_demo(admin: dict = Depends(current_admin)):
    return {"demo": seed_growth_demo_data(reset=True)}


@app.delete("/api/admin/demos/persona-growth")
def admin_clear_growth_demo(admin: dict = Depends(current_admin)):
    return {"demo": clear_growth_demo_data()}


@app.get("/api/admin/llm-calls")
def admin_llm_calls(admin: dict = Depends(current_admin), limit: int = 30, task: str | None = None):
    limit = max(1, min(int(limit), 200))
    params: list[Any] = []
    task_clause = ""
    if task:
        task_clause = "WHERE task = ?"
        params.append(task)
    params.append(limit)
    with get_db() as db:
        rows = db.execute(
            f"""
            SELECT id, task, provider, model, status, prompt_chars, response_chars,
                   duration_ms, error_text, created_at
            FROM llm_call_logs
            {task_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return {"calls": [dict_from_row(row) for row in rows]}


@app.get("/api/admin/error-events")
def admin_error_events(admin: dict = Depends(current_admin), limit: int = 50, status_code: int | None = None):
    return {"events": list_error_events(limit=limit, status_code=status_code)}


@app.get("/api/admin/llm-routes")
def admin_llm_routes(admin: dict = Depends(current_admin)):
    config = load_config()
    base = dict(config.get("llm", {}) or {})
    routes = config.get("llm_routes", {}) or {}
    if not isinstance(routes, dict):
        routes = {}

    safe_routes: dict[str, dict[str, Any]] = {}
    effective: dict[str, dict[str, Any]] = {}
    for task, route in sorted(routes.items()):
        if not isinstance(route, dict):
            continue
        route_config = dict(base)
        route_config.update(route)
        safe_routes[str(task)] = _safe_llm_config(route)
        effective[str(task)] = _safe_llm_config(route_config)

    return {
        "default": _safe_llm_config(base),
        "routes": safe_routes,
        "effective": effective,
    }


def _safe_llm_config(config: dict[str, Any]) -> dict[str, Any]:
    allowed = ("provider", "provider_name", "model", "base_url", "api_key_env", "temperature")
    return {key: config.get(key) for key in allowed if config.get(key) not in (None, "")}


@app.get("/api/admin/memory/items/{uid}")
def admin_memory_item(uid: str, admin: dict = Depends(current_admin), target_user_id: int | None = None):
    try:
        owner_id = _admin_target_user_id(admin, target_user_id)
        return get_memory_item(owner_id, uid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/admin/memory/items/{uid}")
def admin_update_memory(
    uid: str,
    req: MemoryUpdateRequest,
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
):
    try:
        owner_id = _admin_target_user_id(admin, target_user_id)
        return update_memory_item(
            user_id=owner_id,
            uid=uid,
            priority=req.priority,
            locked=req.locked,
            archived=req.archived,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/users")
def admin_users(admin: dict = Depends(current_admin)):
    with get_db() as db:
        rows = db.execute(
            """
            SELECT users.id, users.username, users.role, users.status, users.created_at,
                   users.is_guest, users.guest_expires_at, user_profiles.nickname,
                   (
                       SELECT COUNT(*)
                       FROM persona_revision_suggestions
                       JOIN personas ON personas.id = persona_revision_suggestions.persona_id
                       WHERE persona_revision_suggestions.user_id = users.id
                         AND personas.user_id = users.id
                         AND personas.status = 'active'
                         AND persona_revision_suggestions.status = 'pending'
                         AND persona_revision_suggestions.base_version = personas.version
                   ) AS pending_revision_count,
                   (
                       SELECT COUNT(*)
                       FROM persona_revision_suggestions
                       JOIN personas ON personas.id = persona_revision_suggestions.persona_id
                       WHERE persona_revision_suggestions.user_id = users.id
                         AND personas.user_id = users.id
                         AND personas.status = 'active'
                         AND persona_revision_suggestions.status = 'pending'
                         AND persona_revision_suggestions.base_version = personas.version
                         AND persona_revision_suggestions.origin = 'explicit_feedback'
                   ) AS pending_auto_revision_count,
                   (
                       SELECT COUNT(*)
                       FROM persona_revision_suggestions
                       JOIN personas ON personas.id = persona_revision_suggestions.persona_id
                       WHERE persona_revision_suggestions.user_id = users.id
                         AND personas.user_id = users.id
                         AND personas.status = 'active'
                         AND persona_revision_suggestions.status = 'pending'
                         AND (
                             persona_revision_suggestions.base_version IS NULL
                             OR persona_revision_suggestions.base_version != personas.version
                         )
                   ) AS stale_revision_count,
                   (
                       SELECT COUNT(*)
                       FROM persona_growth_feedback
                       JOIN personas ON personas.id = persona_growth_feedback.persona_id
                       WHERE persona_growth_feedback.user_id = users.id
                         AND personas.user_id = users.id
                         AND personas.status = 'active'
                         AND persona_growth_feedback.reaction = 'needs_adjustment'
                         AND persona_growth_feedback.detail_text <> ''
                         AND persona_growth_feedback.resolved_at = 0
                         AND persona_growth_feedback.reviewed_version = (
                             SELECT COALESCE(MAX(persona_versions.version), 0)
                             FROM persona_versions
                             WHERE persona_versions.persona_id = personas.id
                               AND persona_versions.change_type = 'sculptor_review'
                         )
                   ) AS adjustment_feedback_count,
                   (
                       SELECT COUNT(*)
                       FROM persona_growth_requests
                       JOIN persona_revision_suggestions
                         ON persona_revision_suggestions.id = persona_growth_requests.suggestion_id
                       JOIN personas ON personas.id = persona_growth_requests.persona_id
                       WHERE persona_growth_requests.user_id = users.id
                         AND persona_growth_requests.withdrawn_at = 0
                         AND personas.user_id = users.id
                         AND personas.status = 'active'
                         AND persona_revision_suggestions.status = 'pending'
                         AND persona_revision_suggestions.base_version = personas.version
                   ) AS pending_preference_request_count
            FROM users
            LEFT JOIN user_profiles ON user_profiles.user_id = users.id
            ORDER BY pending_revision_count DESC, pending_preference_request_count DESC,
                     adjustment_feedback_count DESC, stale_revision_count DESC, users.created_at DESC
            LIMIT 200
            """
        ).fetchall()
    return {"users": [dict_from_row(row) for row in rows]}


@app.get("/api/admin/guests")
def admin_guests(admin: dict = Depends(current_admin), limit: int = 20):
    ts = now_ts()
    safe_limit = max(1, min(int(limit or 20), 100))
    with get_db() as db:
        active = db.execute(
            """
            SELECT
                COUNT(*) AS active_guest_count,
                COALESCE(SUM(CASE WHEN guest_expires_at > 0 AND guest_expires_at <= ? THEN 1 ELSE 0 END), 0) AS expiring_24h_count,
                COALESCE(MIN(NULLIF(guest_expires_at, 0)), 0) AS next_expiry_at
            FROM users
            WHERE is_guest = 1 AND status = 'active'
            """,
            (ts + 86400,),
        ).fetchone()
        logs = db.execute(
            """
            SELECT id, user_id, username, guest_expires_at, deleted_at, reason
            FROM guest_cleanup_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return {
        "active_guest_count": int(active["active_guest_count"] or 0),
        "expiring_24h_count": int(active["expiring_24h_count"] or 0),
        "next_expiry_at": int(active["next_expiry_at"] or 0),
        "cleanup_logs": [dict_from_row(row) for row in logs],
    }


@app.get("/api/admin/personas")
def admin_personas(admin: dict = Depends(current_admin), target_user_id: int | None = None):
    owner_id = _admin_target_user_id(admin, target_user_id)
    with get_db() as db:
        rows = db.execute(
            """
            SELECT id, user_id, name, summary, relationship, speaking_style,
                   appearance_description, desired_image, live2d_model_id,
                   live2d_preview_url, fallback_image_url, voice_profile, psychological_fit_notes,
                   psychological_profile_json, growth_notes, avatar_url,
                   version, status, created_at, updated_at,
                   (
                       SELECT COUNT(*)
                       FROM persona_revision_suggestions
                       WHERE persona_revision_suggestions.user_id = personas.user_id
                         AND persona_revision_suggestions.persona_id = personas.id
                         AND personas.status = 'active'
                         AND persona_revision_suggestions.status = 'pending'
                         AND persona_revision_suggestions.base_version = personas.version
                   ) AS pending_revision_count,
                   (
                       SELECT COUNT(*)
                       FROM persona_revision_suggestions
                       WHERE persona_revision_suggestions.user_id = personas.user_id
                         AND persona_revision_suggestions.persona_id = personas.id
                         AND personas.status = 'active'
                         AND persona_revision_suggestions.status = 'pending'
                         AND persona_revision_suggestions.base_version = personas.version
                         AND persona_revision_suggestions.origin = 'explicit_feedback'
                   ) AS pending_auto_revision_count,
                   (
                       SELECT COUNT(*)
                       FROM persona_revision_suggestions
                       WHERE persona_revision_suggestions.user_id = personas.user_id
                         AND persona_revision_suggestions.persona_id = personas.id
                         AND personas.status = 'active'
                         AND persona_revision_suggestions.status = 'pending'
                         AND (
                             persona_revision_suggestions.base_version IS NULL
                             OR persona_revision_suggestions.base_version != personas.version
                         )
                   ) AS stale_revision_count,
                   (
                       SELECT COUNT(*)
                       FROM persona_revision_suggestions
                       WHERE persona_revision_suggestions.user_id = personas.user_id
                         AND persona_revision_suggestions.persona_id = personas.id
                         AND personas.status = 'active'
                         AND persona_revision_suggestions.status = 'pending'
                         AND (
                             persona_revision_suggestions.base_version IS NULL
                             OR persona_revision_suggestions.base_version != personas.version
                         )
                         AND NOT EXISTS (
                             SELECT 1
                             FROM persona_growth_requests
                             WHERE persona_growth_requests.suggestion_id = persona_revision_suggestions.id
                               AND persona_growth_requests.withdrawn_at = 0
                         )
                   ) AS cleanable_stale_revision_count,
                   (
                       SELECT COUNT(*)
                       FROM persona_growth_feedback
                       WHERE persona_growth_feedback.user_id = personas.user_id
                         AND persona_growth_feedback.persona_id = personas.id
                         AND personas.status = 'active'
                         AND persona_growth_feedback.reaction = 'needs_adjustment'
                         AND persona_growth_feedback.detail_text <> ''
                         AND persona_growth_feedback.resolved_at = 0
                         AND persona_growth_feedback.reviewed_version = (
                             SELECT COALESCE(MAX(persona_versions.version), 0)
                             FROM persona_versions
                             WHERE persona_versions.persona_id = personas.id
                               AND persona_versions.change_type = 'sculptor_review'
                         )
                   ) AS adjustment_feedback_count,
                   (
                       SELECT COUNT(*)
                       FROM persona_growth_requests
                       JOIN persona_revision_suggestions
                         ON persona_revision_suggestions.id = persona_growth_requests.suggestion_id
                       WHERE persona_growth_requests.user_id = personas.user_id
                         AND persona_growth_requests.persona_id = personas.id
                         AND persona_growth_requests.withdrawn_at = 0
                         AND personas.status = 'active'
                         AND persona_revision_suggestions.status = 'pending'
                         AND persona_revision_suggestions.base_version = personas.version
                   ) AS pending_preference_request_count
            FROM personas
            WHERE user_id = ?
            ORDER BY pending_revision_count DESC, pending_preference_request_count DESC,
                     adjustment_feedback_count DESC, stale_revision_count DESC, updated_at DESC
            LIMIT 200
            """,
            (owner_id,),
        ).fetchall()
    return {"personas": [dict_from_row(row) for row in rows]}


@app.get("/api/admin/persona-revisions")
def admin_persona_revisions(
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
    persona_id: int | None = None,
    limit: int = 20,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    _assert_persona_owner(owner_id, persona_id)
    suggestions = list_revision_suggestions(owner_id, persona_id, limit)
    with get_db() as db:
        protected_ids = {
            int(row["suggestion_id"])
            for row in db.execute(
                """
                SELECT persona_growth_requests.suggestion_id
                FROM persona_growth_requests
                JOIN persona_revision_suggestions
                  ON persona_revision_suggestions.id = persona_growth_requests.suggestion_id
                WHERE persona_growth_requests.user_id = ? AND persona_growth_requests.persona_id = ?
                  AND persona_growth_requests.withdrawn_at = 0
                  AND persona_revision_suggestions.status = 'pending'
                """,
                (owner_id, persona_id),
            ).fetchall()
            if row["suggestion_id"] is not None
        }
    for suggestion in suggestions:
        suggestion["protected_by_active_request"] = int(suggestion["id"]) in protected_ids
    return {"suggestions": suggestions}


@app.get("/api/admin/persona-versions")
def admin_persona_versions(
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
    persona_id: int | None = None,
    limit: int = 20,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    if persona_id is None:
        raise HTTPException(status_code=400, detail="persona_id is required")
    _assert_persona_owner(owner_id, persona_id)
    limit = max(1, min(int(limit), 100))
    with get_db() as db:
        rows = db.execute(
            """
            SELECT *
            FROM persona_versions
            WHERE persona_id = ?
            ORDER BY version DESC, id DESC
            LIMIT ?
            """,
            (persona_id, limit),
        ).fetchall()
    return {"versions": [_public_persona(dict_from_row(row)) for row in rows]}


@app.get("/api/admin/persona-growth")
def admin_persona_growth(
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
    persona_id: int | None = None,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    if persona_id is None:
        raise HTTPException(status_code=400, detail="persona_id is required")
    _assert_persona_owner(owner_id, persona_id)
    with get_db() as db:
        persona = dict_from_row(
            db.execute(
                "SELECT * FROM personas WHERE id = ? AND user_id = ?",
                (persona_id, owner_id),
            ).fetchone()
        )
        feedback_facts = db.execute(
            """
            SELECT uid, type, text, importance, confidence, priority, locked, updated_at
            FROM memory_facts
            WHERE user_id = ? AND (persona_id = ? OR persona_id IS NULL)
              AND type IN ('persona_feedback', 'boundary', 'relationship', 'preference')
              AND archived = 0 AND valid_to IS NULL
            ORDER BY priority DESC, importance DESC, updated_at DESC
            LIMIT 30
            """,
            (owner_id, persona_id),
        ).fetchall()
        feedback_relations = db.execute(
            """
            SELECT uid, type, subject, predicate, object, text, importance, confidence, priority, locked, updated_at
            FROM memory_relations
            WHERE user_id = ? AND (persona_id = ? OR persona_id IS NULL)
              AND predicate IN ('persona_feedback', 'boundary', 'relationship_expectation', 'preference')
              AND archived = 0 AND valid_to IS NULL
            ORDER BY priority DESC, importance DESC, updated_at DESC
            LIMIT 30
            """,
            (owner_id, persona_id),
        ).fetchall()
        versions = db.execute(
            """
            SELECT *
            FROM persona_versions
            WHERE persona_id = ?
            ORDER BY version DESC, id DESC
            LIMIT 8
            """,
            (persona_id,),
        ).fetchall()
        user_feedback = db.execute(
            """
            SELECT reviewed_version, reaction, detail_text, resolved_at, resolved_by_user_id,
                   resolution_note, created_at, updated_at
            FROM persona_growth_feedback
            WHERE user_id = ? AND persona_id = ?
            ORDER BY reviewed_version DESC
            LIMIT 8
            """,
            (owner_id, persona_id),
        ).fetchall()
        preference_requests = db.execute(
            """
            SELECT persona_growth_requests.id, persona_growth_requests.request_text,
                   persona_growth_requests.created_at, persona_growth_requests.updated_at,
                   persona_growth_requests.withdrawn_at,
                   persona_growth_requests.request_origin,
                   persona_growth_requests.source_reviewed_version,
                   persona_growth_requests.deactivation_actor,
                   persona_growth_requests.deactivation_reason,
                   persona_revision_suggestions.id AS suggestion_id,
                   persona_revision_suggestions.status AS suggestion_status,
                   persona_revision_suggestions.origin AS suggestion_origin,
                   persona_revision_suggestions.base_version,
                   persona_revision_suggestions.applied_version,
                   persona_revision_suggestions.decided_at,
                   persona_revision_suggestions.decided_by_user_id,
                   persona_revision_suggestions.decision_note
            FROM persona_growth_requests
            LEFT JOIN persona_revision_suggestions
              ON persona_revision_suggestions.id = persona_growth_requests.suggestion_id
            WHERE persona_growth_requests.user_id = ? AND persona_growth_requests.persona_id = ?
            ORDER BY persona_growth_requests.id DESC
            LIMIT 12
            """,
            (owner_id, persona_id),
        ).fetchall()
    return {
        "persona": _public_persona(persona),
        "growth_memories": {
            "facts": [dict_from_row(row) for row in feedback_facts],
            "relations": [dict_from_row(row) for row in feedback_relations],
        },
        "user_feedback": [dict_from_row(row) for row in user_feedback],
        "preference_requests": [dict_from_row(row) for row in preference_requests],
        "versions": [_public_persona(dict_from_row(row)) for row in versions],
    }


@app.post("/api/admin/persona-growth/feedback/resolve")
def admin_resolve_persona_growth_feedback(
    req: PersonaGrowthFeedbackResolutionRequest,
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
    persona_id: int | None = None,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    if persona_id is None:
        raise HTTPException(status_code=400, detail="persona_id is required")
    _assert_persona_owner(owner_id, persona_id)
    ts = now_ts()
    note = scrub_identity_text(req.note.strip())[:1000]
    with get_db() as db:
        cursor = db.execute(
            """
            UPDATE persona_growth_feedback
            SET resolved_at = ?, resolved_by_user_id = ?, resolution_note = ?
            WHERE user_id = ? AND persona_id = ? AND reviewed_version = ?
              AND reaction = 'needs_adjustment' AND resolved_at = 0
            """,
            (ts, int(admin["id"]), note, owner_id, persona_id, req.reviewed_version),
        )
        if not cursor.rowcount:
            raise HTTPException(status_code=404, detail="open adjustment feedback not found")
        feedback = dict_from_row(db.execute(
            """
            SELECT reviewed_version, reaction, detail_text, resolved_at, resolved_by_user_id,
                   resolution_note, created_at, updated_at
            FROM persona_growth_feedback
            WHERE user_id = ? AND persona_id = ? AND reviewed_version = ?
            """,
            (owner_id, persona_id, req.reviewed_version),
        ).fetchone())
    return {"feedback": feedback}


@app.post("/api/admin/persona-revisions")
def admin_generate_persona_revision(
    req: PersonaRevisionRequest,
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
    persona_id: int | None = None,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    if persona_id is None:
        raise HTTPException(status_code=400, detail="persona_id is required")
    _assert_persona_owner(owner_id, persona_id)
    try:
        return {"suggestion": generate_revision_suggestion(owner_id, persona_id, req.reason)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/persona-revisions/auto-review")
def admin_auto_review_persona_revisions(
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
    persona_id: int | None = None,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    if persona_id is None:
        raise HTTPException(status_code=400, detail="persona_id is required")
    _assert_persona_owner(owner_id, persona_id)
    with get_db() as db:
        rows = db.execute(
            """
            SELECT persona_revision_suggestions.id
            FROM persona_revision_suggestions
            JOIN personas ON personas.id = persona_revision_suggestions.persona_id
            WHERE persona_revision_suggestions.user_id = ? AND persona_revision_suggestions.persona_id = ?
              AND personas.user_id = ? AND personas.status = 'active'
              AND persona_revision_suggestions.status = 'pending'
              AND persona_revision_suggestions.origin = 'explicit_feedback'
              AND persona_revision_suggestions.base_version = personas.version
            ORDER BY persona_revision_suggestions.id ASC
            """,
            (owner_id, persona_id, owner_id),
        ).fetchall()
    applied = []
    dismissed = []
    for row in rows:
        decision = maybe_auto_review_revision(owner_id, int(row["id"]))
        if decision and decision.get("status") == "dismissed":
            dismissed.append(decision)
        elif decision:
            applied.append(decision)
    return {
        "attempted_count": len(rows),
        "applied_count": len(applied),
        "dismissed_count": len(dismissed),
        "applied": applied,
        "dismissed": dismissed,
    }


@app.post("/api/admin/persona-revisions/{suggestion_id}/apply")
def admin_apply_persona_revision(
    suggestion_id: int,
    req: PersonaRevisionDecisionRequest | None = None,
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    try:
        return apply_revision_suggestion(
            owner_id,
            suggestion_id,
            reviewer_user_id=int(admin["id"]),
            decision_note=req.note if req else "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/persona-revisions/stale/dismiss")
def admin_dismiss_stale_persona_revisions(
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
    persona_id: int | None = None,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    if persona_id is None:
        raise HTTPException(status_code=400, detail="persona_id is required")
    _assert_persona_owner(owner_id, persona_id)
    with get_db() as db:
        rows = db.execute(
            """
            SELECT persona_revision_suggestions.id
            FROM persona_revision_suggestions
            JOIN personas ON personas.id = persona_revision_suggestions.persona_id
            WHERE persona_revision_suggestions.user_id = ? AND persona_revision_suggestions.persona_id = ?
              AND personas.user_id = ? AND personas.status = 'active'
              AND persona_revision_suggestions.status = 'pending'
              AND (
                  persona_revision_suggestions.base_version IS NULL
                  OR persona_revision_suggestions.base_version != personas.version
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM persona_growth_requests
                  WHERE persona_growth_requests.suggestion_id = persona_revision_suggestions.id
                    AND persona_growth_requests.withdrawn_at = 0
              )
            ORDER BY persona_revision_suggestions.id ASC
            """,
            (owner_id, persona_id, owner_id),
        ).fetchall()
    dismissed = [
        dismiss_revision_suggestion(
            owner_id,
            int(row["id"]),
            reviewer_user_id=int(admin["id"]),
            decision_note="人格版本已更新，批量关闭不再可执行的过期建议",
        )
        for row in rows
    ]
    return {"dismissed_count": len(dismissed), "suggestions": dismissed}


@app.post("/api/admin/persona-revisions/{suggestion_id}/dismiss")
def admin_dismiss_persona_revision(
    suggestion_id: int,
    req: PersonaRevisionDecisionRequest | None = None,
    admin: dict = Depends(current_admin),
    target_user_id: int | None = None,
):
    owner_id = _admin_target_user_id(admin, target_user_id)
    try:
        return {
            "suggestion": dismiss_revision_suggestion(
                owner_id,
                suggestion_id,
                reviewer_user_id=int(admin["id"]),
                decision_note=req.note if req else "",
            )
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _admin_target_user_id(admin: dict, target_user_id: int | None) -> int:
    owner_id = target_user_id or int(admin["id"])
    with get_db() as db:
        row = db.execute("SELECT id FROM users WHERE id = ?", (owner_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="target user not found")
    return owner_id


def _assert_persona_owner(owner_id: int, persona_id: int | None) -> None:
    if persona_id is None:
        return
    with get_db() as db:
        row = db.execute("SELECT id FROM personas WHERE id = ? AND user_id = ?", (persona_id, owner_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="persona not found for target user")


@app.get("/api/insights")
def insights(user: dict = Depends(current_user)):
    return {"insight": get_user_insight(int(user["id"]))}


@app.get("/api/personas")
def personas(user: dict = Depends(current_user)):
    bound_persona_id = _self_use_bound_persona_id(user)
    with get_db() as db:
        rows = db.execute(
            """
            SELECT personas.id, personas.name, personas.summary, personas.relationship,
                   personas.speaking_style, personas.appearance_description, personas.desired_image,
                   personas.live2d_model_id, personas.live2d_preview_url,
                   personas.fallback_image_url, personas.voice_profile,
                   personas.psychological_fit_notes, personas.psychological_profile_json,
                   personas.growth_notes, personas.avatar_url, personas.version,
                   personas.created_at, personas.updated_at,
                   (
                       SELECT version
                       FROM persona_versions
                       WHERE persona_versions.persona_id = personas.id
                         AND persona_versions.change_type = 'sculptor_review'
                       ORDER BY version DESC, id DESC
                       LIMIT 1
                   ) AS latest_reviewed_version,
                   (
                       SELECT created_at
                       FROM persona_versions
                       WHERE persona_versions.persona_id = personas.id
                         AND persona_versions.change_type = 'sculptor_review'
                       ORDER BY version DESC, id DESC
                       LIMIT 1
                   ) AS latest_reviewed_at,
                   COALESCE(persona_growth_views.seen_reviewed_version, 0) AS seen_reviewed_version,
                   (
                       SELECT COUNT(*)
                       FROM persona_growth_requests
                       JOIN persona_revision_suggestions
                         ON persona_revision_suggestions.id = persona_growth_requests.suggestion_id
                       WHERE persona_growth_requests.user_id = personas.user_id
                         AND persona_growth_requests.persona_id = personas.id
                         AND persona_growth_requests.withdrawn_at = 0
                         AND persona_revision_suggestions.status = 'pending'
                         AND persona_revision_suggestions.origin = 'profile_request'
                         AND (
                             persona_revision_suggestions.base_version IS NULL
                             OR persona_revision_suggestions.base_version != personas.version
                         )
                   ) AS retry_preference_request_count,
                    (
                        SELECT enabled
                        FROM expression_preferences
                        WHERE expression_preferences.user_id = personas.user_id
                          AND expression_preferences.persona_id = personas.id
                        LIMIT 1
                    ) AS expression_enabled,
                    (
                        SELECT mode
                        FROM expression_preferences
                        WHERE expression_preferences.user_id = personas.user_id
                          AND expression_preferences.persona_id = personas.id
                        LIMIT 1
                    ) AS expression_mode
            FROM personas
            LEFT JOIN persona_growth_views
              ON persona_growth_views.persona_id = personas.id
             AND persona_growth_views.user_id = personas.user_id
            WHERE personas.user_id = ? AND personas.status = 'active'
            ORDER BY personas.updated_at DESC
            """,
            (user["id"],),
        ).fetchall()
    if bound_persona_id is not None:
        rows = [row for row in rows if int(row["id"]) == bound_persona_id]
    return {"personas": [_persona_list_item(dict_from_row(row) or {}) for row in rows]}


@app.get("/api/personas/deleted")
def deleted_personas(user: dict = Depends(current_user)):
    if _self_use_public(user).get("enabled"):
        return {"personas": []}
    with get_db() as db:
        rows = db.execute(
            """
            SELECT id, name, summary, relationship, speaking_style,
                   appearance_description, desired_image, live2d_model_id,
                   live2d_preview_url, fallback_image_url, voice_profile, psychological_fit_notes,
                   psychological_profile_json, growth_notes, avatar_url,
                   version, created_at, updated_at
            FROM personas
            WHERE user_id = ? AND status = 'deleted'
            ORDER BY updated_at DESC
            """,
            (user["id"],),
        ).fetchall()
    return {"personas": [dict_from_row(row) for row in rows]}


@app.get("/api/personas/{persona_id}")
def persona_detail(persona_id: int, user: dict = Depends(current_user)):
    _require_self_use_bound_persona(user, persona_id)
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM personas WHERE id = ? AND user_id = ? AND status = 'active'",
            (persona_id, user["id"]),
        ).fetchone()
    persona = _public_persona(dict_from_row(row))
    if not persona:
        raise HTTPException(status_code=404, detail="persona not found")
    persona["expression_preference"] = _expression_preference_public(int(user["id"]), persona_id)
    return {"persona": persona}


@app.get("/api/personas/{persona_id}/embodiment")
def persona_embodiment(persona_id: int, user: dict = Depends(current_user)):
    _require_self_use_bound_persona(user, persona_id)
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM personas WHERE id = ? AND user_id = ? AND status = 'active'",
            (persona_id, int(user["id"])),
        ).fetchone()
    persona = _public_persona(dict_from_row(row))
    if not persona:
        raise HTTPException(status_code=404, detail="persona not found")
    return {"persona_id": persona_id, "embodiment": persona_embodiment_profile(persona)}


@app.get("/api/personas/{persona_id}/growth")
def persona_growth(persona_id: int, user: dict = Depends(current_user)):
    _require_self_use_bound_persona(user, persona_id)
    user_id = int(user["id"])
    with get_db() as db:
        persona = db.execute(
            "SELECT id, version FROM personas WHERE id = ? AND user_id = ? AND status = 'active'",
            (persona_id, user_id),
        ).fetchone()
        if not persona:
            raise HTTPException(status_code=404, detail="persona not found")
        fact_count = int(
            db.execute(
                """
                SELECT COUNT(*)
                FROM memory_facts
                WHERE user_id = ? AND (persona_id = ? OR persona_id IS NULL)
                  AND type IN ('persona_feedback', 'boundary', 'relationship', 'preference')
                  AND archived = 0 AND valid_to IS NULL
                """,
                (user_id, persona_id),
            ).fetchone()[0]
        )
        relation_count = int(
            db.execute(
                """
                SELECT COUNT(*)
                FROM memory_relations
                WHERE user_id = ? AND (persona_id = ? OR persona_id IS NULL)
                  AND predicate IN ('persona_feedback', 'boundary', 'relationship_expectation', 'preference')
                  AND archived = 0 AND valid_to IS NULL
                """,
                (user_id, persona_id),
            ).fetchone()[0]
        )
        state_count = int(
            db.execute(
                """
                SELECT COUNT(*)
                FROM memory_state
                WHERE user_id = ? AND (persona_id = ? OR persona_id IS NULL)
                """,
                (user_id, persona_id),
            ).fetchone()[0]
        )
        reviewed_versions = [
            dict_from_row(row)
            for row in db.execute(
            """
            SELECT *
            FROM persona_versions
            WHERE persona_id = ? AND change_type = 'sculptor_review'
            ORDER BY version DESC, id DESC
            LIMIT 5
            """,
            (persona_id,),
        ).fetchall()
        ]
        reviewed_version = reviewed_versions[0] if reviewed_versions else None
        reviewed_history: list[dict[str, Any]] = []
        for reviewed_item in reviewed_versions:
            previous_item = dict_from_row(db.execute(
                """
                SELECT *
                FROM persona_versions
                WHERE persona_id = ? AND version < ?
                ORDER BY version DESC, id DESC
                LIMIT 1
                """,
                (persona_id, int(reviewed_item["version"])),
            ).fetchone())
            feedback_item = dict_from_row(db.execute(
                """
                SELECT reviewed_version, reaction, detail_text, resolved_at, created_at, updated_at
                FROM persona_growth_feedback
                WHERE user_id = ? AND persona_id = ? AND reviewed_version = ?
                """,
                (user_id, persona_id, int(reviewed_item["version"])),
            ).fetchone())
            reviewed_history.append(
                {
                    "reviewed_version": reviewed_item,
                    "previous_version": previous_item,
                    "feedback": feedback_item,
                }
            )
        growth_view = db.execute(
            """
            SELECT seen_reviewed_version
            FROM persona_growth_views
            WHERE user_id = ? AND persona_id = ?
            """,
            (user_id, persona_id),
        ).fetchone()
        previous_version = reviewed_history[0]["previous_version"] if reviewed_history else None
        reviewed_feedback = (
            _public_growth_feedback(reviewed_history[0]["feedback"], include_detail=True)
            if reviewed_history
            else None
        )
        request_rows = db.execute(
            """
            SELECT persona_growth_requests.id, persona_growth_requests.request_text,
                   persona_growth_requests.created_at, persona_growth_requests.updated_at,
                   persona_growth_requests.withdrawn_at,
                   persona_growth_requests.request_origin,
                   persona_growth_requests.source_reviewed_version,
                   persona_growth_requests.deactivation_actor,
                   persona_growth_requests.deactivation_reason,
                   persona_growth_requests.suggestion_id,
                   persona_revision_suggestions.status AS suggestion_status,
                   persona_revision_suggestions.origin AS suggestion_origin,
                   persona_revision_suggestions.base_version,
                   persona_revision_suggestions.applied_version
            FROM persona_growth_requests
            LEFT JOIN persona_revision_suggestions
              ON persona_revision_suggestions.id = persona_growth_requests.suggestion_id
            WHERE persona_growth_requests.user_id = ? AND persona_growth_requests.persona_id = ?
            ORDER BY persona_growth_requests.id DESC
            LIMIT 5
            """,
            (user_id, persona_id),
        ).fetchall()
        request_history: list[dict[str, Any]] = []
        for request_row in request_rows:
            request_item = dict_from_row(request_row) or {}
            public_result = None
            if request_item.get("suggestion_status") == "applied" and request_item.get("applied_version"):
                applied_review = dict_from_row(db.execute(
                    """
                    SELECT *
                    FROM persona_versions
                    WHERE persona_id = ? AND version = ? AND source_suggestion_id = ?
                      AND change_type = 'sculptor_review'
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (persona_id, int(request_item["applied_version"]), int(request_item["suggestion_id"])),
                ).fetchone())
                if applied_review:
                    before_review = dict_from_row(db.execute(
                        """
                        SELECT *
                        FROM persona_versions
                        WHERE persona_id = ? AND version < ?
                        ORDER BY version DESC, id DESC
                        LIMIT 1
                        """,
                        (persona_id, int(applied_review["version"])),
                    ).fetchone())
                    public_result = {
                        "version": int(applied_review["version"]),
                        "created_at": int(applied_review["created_at"]),
                        "highlights": _public_review_highlights(before_review, applied_review),
                    }
            request_item["public_result"] = public_result
            request_history.append(request_item)

    remembered_count = fact_count + relation_count
    seen_reviewed_version = int(growth_view["seen_reviewed_version"]) if growth_view else 0
    reviewed_changes = [
        {
            "version": int(item["reviewed_version"]["version"]),
            "created_at": int(item["reviewed_version"]["created_at"]),
            "highlights": _public_review_highlights(item["previous_version"], item["reviewed_version"]),
            "feedback": _public_growth_feedback(item["feedback"]),
        }
        for item in reviewed_history
    ]
    preference_requests = []
    for item in request_history:
        suggestion_status = str(item.get("suggestion_status") or "")
        public_status = "recorded"
        if int(item.get("withdrawn_at") or 0):
            if item.get("deactivation_actor") == "adaptive_runtime":
                public_status = "superseded"
            elif item.get("deactivation_actor") == "chat_runtime":
                public_status = "stopped_in_chat"
            else:
                public_status = "withdrawn"
        else:
            public_status = "active_guidance"
        preference_requests.append(
            {
                "id": int(item["id"]),
                "detail": item["request_text"],
                "created_at": int(item["created_at"]),
                "updated_at": int(item.get("updated_at") or item["created_at"]),
                "status": public_status,
                "origin": item.get("request_origin") or "direct_entry",
                "source_reviewed_version": item.get("source_reviewed_version"),
                "deactivation_reason": item.get("deactivation_reason") or "",
                "applied_version": item.get("applied_version"),
                "result": item.get("public_result"),
                "can_withdraw": not int(item.get("withdrawn_at") or 0),
                "can_retry": False,
            }
        )
    signals: list[dict[str, Any]] = []
    if remembered_count:
        signals.append(
            {
                "kind": "memory",
                "title": "记住了相处中的重点",
                "text": f"已经留下 {remembered_count} 条与你们相处有关的记忆线索。",
            }
        )
    if state_count:
        signals.append(
            {
                "kind": "attention",
                "title": "正在留意你的节奏",
                "text": f"有 {state_count} 项当前状态或边界正在帮助 TA 回应你。",
            }
        )
    latest_reviewed_change = None
    if reviewed_version:
        highlights = _public_review_highlights(previous_version, reviewed_version)
        latest_reviewed_change = {
            "version": int(reviewed_version["version"]),
            "created_at": int(reviewed_version["created_at"]),
            "unseen": int(reviewed_version["version"]) > seen_reviewed_version,
            "highlights": highlights,
            "feedback": reviewed_feedback,
        }
        signals.append(
            {
                "kind": "adaptation",
                "title": "最近确认的变化",
                "text": f"经确认后，{'；'.join(highlights)}。",
                "created_at": int(reviewed_version["created_at"]),
            }
        )
    if signals:
        headline = "你们的相处正在留下痕迹"
    else:
        headline = "你们的相处还在慢慢形成"
        signals.append(
            {
                "kind": "starting",
                "title": "从自然聊天开始",
                "text": "重要的偏好和相处方式会在之后逐渐被记住。",
            }
        )
    return {
        "growth": {
            "headline": headline,
            "signals": signals,
            "version": int(persona["version"]),
            "latest_reviewed_change": latest_reviewed_change,
            "reviewed_changes": reviewed_changes,
            "preference_requests": preference_requests,
        }
    }


@app.post("/api/personas/{persona_id}/growth/requests")
def submit_persona_preference_request(
    persona_id: int,
    req: PersonaPreferenceRequest,
    user: dict = Depends(current_user),
):
    _require_self_use_bound_persona(user, persona_id)
    detail_text = scrub_identity_text(req.detail.strip())[:500]
    if not detail_text:
        raise HTTPException(status_code=400, detail="请写下希望调整的相处方式")
    return _store_persona_preference_guidance(persona_id, detail_text, user)


def _store_persona_preference_guidance(
    persona_id: int,
    detail_text: str,
    user: dict,
    *,
    request_origin: str = "direct_entry",
    source_reviewed_version: int | None = None,
):
    user_id = int(user["id"])
    with get_db() as db:
        persona = db.execute(
            "SELECT id, version FROM personas WHERE id = ? AND user_id = ? AND status = 'active'",
            (persona_id, user_id),
        ).fetchone()
        if not persona:
            raise HTTPException(status_code=404, detail="persona not found")
        existing_request = dict_from_row(db.execute(
            """
            SELECT persona_growth_requests.id, persona_growth_requests.created_at,
                   persona_growth_requests.memory_uids_json,
                   persona_revision_suggestions.id AS suggestion_id,
                   persona_revision_suggestions.status AS suggestion_status,
                   persona_revision_suggestions.trigger_memory_uids_json
            FROM persona_growth_requests
            LEFT JOIN persona_revision_suggestions
              ON persona_revision_suggestions.id = persona_growth_requests.suggestion_id
            WHERE persona_growth_requests.user_id = ? AND persona_growth_requests.persona_id = ?
              AND persona_growth_requests.withdrawn_at = 0
              AND persona_growth_requests.request_origin = ?
              AND (
                  (? IS NULL AND persona_growth_requests.source_reviewed_version IS NULL)
                  OR persona_growth_requests.source_reviewed_version = ?
              )
            ORDER BY persona_growth_requests.id DESC
            LIMIT 1
            """,
            (user_id, persona_id, request_origin, source_reviewed_version, source_reviewed_version),
        ).fetchone())
    request_memory_text = (
        f"用户对已确认变化提出的补充偏好：{detail_text}"
        if request_origin == "growth_feedback"
        else f"用户主动提出的相处偏好：{detail_text}"
    )
    memory_uids: list[str] = []
    if existing_request:
        try:
            memory_uids = [
                str(uid) for uid in json.loads(
                    existing_request.get("memory_uids_json")
                    or existing_request.get("trigger_memory_uids_json")
                    or "[]"
                )
                if uid
            ]
        except Exception:
            memory_uids = []
        ts = now_ts()
        with get_db() as db:
            for uid in memory_uids:
                db.execute(
                    """
                    UPDATE memory_facts
                    SET text = ?, importance = 0.92, confidence = 1.0,
                        priority = 'high', locked = 1, updated_at = ?
                    WHERE uid = ? AND user_id = ? AND persona_id = ? AND type = 'persona_feedback'
                    """,
                    (request_memory_text, ts, uid, user_id, persona_id),
                )
                db.execute(
                    """
                    UPDATE memory_relations
                    SET text = ?, object = ?, importance = 0.92, confidence = 1.0,
                        priority = 'high', locked = 1, updated_at = ?
                    WHERE uid = ? AND user_id = ? AND persona_id = ? AND type = 'persona_feedback'
                    """,
                        (request_memory_text, request_memory_text[:120], ts, uid, user_id, persona_id),
                )
        if existing_request.get("suggestion_status") == "pending" and existing_request.get("suggestion_id"):
            dismiss_revision_suggestion(
                user_id,
                int(existing_request["suggestion_id"]),
                decision_actor="adaptive_runtime",
                decision_note="已切换为运行时自动适配：用户相处偏好直接进入聊天指导，不再等待人工审核。",
            )
    if not memory_uids:
        stored = store_layered_memories(
            user_id=user_id,
            persona_id=persona_id,
            conversation_id=None,
            source_message_id=None,
            event_uid=None,
            episode_uid=None,
            memories=[
                {
                    "type": "persona_feedback",
                    "text": request_memory_text,
                    "importance": 0.92,
                    "confidence": 1.0,
                }
            ],
        )
        memory_uids = [
            str(item["uid"])
            for item in stored
            if item.get("uid") and item.get("layer") in {"L2", "L3"}
        ]
    ts = now_ts()
    with get_db() as db:
        if existing_request:
            request_id = int(existing_request["id"])
            created_at = int(existing_request["created_at"])
            db.execute(
                "UPDATE persona_growth_requests SET request_text = ?, memory_uids_json = ?, updated_at = ? WHERE id = ?",
                (detail_text, json.dumps(memory_uids, ensure_ascii=False), ts, request_id),
            )
            updated = True
        else:
            cursor = db.execute(
                """
                INSERT INTO persona_growth_requests (
                    user_id, persona_id, request_text, suggestion_id, memory_uids_json,
                    request_origin, source_reviewed_version, created_at, updated_at
                )
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, persona_id, detail_text, json.dumps(memory_uids, ensure_ascii=False),
                    request_origin, source_reviewed_version, ts, ts,
                ),
            )
            request_id = int(cursor.lastrowid)
            created_at = ts
            updated = False
    superseded_request_ids = supersede_conflicting_guidance(
        user_id,
        persona_id,
        detail_text,
        exclude_request_id=request_id,
    )
    refresh_memory_state(user_id, persona_id)
    refresh_memory_summaries(user_id, persona_id)
    return {
        "request": {
            "id": request_id,
            "detail": detail_text,
            "created_at": created_at,
            "updated_at": ts,
            "status": "active_guidance",
            "origin": request_origin,
            "source_reviewed_version": source_reviewed_version,
            "applied_version": None,
        },
        "updated": updated,
        "superseded_request_ids": superseded_request_ids,
    }


@app.post("/api/personas/{persona_id}/growth/requests/{request_id}/retry")
def retry_persona_preference_request(
    persona_id: int,
    request_id: int,
    user: dict = Depends(current_user),
):
    _require_self_use_bound_persona(user, persona_id)
    user_id = int(user["id"])
    with get_db() as db:
        row = dict_from_row(db.execute(
            """
            SELECT persona_growth_requests.*, persona_revision_suggestions.status AS suggestion_status,
                   persona_revision_suggestions.origin AS suggestion_origin,
                   persona_revision_suggestions.base_version,
                   persona_revision_suggestions.trigger_memory_uids_json,
                   personas.version AS persona_version
            FROM persona_growth_requests
            LEFT JOIN persona_revision_suggestions
              ON persona_revision_suggestions.id = persona_growth_requests.suggestion_id
            JOIN personas
              ON personas.id = persona_growth_requests.persona_id
             AND personas.user_id = persona_growth_requests.user_id
             AND personas.status = 'active'
            WHERE persona_growth_requests.id = ? AND persona_growth_requests.user_id = ?
              AND persona_growth_requests.persona_id = ?
            """,
            (request_id, user_id, persona_id),
        ).fetchone())
    if not row:
        raise HTTPException(status_code=404, detail="request not found")
    if int(row.get("withdrawn_at") or 0):
        raise HTTPException(status_code=400, detail="已撤回的偏好不能重新提交")
    return submit_persona_preference_request(
        persona_id,
        PersonaPreferenceRequest(detail=str(row["request_text"] or "")),
        user,
    )


@app.post("/api/personas/{persona_id}/growth/requests/{request_id}/withdraw")
def withdraw_persona_preference_request(
    persona_id: int,
    request_id: int,
    user: dict = Depends(current_user),
):
    _require_self_use_bound_persona(user, persona_id)
    user_id = int(user["id"])
    with get_db() as db:
        row = dict_from_row(db.execute(
            """
            SELECT persona_growth_requests.*, persona_revision_suggestions.status AS suggestion_status,
                   persona_revision_suggestions.origin AS suggestion_origin,
                   persona_growth_requests.memory_uids_json,
                   persona_revision_suggestions.trigger_memory_uids_json
            FROM persona_growth_requests
            LEFT JOIN persona_revision_suggestions
              ON persona_revision_suggestions.id = persona_growth_requests.suggestion_id
            WHERE persona_growth_requests.id = ? AND persona_growth_requests.user_id = ?
              AND persona_growth_requests.persona_id = ?
            """,
            (request_id, user_id, persona_id),
        ).fetchone())
    if not row:
        raise HTTPException(status_code=404, detail="request not found")
    if int(row.get("withdrawn_at") or 0):
        return {"request": {"id": request_id, "status": "withdrawn"}}
    if row.get("suggestion_status") == "pending" and row.get("suggestion_id"):
        dismiss_revision_suggestion(
            user_id,
            int(row["suggestion_id"]),
            decision_actor="user",
            decision_note="用户停止了这条自动相处指导",
        )
    ts = now_ts()
    if not row.get("memory_uids_json") and row.get("trigger_memory_uids_json"):
        row["memory_uids_json"] = row["trigger_memory_uids_json"]
    deactivate_guidance(
        user_id,
        persona_id,
        row,
        actor="user",
        reason="用户停止了这条相处指导",
        ts=ts,
    )
    refresh_memory_state(user_id, persona_id)
    refresh_memory_summaries(user_id, persona_id)
    return {"request": {"id": request_id, "status": "withdrawn", "updated_at": ts}}


@app.post("/api/personas/{persona_id}/growth/feedback")
def set_persona_growth_feedback(
    persona_id: int,
    req: PersonaGrowthFeedbackRequest,
    user: dict = Depends(current_user),
):
    _require_self_use_bound_persona(user, persona_id)
    reaction = req.reaction.strip()
    if reaction not in {"helpful", "needs_adjustment"}:
        raise HTTPException(status_code=400, detail="invalid growth feedback reaction")
    detail_text = scrub_identity_text(req.detail.strip())[:500] if reaction == "needs_adjustment" else ""
    user_id = int(user["id"])
    with get_db() as db:
        persona = db.execute(
            "SELECT id FROM personas WHERE id = ? AND user_id = ? AND status = 'active'",
            (persona_id, user_id),
        ).fetchone()
        if not persona:
            raise HTTPException(status_code=404, detail="persona not found")
        row = db.execute(
            """
            SELECT COALESCE(MAX(version), 0) AS version
            FROM persona_versions
            WHERE persona_id = ? AND change_type = 'sculptor_review'
            """,
            (persona_id,),
        ).fetchone()
        reviewed_version = int(row["version"] or 0)
        if not reviewed_version:
            raise HTTPException(status_code=400, detail="no confirmed growth change to review")
        ts = now_ts()
        db.execute(
            """
            INSERT INTO persona_growth_feedback (
                user_id, persona_id, reviewed_version, reaction, detail_text, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, persona_id, reviewed_version) DO UPDATE SET
                reaction = excluded.reaction,
                detail_text = excluded.detail_text,
                resolved_at = 0,
                resolved_by_user_id = NULL,
                resolution_note = '',
                updated_at = excluded.updated_at
            """,
            (user_id, persona_id, reviewed_version, reaction, detail_text, ts, ts),
        )
        feedback = dict_from_row(db.execute(
            """
            SELECT reviewed_version, reaction, detail_text, resolved_at, created_at, updated_at
            FROM persona_growth_feedback
            WHERE user_id = ? AND persona_id = ? AND reviewed_version = ?
            """,
            (user_id, persona_id, reviewed_version),
        ).fetchone())
    if reaction == "needs_adjustment" and detail_text:
        _store_persona_preference_guidance(
            persona_id,
            detail_text,
            user,
            request_origin="growth_feedback",
            source_reviewed_version=reviewed_version,
        )
        ts = now_ts()
        with get_db() as db:
            db.execute(
                """
                UPDATE persona_growth_feedback
                SET resolved_at = ?, resolved_by_user_id = NULL,
                    resolution_note = '已自动加入当前回应指导', updated_at = ?
                WHERE user_id = ? AND persona_id = ? AND reviewed_version = ?
                """,
                (ts, ts, user_id, persona_id, reviewed_version),
            )
            feedback = dict_from_row(db.execute(
                """
                SELECT reviewed_version, reaction, detail_text, resolved_at, created_at, updated_at
                FROM persona_growth_feedback
                WHERE user_id = ? AND persona_id = ? AND reviewed_version = ?
                """,
                (user_id, persona_id, reviewed_version),
            ).fetchone())
    return {"feedback": _public_growth_feedback(feedback, include_detail=True, include_version=True)}


@app.post("/api/personas/{persona_id}/growth/viewed")
def mark_persona_growth_viewed(persona_id: int, user: dict = Depends(current_user)):
    _require_self_use_bound_persona(user, persona_id)
    user_id = int(user["id"])
    with get_db() as db:
        persona = db.execute(
            "SELECT id FROM personas WHERE id = ? AND user_id = ? AND status = 'active'",
            (persona_id, user_id),
        ).fetchone()
        if not persona:
            raise HTTPException(status_code=404, detail="persona not found")
        row = db.execute(
            """
            SELECT COALESCE(MAX(version), 0) AS version
            FROM persona_versions
            WHERE persona_id = ? AND change_type = 'sculptor_review'
            """,
            (persona_id,),
        ).fetchone()
        reviewed_version = int(row["version"] or 0)
        ts = now_ts()
        db.execute(
            """
            INSERT INTO persona_growth_views (user_id, persona_id, seen_reviewed_version, viewed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, persona_id) DO UPDATE SET
                seen_reviewed_version = MAX(persona_growth_views.seen_reviewed_version, excluded.seen_reviewed_version),
                viewed_at = excluded.viewed_at
            """,
            (user_id, persona_id, reviewed_version, ts),
        )
    return {"ok": True, "persona_id": persona_id, "seen_reviewed_version": reviewed_version}


@app.patch("/api/personas/{persona_id}")
def update_persona(persona_id: int, req: PersonaUpdateRequest, user: dict = Depends(current_user)):
    _require_self_use_bound_persona(user, persona_id)
    if _self_use_public(user).get("enabled") and req.avatar_url is not None:
        raise HTTPException(status_code=400, detail="LING self-use mode uses Live2D preview/fallback fields instead of avatar_url")
    user_id = int(user["id"])
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM personas WHERE id = ? AND user_id = ? AND status = 'active'",
            (persona_id, user_id),
        ).fetchone()
    current = _public_persona(dict_from_row(row))
    if not current:
        raise HTTPException(status_code=404, detail="persona not found")

    name = scrub_identity_text(req.name.strip()) if req.name is not None else current.get("name", "")
    if req.name is not None and not name:
        raise HTTPException(status_code=400, detail="persona name cannot be empty")
    summary = scrub_identity_text(req.summary.strip()) if req.summary is not None else current.get("summary", "")
    relationship = scrub_identity_text(req.relationship.strip()) if req.relationship is not None else current.get("relationship", "")
    speaking_style = scrub_identity_text(req.speaking_style.strip()) if req.speaking_style is not None else current.get("speaking_style", "")
    appearance = scrub_identity_text(req.appearance_description) if req.appearance_description is not None else current.get("appearance_description", "")
    desired = scrub_identity_text(req.desired_image) if req.desired_image is not None else current.get("desired_image", "")
    avatar_url = _clean_avatar_url(req.avatar_url) if req.avatar_url is not None else current.get("avatar_url")
    live2d_model_id = str(req.live2d_model_id or "").strip() if req.live2d_model_id is not None else current.get("live2d_model_id", "")
    live2d_preview_url = (
        _clean_visual_asset_url(req.live2d_preview_url, "live2d_preview_url")
        if req.live2d_preview_url is not None
        else current.get("live2d_preview_url", "")
    )
    fallback_image_url = (
        _clean_visual_asset_url(req.fallback_image_url, "fallback_image_url")
        if req.fallback_image_url is not None
        else current.get("fallback_image_url", "")
    )
    voice_profile = scrub_identity_text(req.voice_profile.strip()) if req.voice_profile is not None else current.get("voice_profile", "")
    content_changed = (
        name != current.get("name", "")
        or summary != current.get("summary", "")
        or relationship != current.get("relationship", "")
        or speaking_style != current.get("speaking_style", "")
        or appearance != current.get("appearance_description", "")
        or desired != current.get("desired_image", "")
    )
    ts = now_ts()
    next_version = int(current.get("version", 1) or 1) + 1 if content_changed else int(current.get("version", 1) or 1)

    updated = dict(current)
    updated["name"] = name
    updated["summary"] = summary
    updated["relationship"] = relationship
    updated["speaking_style"] = speaking_style
    updated["appearance_description"] = appearance or ""
    updated["desired_image"] = desired or ""
    updated["avatar_url"] = avatar_url
    updated["live2d_model_id"] = live2d_model_id
    updated["live2d_preview_url"] = live2d_preview_url
    updated["fallback_image_url"] = fallback_image_url
    updated["voice_profile"] = voice_profile
    if content_changed:
        updated["prompt"] = (
            build_ling_prompt(updated) if _self_use_public(user).get("enabled") else build_prompt(updated)
        )

    with get_db() as db:
        db.execute(
            """
            UPDATE personas
            SET name = ?, summary = ?, relationship = ?, speaking_style = ?,
                avatar_url = ?, appearance_description = ?, desired_image = ?,
                live2d_model_id = ?, live2d_preview_url = ?, fallback_image_url = ?,
                voice_profile = ?, prompt = ?, version = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                updated["name"],
                updated["summary"],
                updated["relationship"],
                updated["speaking_style"],
                avatar_url,
                updated["appearance_description"],
                updated["desired_image"],
                updated["live2d_model_id"],
                updated["live2d_preview_url"],
                updated["fallback_image_url"],
                updated["voice_profile"],
                updated.get("prompt") or current.get("prompt") or "",
                next_version,
                ts,
                persona_id,
                user_id,
            ),
        )
        if content_changed:
            db.execute(
                """
                INSERT INTO persona_versions (
                    persona_id, version, name, summary, prompt, traits_json,
                    relationship, speaking_style, boundaries_json,
                    psychological_profile_json, psychological_fit_notes,
                    appearance_description, desired_image, live2d_model_id,
                    live2d_preview_url, fallback_image_url, voice_profile, growth_notes,
                    reason, change_type, change_notes_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    persona_id,
                    next_version,
                    updated["name"],
                    updated["summary"],
                    updated["prompt"],
                    json.dumps(updated.get("traits", []), ensure_ascii=False),
                    updated.get("relationship", ""),
                    updated.get("speaking_style", ""),
                    json.dumps(updated.get("boundaries", []), ensure_ascii=False),
                    json.dumps(updated.get("psychological_profile", {}), ensure_ascii=False),
                    updated.get("psychological_fit_notes", ""),
                    updated.get("appearance_description", ""),
                    updated.get("desired_image", ""),
                    updated.get("live2d_model_id", ""),
                    updated.get("live2d_preview_url", ""),
                    updated.get("fallback_image_url", ""),
                    updated.get("voice_profile", ""),
                    updated.get("growth_notes", ""),
                    "persona profile update",
                    "user_profile_update",
                    json.dumps(["用户编辑了联系人资料。"], ensure_ascii=False),
                    ts,
                ),
            )
        persona = dict_from_row(db.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone())
    public_persona = _public_persona(persona)
    public_persona["expression_preference"] = _expression_preference_public(user_id, persona_id)
    return {"persona": public_persona}


@app.patch("/api/personas/{persona_id}/expression-preference")
def update_persona_expression_preference(
    persona_id: int,
    req: ExpressionPreferenceUpdateRequest,
    user: dict = Depends(current_user),
):
    _require_self_use_bound_persona(user, persona_id)
    user_id = int(user["id"])
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM personas WHERE id = ? AND user_id = ? AND status = 'active'",
            (persona_id, user_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="persona not found")
        ts = now_ts()
        mode = _normalize_expression_mode(req.mode, req.enabled)
        enabled = 0 if mode == "off" else 1
        db.execute(
            """
            INSERT INTO expression_preferences (user_id, persona_id, enabled, mode, source_message_id, updated_at)
            VALUES (?, ?, ?, ?, NULL, ?)
            ON CONFLICT(user_id, persona_id) DO UPDATE SET
                enabled = excluded.enabled,
                mode = excluded.mode,
                source_message_id = NULL,
                updated_at = excluded.updated_at
            """,
            (user_id, persona_id, enabled, mode, ts),
        )
    return {
        "persona_id": persona_id,
        "expression_preference": _expression_preference_public(user_id, persona_id),
    }


@app.post("/api/personas/{persona_id}/avatar/generate")
def generate_persona_avatar_placeholder(
    persona_id: int,
    req: PersonaAvatarGenerateRequest,
    user: dict = Depends(current_user),
):
    if _self_use_public(user).get("enabled"):
        raise HTTPException(status_code=404, detail="LING self-use mode does not use avatar generation")
    _require_self_use_bound_persona(user, persona_id)
    user_id = int(user["id"])
    with get_db() as db:
        row = db.execute(
            "SELECT id, desired_image FROM personas WHERE id = ? AND user_id = ? AND status = 'active'",
            (persona_id, user_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="persona not found")
        if req.desired_image is not None:
            db.execute(
                """
                UPDATE personas
                SET desired_image = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (req.desired_image, now_ts(), persona_id, user_id),
            )
    return {
        "ok": False,
        "status": "reserved",
        "message": "avatar generation endpoint is reserved; image generation is not connected yet",
    }


@app.post("/api/personas/{persona_id}/delete")
def delete_persona(persona_id: int, req: PersonaDeleteRequest, user: dict = Depends(current_user)):
    if _self_use_public(user).get("enabled"):
        raise HTTPException(status_code=403, detail="LING self-use mode keeps the single companion bound.")
    user_id = int(user["id"])
    with get_db() as db:
        row = db.execute(
            "SELECT id, name FROM personas WHERE id = ? AND user_id = ? AND status = 'active'",
            (persona_id, user_id),
        ).fetchone()
        persona = dict_from_row(row)
        if not persona:
            raise HTTPException(status_code=404, detail="persona not found")
        if req.confirm_name.strip() != str(persona["name"]).strip():
            raise HTTPException(status_code=400, detail="请输入完整名字以确认删除")
        db.execute(
            """
            UPDATE personas
            SET status = 'deleted', updated_at = ?
            WHERE id = ? AND user_id = ? AND status = 'active'
            """,
            (now_ts(), persona_id, user_id),
        )
    return {"ok": True, "persona_id": persona_id, "status": "deleted"}


@app.post("/api/personas/{persona_id}/restore")
def restore_persona(persona_id: int, user: dict = Depends(current_user)):
    if _self_use_public(user).get("enabled"):
        raise HTTPException(status_code=403, detail="LING self-use mode does not restore legacy personas.")
    user_id = int(user["id"])
    with get_db() as db:
        cursor = db.execute(
            """
            UPDATE personas
            SET status = 'active', updated_at = ?
            WHERE id = ? AND user_id = ? AND status = 'deleted'
            """,
            (now_ts(), persona_id, user_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="deleted persona not found")
        persona = dict_from_row(db.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone())
    return {"persona": _public_persona(persona)}


@app.post("/api/personas/{persona_id}/purge")
def purge_persona(persona_id: int, req: PersonaDeleteRequest, user: dict = Depends(current_user)):
    if _self_use_public(user).get("enabled"):
        raise HTTPException(status_code=403, detail="LING self-use mode keeps the single companion bound.")
    user_id = int(user["id"])
    with get_db() as db:
        row = db.execute(
            "SELECT id, name, status FROM personas WHERE id = ? AND user_id = ?",
            (persona_id, user_id),
        ).fetchone()
        persona = dict_from_row(row)
        if not persona:
            raise HTTPException(status_code=404, detail="persona not found")
        if str(persona.get("status") or "") != "deleted":
            raise HTTPException(status_code=400, detail="请先软删除，再执行永久删除")
        if req.confirm_name.strip() != str(persona["name"]).strip():
            raise HTTPException(status_code=400, detail="请输入完整名字以确认永久删除")
        db.execute(
            "DELETE FROM personas WHERE id = ? AND user_id = ? AND status = 'deleted'",
            (persona_id, user_id),
        )
    return {"ok": True, "persona_id": persona_id, "status": "purged"}


@app.post("/api/personas")
def create_persona(req: PersonaCreateRequest, user: dict = Depends(current_user)):
    if _self_use_public(user).get("enabled"):
        raise HTTPException(
            status_code=403,
            detail="LING self-use mode is bound to one companion. Persona generation is disabled.",
        )
    user_id = int(user["id"])
    preferred_name = scrub_identity_text(str(req.preferred_name or "").strip())
    with get_db() as db:
        existing_names = [
            str(row["name"])
            for row in db.execute(
                "SELECT name FROM personas WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ).fetchall()
        ]
    forged = forge_persona(
        selections=_clean_selections(req.selections),
        description=req.description,
        user_profile=_get_profile(user_id),
        existing_names=existing_names,
        preferred_name=preferred_name,
    )
    if not preferred_name and str(forged.get("name") or "").strip() == "未命名":
        raise HTTPException(
            status_code=503,
            detail="这次没有取得合适的名字。可以重新生成，或者亲自给 TA 写下一个名字。",
        )

    ts = now_ts()
    with get_db() as db:
        cursor = db.execute(
            """
            INSERT INTO personas (
                user_id, name, summary, prompt, traits_json, relationship,
                speaking_style, boundaries_json, memory_profile_json,
                psychological_profile_json, psychological_fit_notes,
                appearance_description, desired_image, growth_notes,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                forged["name"],
                forged["summary"],
                forged["prompt"],
                json.dumps(forged["traits"], ensure_ascii=False),
                forged["relationship"],
                forged["speaking_style"],
                json.dumps(forged["boundaries"], ensure_ascii=False),
                json.dumps(forged.get("memory_profile", {}), ensure_ascii=False),
                json.dumps(forged.get("psychological_profile", {}), ensure_ascii=False),
                forged.get("psychological_fit_notes", ""),
                forged.get("appearance_description", ""),
                forged.get("desired_image", ""),
                forged.get("growth_notes", ""),
                ts,
                ts,
            ),
        )
        persona_id = int(cursor.lastrowid)
        db.execute(
            """
            INSERT INTO persona_versions (
                persona_id, version, name, summary, prompt, traits_json,
                relationship, speaking_style, boundaries_json,
                psychological_profile_json, psychological_fit_notes,
                appearance_description, desired_image, growth_notes,
                reason, change_type, change_notes_json, created_at
            )
            VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                persona_id,
                forged["name"],
                forged["summary"],
                forged["prompt"],
                json.dumps(forged["traits"], ensure_ascii=False),
                forged["relationship"],
                forged["speaking_style"],
                json.dumps(forged["boundaries"], ensure_ascii=False),
                json.dumps(forged.get("psychological_profile", {}), ensure_ascii=False),
                forged.get("psychological_fit_notes", ""),
                forged.get("appearance_description", ""),
                forged.get("desired_image", ""),
                forged.get("growth_notes", ""),
                "initial forge",
                "initial_forge",
                json.dumps(["初始人格创建。"], ensure_ascii=False),
                ts,
            ),
        )
        persona = dict_from_row(db.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone())

    return {"persona": _public_persona(persona)}


@app.get("/api/conversations")
def conversations(user: dict = Depends(current_user), status: str = "active"):
    if status not in {"active", "archived"}:
        raise HTTPException(status_code=400, detail="invalid conversation status")
    bound_persona_id = _self_use_bound_persona_id(user)
    if _self_use_public(user).get("enabled") and bound_persona_id is None:
        return {"conversations": []}
    persona_clause = "AND conversations.persona_id = ?" if bound_persona_id is not None else ""
    params: list[Any] = [user["id"], status]
    if bound_persona_id is not None:
        params.append(bound_persona_id)
    with get_db() as db:
        rows = db.execute(
            f"""
            SELECT conversations.*, personas.name AS persona_name, personas.avatar_url AS persona_avatar_url,
                   (
                       SELECT messages.content
                       FROM messages
                       WHERE messages.conversation_id = conversations.id
                       ORDER BY messages.id DESC
                       LIMIT 1
                   ) AS last_message,
                   (
                       SELECT messages.role
                       FROM messages
                       WHERE messages.conversation_id = conversations.id
                       ORDER BY messages.id DESC
                       LIMIT 1
                   ) AS last_message_role,
                   (
                       SELECT messages.reply_status
                       FROM messages
                       WHERE messages.conversation_id = conversations.id
                       ORDER BY messages.id DESC
                       LIMIT 1
                   ) AS last_message_reply_status,
                   (
                       SELECT COUNT(*)
                       FROM messages
                       WHERE messages.conversation_id = conversations.id
                   ) AS message_count,
                   (
                       SELECT COUNT(*)
                       FROM messages
                       WHERE messages.conversation_id = conversations.id
                         AND messages.role = 'assistant'
                         AND messages.id > conversations.last_read_message_id
                   ) AS unread_count
            FROM conversations
            JOIN personas ON personas.id = conversations.persona_id
            WHERE conversations.user_id = ?
              AND conversations.status = ?
              AND personas.status = 'active'
              {persona_clause}
            ORDER BY conversations.pinned_at DESC, conversations.updated_at DESC
            """,
            params,
        ).fetchall()
    return {"conversations": [dict_from_row(row) for row in rows]}


@app.get("/api/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: int, user: dict = Depends(current_user)):
    bound_persona_id = _self_use_bound_persona_id(user)
    if _self_use_public(user).get("enabled") and bound_persona_id is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    persona_clause = "AND conversations.persona_id = ?" if bound_persona_id is not None else ""
    params: list[Any] = [conversation_id, user["id"]]
    if bound_persona_id is not None:
        params.append(bound_persona_id)
    with get_db() as db:
        conversation = db.execute(
            f"""
            SELECT conversations.id
            FROM conversations
            JOIN personas ON personas.id = conversations.persona_id
            WHERE conversations.id = ?
              AND conversations.user_id = ?
              AND personas.status = 'active'
              {persona_clause}
            """,
            params,
        ).fetchone()
        if not conversation:
            raise HTTPException(status_code=404, detail="conversation not found")

        rows = db.execute(
            """
            SELECT id, role, content, reply_status, reply_error, client_message_id, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        ).fetchall()
        messages = [dict_from_row(row) for row in rows]
        message_ids = [int(item["id"]) for item in messages]
        expressions_by_message: dict[int, list[dict[str, Any]]] = {message_id: [] for message_id in message_ids}
        if message_ids:
            active_labels = active_expression_labels()
            placeholders = ",".join("?" for _ in message_ids)
            expression_rows = db.execute(
                f"""
                SELECT message_id, expression_type, label, source_text, created_at
                FROM message_expressions
                WHERE message_id IN ({placeholders}) AND user_id = ?
                ORDER BY id ASC
                """,
                [*message_ids, user["id"]],
            ).fetchall()
            for row in expression_rows:
                expression = dict_from_row(row)
                expression_type = str(expression.get("expression_type") or "")
                label = str(expression.get("label") or "")
                if label not in active_labels.get(expression_type, set()):
                    continue
                message_id = int(expression.pop("message_id"))
                expressions_by_message.setdefault(message_id, []).append(expression)
        for item in messages:
            item["expressions"] = expressions_by_message.get(int(item["id"]), [])
        if message_ids:
            db.execute(
                """
                UPDATE conversations
                SET last_read_message_id = ?, last_read_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (max(message_ids), now_ts(), conversation_id, user["id"]),
            )
    return {"messages": messages}


@app.post("/api/conversations/{conversation_id}/read")
def mark_conversation_read(conversation_id: int, user: dict = Depends(current_user)):
    ts = now_ts()
    bound_persona_id = _self_use_bound_persona_id(user)
    if _self_use_public(user).get("enabled") and bound_persona_id is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    persona_clause = "AND conversations.persona_id = ?" if bound_persona_id is not None else ""
    params: list[Any] = [conversation_id, user["id"]]
    if bound_persona_id is not None:
        params.append(bound_persona_id)
    with get_db() as db:
        row = db.execute(
            f"""
            SELECT conversations.id,
                   COALESCE(MAX(messages.id), 0) AS latest_message_id
            FROM conversations
            JOIN personas ON personas.id = conversations.persona_id
            LEFT JOIN messages ON messages.conversation_id = conversations.id
            WHERE conversations.id = ?
              AND conversations.user_id = ?
              AND personas.status = 'active'
              {persona_clause}
            GROUP BY conversations.id
            """,
            params,
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="conversation not found")
        latest_message_id = int(row["latest_message_id"] or 0)
        db.execute(
            """
            UPDATE conversations
            SET last_read_message_id = ?, last_read_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (latest_message_id, ts, conversation_id, user["id"]),
        )
    return {"ok": True, "conversation_id": conversation_id, "last_read_message_id": latest_message_id}


@app.patch("/api/conversations/{conversation_id}")
def update_conversation(conversation_id: int, req: ConversationUpdateRequest, user: dict = Depends(current_user)):
    allowed_status = {"active", "archived"}
    title = req.title.strip() if req.title is not None else None
    status = req.status.strip() if req.status is not None else None
    if status is not None and status not in allowed_status:
        raise HTTPException(status_code=400, detail="invalid conversation status")
    if title is not None and not title:
        raise HTTPException(status_code=400, detail="title cannot be empty")
    if title is None and status is None and req.pinned is None:
        raise HTTPException(status_code=400, detail="nothing to update")
    bound_persona_id = _self_use_bound_persona_id(user)
    if _self_use_public(user).get("enabled") and bound_persona_id is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    persona_clause = "AND persona_id = ?" if bound_persona_id is not None else ""

    fields: list[str] = []
    params: list[Any] = []
    if title is not None:
        fields.append("title = ?")
        params.append(title)
    if status is not None:
        fields.append("status = ?")
        params.append(status)
    if req.pinned is not None:
        fields.append("pinned_at = ?")
        params.append(now_ts() if req.pinned else 0)
    fields.append("updated_at = ?")
    params.append(now_ts())
    params.extend([conversation_id, user["id"]])
    if bound_persona_id is not None:
        params.append(bound_persona_id)

    with get_db() as db:
        cursor = db.execute(
            f"""
            UPDATE conversations
            SET {", ".join(fields)}
            WHERE id = ? AND user_id = ?
              {persona_clause}
              AND EXISTS (
                  SELECT 1
                  FROM personas
                  WHERE personas.id = conversations.persona_id
                    AND personas.status = 'active'
              )
            """,
            params,
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="conversation not found")
        row = db.execute(
            """
            SELECT conversations.*, personas.name AS persona_name, personas.avatar_url AS persona_avatar_url
            FROM conversations
            JOIN personas ON personas.id = conversations.persona_id
            WHERE conversations.id = ? AND personas.status = 'active'
            """,
            (conversation_id,),
        ).fetchone()
    return {"conversation": dict_from_row(row)}


@app.get("/api/group-conversations")
def group_conversations(user: dict = Depends(current_user), status: str = "active"):
    if _self_use_group_disabled(user):
        return {"group_conversations": []}
    try:
        return {"group_conversations": list_group_conversations(int(user["id"]), status)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/group-conversations")
def create_group_conversation_endpoint(req: GroupConversationCreateRequest, user: dict = Depends(current_user)):
    if _self_use_group_disabled(user):
        raise HTTPException(status_code=403, detail="LING self-use mode does not use group conversations.")
    try:
        return {
            "group_conversation": create_group_conversation(
                int(user["id"]),
                req.persona_ids,
                req.title or "",
            )
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/group-conversations/{group_conversation_id}/messages")
def group_conversation_messages(group_conversation_id: int, user: dict = Depends(current_user)):
    if _self_use_group_disabled(user):
        raise HTTPException(status_code=403, detail="LING self-use mode does not use group conversations.")
    try:
        return {"messages": group_messages(int(user["id"]), group_conversation_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/group-conversations/{group_conversation_id}/read")
def mark_group_read(group_conversation_id: int, user: dict = Depends(current_user)):
    if _self_use_group_disabled(user):
        raise HTTPException(status_code=403, detail="LING self-use mode does not use group conversations.")
    try:
        return mark_group_conversation_read(int(user["id"]), group_conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/group-conversations/{group_conversation_id}")
def patch_group_conversation(
    group_conversation_id: int,
    req: GroupConversationUpdateRequest,
    user: dict = Depends(current_user),
):
    if _self_use_group_disabled(user):
        raise HTTPException(status_code=403, detail="LING self-use mode does not use group conversations.")
    try:
        return {
            "group_conversation": update_group_conversation(
                int(user["id"]),
                group_conversation_id,
                title=req.title,
                status=req.status,
                pinned=req.pinned,
            )
        }
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@app.post("/api/group-chat")
def group_chat_endpoint(req: GroupChatRequest, user: dict = Depends(current_user)):
    if _self_use_group_disabled(user):
        raise HTTPException(status_code=403, detail="LING self-use mode does not use group conversations.")
    try:
        return group_chat(
            user_id=int(user["id"]),
            group_conversation_id=int(req.group_conversation_id),
            message=req.message,
            client_message_id=req.client_message_id,
        )
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=503, detail=exc.user_message) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="group chat service unavailable") from exc


@app.post("/api/chat")
def chat(req: ChatRequest, background_tasks: BackgroundTasks, user: dict = Depends(current_user)):
    self_use = _self_use_public(user)
    if self_use.get("enabled"):
        _require_self_use_bound_persona(user, int(req.persona_id))
        if not self_use.get("chat_enabled"):
            raise HTTPException(status_code=403, detail="LING chat is not enabled yet. Set self_use.chat_enabled: true after API setup.")
        gate = _companion_chat_gate(self_use, llm_runtime_status("chat"))
        if not gate.get("ready"):
            raise HTTPException(status_code=503, detail={
                "error": "LING chat route is not verified",
                "reason": gate.get("reason"),
                "text": gate.get("text"),
            })
    try:
        result = db_chat(
            user_id=int(user["id"]),
            persona_id=int(req.persona_id),
            conversation_id=req.conversation_id,
            message=req.message,
            retry_user_message_id=req.retry_user_message_id,
            client_message_id=req.client_message_id,
            defer_summary_refresh=True,
        )
        if (
            result.get("assistant_message_id")
            and (result.get("conversation_summary") or {}).get("scheduled")
        ):
            background_tasks.add_task(
                refresh_conversation_summary,
                user_id=int(user["id"]),
                persona_id=int(req.persona_id),
                conversation_id=int(result["conversation_id"]),
                latest_message_id=int(result["assistant_message_id"]),
            )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=503, detail=exc.user_message) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="服务暂时不可用，请稍后再试。") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="聊天服务暂时不可用，请稍后再试。") from exc


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest, background_tasks: BackgroundTasks, user: dict = Depends(current_user)):
    """Stream text deltas for the local companion while keeping normal chat persistence."""
    self_use = _self_use_public(user)
    if self_use.get("enabled"):
        _require_self_use_bound_persona(user, int(req.persona_id))
        if not self_use.get("chat_enabled"):
            raise HTTPException(status_code=403, detail="LING chat is not enabled yet. Set self_use.chat_enabled: true after API setup.")
        gate = _companion_chat_gate(self_use, llm_runtime_status("chat"))
        if not gate.get("ready"):
            raise HTTPException(status_code=503, detail={
                "error": "LING chat route is not verified",
                "reason": gate.get("reason"),
                "text": gate.get("text"),
            })

    stream_id = str(req.stream_id or uuid.uuid4().hex).strip()
    if not stream_id or len(stream_id) > 64:
        raise HTTPException(status_code=422, detail="invalid stream id")
    cancel_event = threading.Event()
    with _chat_stream_cancellations_lock:
        if stream_id in _chat_stream_cancellations:
            raise HTTPException(status_code=409, detail="chat stream id is already active")
        _chat_stream_cancellations[stream_id] = (int(user["id"]), cancel_event)

    events: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()

    def emit_delta(text: str) -> None:
        if text:
            events.put(("delta", {"text": text}))

    def run_chat() -> None:
        try:
            result = db_chat(
                user_id=int(user["id"]),
                persona_id=int(req.persona_id),
                conversation_id=req.conversation_id,
                message=req.message,
                retry_user_message_id=req.retry_user_message_id,
                client_message_id=req.client_message_id,
                defer_summary_refresh=True,
                defer_turn_enrichment=True,
                on_stream_delta=emit_delta,
                should_cancel=cancel_event.is_set,
            )
            events.put(("cancelled" if result.get("interrupted") else "final", result))
        except ValueError as exc:
            events.put(("error", {"message": str(exc), "status_code": 404}))
        except LLMProviderError as exc:
            events.put(("error", {"message": exc.user_message, "status_code": 503}))
        except RuntimeError:
            events.put(("error", {"message": "LLM service is temporarily unavailable.", "status_code": 503}))
        except Exception:
            events.put(("error", {"message": "Chat service is temporarily unavailable.", "status_code": 500}))
        finally:
            with _chat_stream_cancellations_lock:
                _chat_stream_cancellations.pop(stream_id, None)

    def event_stream():
        while True:
            event_name, payload = events.get()
            if event_name == "final" and payload.get("assistant_message_id") and (payload.get("conversation_summary") or {}).get("scheduled"):
                background_tasks.add_task(
                    refresh_conversation_summary,
                    user_id=int(user["id"]),
                    persona_id=int(req.persona_id),
                    conversation_id=int(payload["conversation_id"]),
                    latest_message_id=int(payload["assistant_message_id"]),
                )
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            yield f"event: {event_name}\ndata: {data}\n\n"
            if event_name in {"final", "cancelled", "error"}:
                break

    threading.Thread(target=run_chat, name="ling-chat-stream", daemon=True).start()
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/chat/stream/{stream_id}/cancel")
def cancel_chat_stream(stream_id: str, user: dict = Depends(current_user)):
    """Best-effort cancellation for an interrupted local companion turn."""
    with _chat_stream_cancellations_lock:
        active = _chat_stream_cancellations.get(stream_id)
        if not active or active[0] != int(user["id"]):
            return {"cancelled": False}
        active[1].set()
    return {"cancelled": True}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/admin")
def admin_index():
    return FileResponse(ADMIN_WEB_DIR / "index.html")


@app.get("/admin/admin.js")
def admin_script():
    return FileResponse(ADMIN_WEB_DIR / "admin.js")


@app.get("/admin/admin.css")
def admin_style():
    return FileResponse(ADMIN_WEB_DIR / "admin.css")


def _get_profile(user_id: int) -> dict:
    with get_db() as db:
        row = db.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
    profile = dict_from_row(row) or {}
    preferences_json = profile.pop("preferences_json", "{}")
    try:
        profile["preferences"] = json.loads(preferences_json or "{}")
    except Exception:
        profile["preferences"] = {}
    return profile


def _clean_selections(selections: dict[str, list[str]]) -> dict[str, list[str]]:
    cleaned: dict[str, list[str]] = {}
    for key, allowed in PERSONA_OPTIONS.items():
        chosen = selections.get(key, [])
        if not isinstance(chosen, list):
            chosen = []
        cleaned[key] = [item for item in chosen if item in allowed][:4]
    return cleaned


def _public_persona(persona: dict | None) -> dict:
    if not persona:
        return {}
    result = dict(persona)
    for key, default in (
        ("traits_json", "[]"),
        ("boundaries_json", "[]"),
        ("psychological_profile_json", "{}"),
        ("memory_profile_json", "{}"),
    ):
        raw = result.pop(key, default)
        try:
            result[key.removesuffix("_json")] = json.loads(raw or default)
        except Exception:
            result[key.removesuffix("_json")] = json.loads(default)
    if "change_notes_json" in result:
        try:
            result["change_notes"] = json.loads(result.pop("change_notes_json") or "[]")
        except Exception:
            result["change_notes"] = []
    return result


def _expression_preference_public(user_id: int, persona_id: int) -> dict[str, Any]:
    with get_db() as db:
        row = db.execute(
            """
            SELECT enabled, mode, source_message_id, updated_at
            FROM expression_preferences
            WHERE user_id = ? AND persona_id = ?
            """,
            (user_id, persona_id),
        ).fetchone()
    if not row:
        return {"enabled": True, "mode": "normal", "explicit": False, "updated_at": 0, "source_message_id": None}
    item = dict_from_row(row) or {}
    mode = _normalize_expression_mode(item.get("mode"), bool(int(item.get("enabled", 1) or 0)))
    return {
        "enabled": mode != "off",
        "mode": mode,
        "explicit": True,
        "updated_at": int(item.get("updated_at") or 0),
        "source_message_id": item.get("source_message_id"),
    }


def _with_expression_asset_metadata(item: dict[str, Any], asset_map: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    expression_type = str(item.get("expression_type") or "")
    label = str(item.get("label") or "")
    asset = asset_map.get((expression_type, label)) or {}
    item["asset_enabled"] = bool(asset.get("enabled", False))
    item["asset_known"] = bool(asset)
    item["asset_kind"] = asset.get("asset_kind") or "unknown"
    item["display_text"] = asset.get("display_text") or label
    item["icon"] = asset.get("icon") or ""
    item["group"] = asset.get("group") or "unknown"
    item["risk_level"] = asset.get("risk_level") or "unknown"
    item["intensity"] = int(asset.get("intensity") or 0)
    item["cooldown_turns"] = int(asset.get("cooldown_turns") or 0)
    return item


def _persona_list_item(persona: dict) -> dict:
    result = dict(persona)
    latest_version = int(result.pop("latest_reviewed_version", 0) or 0)
    latest_at = int(result.pop("latest_reviewed_at", 0) or 0)
    seen_version = int(result.pop("seen_reviewed_version", 0) or 0)
    result.pop("retry_preference_request_count", None)
    expression_enabled = result.pop("expression_enabled", None)
    expression_mode = result.pop("expression_mode", None)
    mode = _normalize_expression_mode(expression_mode, None if expression_enabled is None else bool(int(expression_enabled)))
    result["expression_preference"] = {
        "enabled": mode != "off",
        "mode": mode,
        "explicit": expression_enabled is not None,
    }
    result["growth_notice"] = (
        {
            "kind": "adaptation",
            "title": "相处方式有变化",
            "version": latest_version,
            "created_at": latest_at,
        }
        if latest_version > seen_version
        else None
    )
    result["growth_action"] = None
    return result


def _normalize_expression_mode(mode: Any, enabled: bool | None = None) -> str:
    value = str(mode or "").strip().lower()
    aliases = {
        "off": "off",
        "disabled": "off",
        "disable": "off",
        "false": "off",
        "subtle": "subtle",
        "low": "subtle",
        "less": "subtle",
        "quiet": "subtle",
        "normal": "normal",
        "on": "normal",
        "enabled": "normal",
        "true": "normal",
    }
    if value in aliases:
        return aliases[value]
    if enabled is False:
        return "off"
    return "normal"


def _public_review_highlights(previous_version: dict | None, reviewed_version: dict | None) -> list[str]:
    before = _public_persona(previous_version)
    after = _public_persona(reviewed_version)
    if not before or not after:
        return ["相处方式完成了一次轻微调整"]
    highlights: list[str] = []
    field_labels = (
        ("speaking_style", "回应方式更贴近你的偏好"),
        ("boundaries", "相处边界更加明确"),
        ("relationship", "相处定位经过确认"),
        ("psychological_fit_notes", "支持你的方式做了细微调整"),
        ("summary", "整体相处感觉做了轻微调整"),
        ("traits", "表达气质做了细微调整"),
    )
    for key, label in field_labels:
        if before.get(key) != after.get(key):
            highlights.append(label)
    return highlights[:3] or ["相处方式完成了一次轻微调整"]


def _public_growth_feedback(
    feedback: dict | None,
    *,
    include_detail: bool = False,
    include_version: bool = False,
) -> dict | None:
    if not feedback:
        return None
    public_feedback: dict[str, Any] = {"reaction": feedback.get("reaction", "")}
    if include_version:
        public_feedback["reviewed_version"] = int(feedback.get("reviewed_version") or 0)
    if include_detail:
        public_feedback["detail_text"] = feedback.get("detail_text", "")
    if feedback.get("reaction") == "needs_adjustment":
        followed_up_at = int(feedback.get("resolved_at") or 0)
        public_feedback["followup_status"] = "completed" if followed_up_at else "waiting"
        if followed_up_at:
            public_feedback["followed_up_at"] = followed_up_at
    return public_feedback


def _normalize_existing_persona_identity() -> dict[str, int]:
    changed = {"personas": 0, "persona_versions": 0}

    def scrub_list(values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        return [
            scrub_identity_text(str(item).strip())
            for item in values
            if str(item).strip() and not is_identity_polluted_boundary(item)
        ]

    with get_db() as db:
        bound_persona_ids = {
            int(row["persona_id"])
            for row in db.execute("SELECT persona_id FROM self_use_companion_bindings").fetchall()
        }
        rows = db.execute("SELECT * FROM personas").fetchall()
        for row in rows:
            persona = _public_persona(dict_from_row(row))
            for key in (
                "name",
                "summary",
                "relationship",
                "speaking_style",
                "psychological_fit_notes",
                "appearance_description",
                "desired_image",
                "growth_notes",
            ):
                persona[key] = scrub_identity_text(persona.get(key))
            persona["traits"] = scrub_list(persona.get("traits"))
            persona["boundaries"] = scrub_list(persona.get("boundaries"))
            prompt = build_ling_prompt(persona) if int(persona["id"]) in bound_persona_ids else build_prompt(persona)
            db.execute(
                """
                UPDATE personas
                SET name = ?, summary = ?, relationship = ?, speaking_style = ?,
                    traits_json = ?, boundaries_json = ?, psychological_fit_notes = ?,
                    appearance_description = ?, desired_image = ?, growth_notes = ?, prompt = ?
                WHERE id = ?
                """,
                (
                    persona.get("name", ""),
                    persona.get("summary", ""),
                    persona.get("relationship", ""),
                    persona.get("speaking_style", ""),
                    json.dumps(persona.get("traits", []), ensure_ascii=False),
                    json.dumps(persona.get("boundaries", []), ensure_ascii=False),
                    persona.get("psychological_fit_notes", ""),
                    persona.get("appearance_description", ""),
                    persona.get("desired_image", ""),
                    persona.get("growth_notes", ""),
                    prompt,
                    persona["id"],
                ),
            )
            changed["personas"] += 1

        rows = db.execute("SELECT * FROM persona_versions").fetchall()
        for row in rows:
            version = _public_persona(dict_from_row(row))
            for key in (
                "name",
                "summary",
                "relationship",
                "speaking_style",
                "psychological_fit_notes",
                "appearance_description",
                "desired_image",
                "growth_notes",
            ):
                version[key] = scrub_identity_text(version.get(key))
            version["traits"] = scrub_list(version.get("traits"))
            version["boundaries"] = scrub_list(version.get("boundaries"))
            prompt = (
                build_ling_prompt(version)
                if int(version.get("persona_id") or 0) in bound_persona_ids
                else build_prompt(version)
            )
            db.execute(
                """
                UPDATE persona_versions
                SET name = ?, summary = ?, relationship = ?, speaking_style = ?,
                    traits_json = ?, boundaries_json = ?, psychological_fit_notes = ?,
                    appearance_description = ?, desired_image = ?, growth_notes = ?, prompt = ?
                WHERE id = ?
                """,
                (
                    version.get("name", ""),
                    version.get("summary", ""),
                    version.get("relationship", ""),
                    version.get("speaking_style", ""),
                    json.dumps(version.get("traits", []), ensure_ascii=False),
                    json.dumps(version.get("boundaries", []), ensure_ascii=False),
                    version.get("psychological_fit_notes", ""),
                    version.get("appearance_description", ""),
                    version.get("desired_image", ""),
                    version.get("growth_notes", ""),
                    prompt,
                    version["id"],
                ),
            )
            changed["persona_versions"] += 1

        for table, columns in {
            "user_insights": [
                "profile_summary",
                "interaction_style",
                "emotional_patterns_json",
                "inferred_profile_json",
                "topic_model_json",
                "guidance_json",
            ],
            "conversation_summaries": ["summary_text", "key_points_json"],
            "conversations": ["summary"],
            "memories": ["text"],
            "memory_facts": ["text"],
            "memory_relations": ["subject", "predicate", "object", "text"],
            "memory_summaries": ["text", "source_uids_json"],
            "persona_revision_suggestions": ["reason", "suggestion_json", "source_context_json", "decision_note"],
            "chat_context_traces": ["context_json", "error_text"],
        }.items():
            try:
                rows = db.execute(f"SELECT rowid AS _rowid, * FROM {table}").fetchall()
            except Exception:
                continue
            table_changed = 0
            for row in rows:
                item = dict_from_row(row) or {}
                updates = {}
                for column in columns:
                    if column in item and item.get(column) is not None:
                        cleaned = scrub_identity_text(item.get(column))
                        if cleaned != item.get(column):
                            updates[column] = cleaned
                if updates:
                    set_sql = ", ".join(f"{column} = ?" for column in updates)
                    db.execute(
                        f"UPDATE {table} SET {set_sql} WHERE rowid = ?",
                        [*updates.values(), item["_rowid"]],
                    )
                    table_changed += 1
            if table_changed:
                changed[table] = table_changed

    return changed


try:
    _normalize_existing_persona_identity()
except Exception as exc:
    print("[IdentitySanitizer] persona normalization skipped:", exc)


app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
