from __future__ import annotations

import os
import hashlib
import socket
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from .config import BASE_DIR, load_config
from .database import DB_PATH
from .manual_acceptance import apply_manual_acceptance


LLM_VERIFICATION_TTL_SECONDS = 7 * 24 * 60 * 60


def acceptance_report(
    config: dict[str, Any] | None = None,
    *,
    db_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    probe_local_ports: bool = True,
    base_dir: Path | None = None,
    manual_acceptance_path: Path | None = None,
    apply_manual_receipts: bool = True,
) -> dict[str, Any]:
    cfg = config or load_config()
    database_path = Path(db_path or DB_PATH)
    env = environ if environ is not None else os.environ
    root = Path(base_dir or BASE_DIR)
    checks: list[dict[str, Any]] = []

    self_use = _section(cfg, "self_use")
    self_use_enabled = bool(self_use.get("enabled"))
    localhost_only = bool(self_use.get("require_localhost", True))
    _add(
        checks,
        "self_use_boundary",
        "ready" if self_use_enabled and localhost_only else "pending",
        True,
        "LING is local self-use and restricted to localhost"
        if self_use_enabled and localhost_only
        else "self_use.enabled and self_use.require_localhost must both be true",
    )

    owner = _owner_state(database_path, str(self_use.get("username") or ""))
    _add(
        checks,
        "single_companion_binding",
        "ready" if owner.get("bound") else "pending",
        True,
        owner.get("detail") or "stable companion binding is missing",
        evidence={key: owner.get(key) for key in ("user_id", "persona_id", "isolated_legacy_personas")},
    )
    ling_prompt = bool(owner.get("ling_prompt"))
    _add(
        checks,
        "ling_identity_prompt",
        "ready" if ling_prompt else "pending",
        True,
        "bound companion uses the LING single-companion prompt"
        if ling_prompt
        else "bound companion still has a legacy persona/chat-product prompt",
    )

    sqlite_state = _sqlite_state(database_path)
    _add(
        checks,
        "sqlite_integrity",
        "ready" if sqlite_state.get("ok") else "pending",
        True,
        sqlite_state.get("detail") or "SQLite database is unavailable",
        evidence=sqlite_state,
    )

    llm = _llm_state(cfg, database_path, env)
    _add(
        checks,
        "chat_model",
        llm["status"],
        True,
        llm["detail"],
        evidence={
            key: llm.get(key)
            for key in (
                "provider", "model", "configured", "verified", "verified_at",
                "chat_enabled", "route_fingerprint",
            )
        },
    )

    live2d = _live2d_state(cfg, owner, probe_local_ports)
    _add(checks, "live2d", live2d["status"], True, live2d["detail"], evidence=live2d["evidence"])

    voice = _voice_state(cfg, owner, env, probe_local_ports)
    _add(checks, "voice", voice["status"], True, voice["detail"], evidence=voice["evidence"])

    video = _video_state(cfg, probe_local_ports)
    _add(checks, "video_companion", video["status"], False, video["detail"], evidence=video["evidence"])

    screen = _section(cfg, "screen")
    proactive = _section(cfg, "proactive")
    consent = owner.get("consents") if isinstance(owner.get("consents"), dict) else {}
    awareness_ready = bool(screen.get("enabled") and consent.get("screen"))
    proactive_ready = bool(proactive.get("enabled") and consent.get("proactive"))
    _add(
        checks,
        "optional_awareness",
        "ready" if awareness_ready or proactive_ready else "optional",
        False,
        "screen/proactive capability is explicitly enabled and authorized"
        if awareness_ready or proactive_ready
        else "screen perception and proactive messages remain disabled or unauthorized",
        evidence={"screen": awareness_ready, "proactive": proactive_ready},
    )

    launcher_ready = all(
        (root / relative).is_file()
        for relative in (
            "scripts/start_local_server.ps1",
            "scripts/stop_local_server.ps1",
            "scripts/run_local_server.py",
        )
    )
    _add(
        checks,
        "managed_local_lifecycle",
        "ready" if launcher_ready else "pending",
        True,
        "managed start/stop runner files are present" if launcher_ready else "managed local runner files are incomplete",
    )

    backup = _backup_state(root / "data" / "backups")
    _add(checks, "local_backup", backup["status"], False, backup["detail"], evidence=backup.get("evidence"))

    _add(
        checks,
        "daily_endurance",
        "manual",
        True,
        "run a real long session covering disconnect/reconnect, sleep/wake, interruption and SQLite concurrency",
        evidence={"scope": "disconnect-reconnect-sleep-wake-interruption-sqlite"},
    )

    ledger_path = Path(manual_acceptance_path or (root / "data" / "acceptance" / "manual_acceptance.json"))
    manual_state = (
        apply_manual_acceptance(checks, ledger_path)
        if apply_manual_receipts
        else {"path": str(ledger_path), "accepted": [], "stale": [], "receipt_count": 0}
    )
    counts = {status: sum(1 for item in checks if item["status"] == status) for status in ("ready", "pending", "manual", "optional")}
    required = [item for item in checks if item["required"]]
    automated_ready = not any(item["status"] == "pending" for item in required)
    fully_accepted = automated_ready and not any(item["status"] == "manual" for item in required)
    return {
        "generated_at": int(time.time()),
        "mode": "local_self_use",
        "network_calls": False,
        "automated_ready": automated_ready,
        "fully_accepted": fully_accepted,
        "checks": checks,
        "summary": counts,
        "manual_acceptance": manual_state,
    }


def _section(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key, {})
    return value if isinstance(value, dict) else {}


def _add(
    checks: list[dict[str, Any]],
    key: str,
    status: str,
    required: bool,
    detail: str,
    *,
    evidence: dict[str, Any] | None = None,
) -> None:
    item: dict[str, Any] = {"key": key, "status": status, "required": required, "detail": detail}
    if evidence is not None:
        item["evidence"] = evidence
    checks.append(item)


def _owner_state(db_path: Path, username: str) -> dict[str, Any]:
    if not db_path.is_file():
        return {"bound": False, "detail": f"database does not exist: {db_path}"}
    try:
        with closing(sqlite3.connect(db_path)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """
                SELECT users.id AS user_id, bindings.persona_id, personas.name, personas.prompt,
                       personas.live2d_model_id, personas.live2d_preview_url,
                       personas.fallback_image_url, personas.voice_profile
                FROM users
                LEFT JOIN self_use_companion_bindings AS bindings ON bindings.user_id = users.id
                LEFT JOIN personas ON personas.id = bindings.persona_id
                WHERE users.username = ? AND users.status = 'active'
                """,
                (username,),
            ).fetchone()
            if not row or row["persona_id"] is None:
                return {"bound": False, "detail": f"owner '{username}' has no stable companion binding"}
            extra = int(
                db.execute(
                    "SELECT COUNT(*) FROM personas WHERE user_id = ? AND status = 'active' AND id <> ?",
                    (row["user_id"], row["persona_id"]),
                ).fetchone()[0]
            )
            consent_rows = db.execute(
                "SELECT consent_key, granted FROM user_consents WHERE user_id = ?",
                (row["user_id"],),
            ).fetchall()
    except (OSError, sqlite3.Error) as exc:
        return {"bound": False, "detail": f"could not inspect owner binding: {exc}"}
    result = dict(row)
    result.update(
        {
            "bound": True,
            "ling_prompt": "LING 本地工作区中唯一、持续存在的 AI companion" in str(row["prompt"] or ""),
            "isolated_legacy_personas": extra,
            "consents": {str(item["consent_key"]): bool(item["granted"]) for item in consent_rows},
            "detail": f"owner is bound to stable LING companion id {int(row['persona_id'])}"
            + (f"; {extra} legacy persona rows remain isolated" if extra else ""),
        }
    )
    return result


def _sqlite_state(db_path: Path) -> dict[str, Any]:
    if not db_path.is_file():
        return {"ok": False, "detail": f"database does not exist: {db_path}"}
    try:
        with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as db:
            quick_check = str(db.execute("PRAGMA quick_check").fetchone()[0])
            foreign_key_issues = int(db.execute("SELECT COUNT(*) FROM pragma_foreign_key_check").fetchone()[0])
            journal_mode = str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    except (OSError, sqlite3.Error) as exc:
        return {"ok": False, "detail": f"SQLite inspection failed: {exc}"}
    ok = quick_check == "ok" and foreign_key_issues == 0
    return {
        "ok": ok,
        "quick_check": quick_check,
        "foreign_key_issues": foreign_key_issues,
        "journal_mode": journal_mode,
        "detail": "SQLite quick check and foreign-key check passed" if ok else "SQLite integrity checks need attention",
    }


def _llm_state(config: dict[str, Any], db_path: Path, env: Mapping[str, str]) -> dict[str, Any]:
    route = dict(_section(config, "llm_routes").get("default") or _section(config, "llm"))
    chat_route = _section(config, "llm_routes").get("chat")
    if isinstance(chat_route, dict):
        route.update(chat_route)
    provider = str(route.get("provider") or "").strip().lower()
    model = str(route.get("model") or "").strip()
    base_url = str(route.get("base_url") or "").rstrip("/")
    api_key_env = str(route.get("api_key_env") or "").strip()
    configured = bool(provider and model and (provider == "ollama" or not api_key_env or env.get(api_key_env)))
    verified = False
    checked_at = 0
    route_fingerprint = _llm_route_fingerprint(provider, model, base_url, api_key_env, str(env.get(api_key_env) or ""))
    if configured and db_path.is_file():
        try:
            with closing(sqlite3.connect(db_path)) as db:
                row = db.execute(
                    """
                    SELECT state, checked_at FROM llm_route_verifications
                    WHERE route_key = ?
                    """,
                    (route_fingerprint,),
                ).fetchone()
                checked_at = int(row[1] or 0) if row else 0
                verified = bool(
                    row
                    and str(row[0]) == "verified"
                    and checked_at > 0
                    and int(time.time()) - checked_at <= LLM_VERIFICATION_TTL_SECONDS
                )
        except sqlite3.Error:
            verified = False
    chat_enabled = bool(_section(config, "self_use").get("chat_enabled"))
    if not configured:
        status, detail = "pending", f"chat route is not configured; missing {api_key_env or 'provider/model'}"
    elif not verified:
        status, detail = "pending", "chat route is configured but has not passed an explicit local probe"
    elif not chat_enabled:
        status, detail = "pending", "chat route is verified but the self-use chat gate is still disabled"
    else:
        status, detail = "manual", "chat route and gate are ready; complete a real reply and memory-continuity observation"
    return {
        "status": status,
        "detail": detail,
        "provider": provider,
        "model": model,
        "configured": configured,
        "verified": verified,
        "verified_at": checked_at,
        "chat_enabled": chat_enabled,
        "route_fingerprint": route_fingerprint,
    }


def _llm_route_fingerprint(provider: str, model: str, base_url: str, api_key_env: str, api_key: str) -> str:
    key_fingerprint = hashlib.sha256(str(api_key or "").encode("utf-8")).hexdigest()[:16]
    material = "|".join((provider, model, base_url, api_key_env, key_fingerprint))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _live2d_state(config: dict[str, Any], owner: dict[str, Any], probe: bool) -> dict[str, Any]:
    live2d = _section(config, "live2d")
    enabled = bool(live2d.get("enabled"))
    model_id = str(owner.get("live2d_model_id") or "").strip()
    endpoint = str(live2d.get("vts_ws_url") or "")
    reachable = _endpoint_reachable(endpoint) if probe and enabled else False
    evidence = {"enabled": enabled, "model_id": model_id, "endpoint": endpoint, "reachable": reachable}
    if not enabled:
        return {"status": "pending", "detail": "Live2D is disabled", "evidence": evidence}
    if not model_id:
        return {"status": "pending", "detail": "no VTube Studio model is bound to the companion", "evidence": evidence}
    if probe and not reachable:
        return {"status": "pending", "detail": "VTube Studio endpoint is not reachable", "evidence": evidence}
    return {
        "status": "manual",
        "detail": "Live2D prerequisites are present; verify authorization, restart reconnect and real actions",
        "evidence": evidence,
    }


def _voice_state(config: dict[str, Any], owner: dict[str, Any], env: Mapping[str, str], probe: bool = True) -> dict[str, Any]:
    voice = _section(config, "voice")
    enabled = bool(voice.get("enabled"))
    provider = str(voice.get("tts_provider") or "").strip().lower()
    voice_profile = str(owner.get("voice_profile") or "").strip()
    api_key_env = str(voice.get("api_key_env") or "").strip()
    api_key_env = "" if provider == "local_http" else (api_key_env or "OPENAI_API_KEY")
    key_present = bool(not api_key_env or env.get(api_key_env))
    evidence = {
        "enabled": enabled,
        "provider": provider,
        "voice_profile": voice_profile,
        "api_key_env": api_key_env,
        "api_key_present": key_present,
    }
    if provider == "edge":
        return {"status": "pending", "detail": "Edge TTS is not allowed for LING", "evidence": evidence}
    if not enabled:
        return {"status": "pending", "detail": "voice is disabled", "evidence": evidence}
    if not voice_profile:
        return {"status": "pending", "detail": "no actual voice profile is bound to the companion", "evidence": evidence}
    if provider not in {"local_http", "openai_tts"}:
        return {"status": "pending", "detail": f"unsupported TTS provider: {provider}", "evidence": evidence}
    if provider == "local_http":
        endpoint = str(voice.get("local_base_url") or "http://127.0.0.1:9881")
        evidence["endpoint"] = endpoint
        if probe and not _endpoint_reachable(endpoint):
            return {"status": "pending", "detail": "local voice service is not reachable; start ling-local-voice", "evidence": evidence}
    if not key_present:
        return {"status": "pending", "detail": f"missing voice API key environment variable: {api_key_env}", "evidence": evidence}
    return {
        "status": "manual",
        "detail": "voice prerequisites are present; verify real audio, interruption and Talk/Idle timing",
        "evidence": evidence,
    }


def _video_state(config: dict[str, Any], probe: bool) -> dict[str, Any]:
    video = _section(config, "video_companion")
    enabled = bool(video.get("enabled"))
    project_path = Path(str(video.get("project_path") or ""))
    endpoint = str(video.get("base_url") or "")
    path_exists = project_path.is_dir()
    reachable = _endpoint_reachable(endpoint) if probe and enabled else False
    evidence = {"enabled": enabled, "project_path_exists": path_exists, "endpoint": endpoint, "reachable": reachable}
    if not enabled:
        return {"status": "optional", "detail": "external Video Companion is disabled", "evidence": evidence}
    if not path_exists or (probe and not reachable):
        return {"status": "pending", "detail": "external Video Companion is enabled but not locally ready", "evidence": evidence}
    return {
        "status": "manual",
        "detail": "external Video Companion is reachable; verify a real authorized device session and summary writeback",
        "evidence": evidence,
    }


def _backup_state(directory: Path) -> dict[str, Any]:
    backups = sorted(directory.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True) if directory.is_dir() else []
    if not backups:
        return {"status": "optional", "detail": "no local backup zip exists yet", "evidence": {"latest": None}}
    latest = backups[0]
    age_hours = max(0.0, (time.time() - latest.stat().st_mtime) / 3600)
    return {
        "status": "ready",
        "detail": f"latest local backup is {age_hours:.1f} hours old",
        "evidence": {"latest": str(latest), "age_hours": round(age_hours, 1)},
    }


def _endpoint_reachable(url: str, timeout: float = 0.25) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname
    try:
        port = parsed.port or (80 if parsed.scheme in {"http", "ws"} else 443)
    except ValueError:
        return False
    if not host or port is None or host not in {"127.0.0.1", "localhost", "::1"}:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
