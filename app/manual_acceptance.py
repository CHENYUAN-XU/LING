from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
RECORDABLE_CHECKS = {
    "chat_model",
    "live2d",
    "voice",
    "video_companion",
    "daily_endurance",
}


def apply_manual_acceptance(
    checks: list[dict[str, Any]],
    path: Path,
) -> dict[str, Any]:
    ledger = load_manual_acceptance(path)
    receipts = ledger.get("receipts") if isinstance(ledger.get("receipts"), dict) else {}
    accepted: list[str] = []
    stale: list[str] = []
    for check in checks:
        key = str(check.get("key") or "")
        receipt = receipts.get(key)
        if not isinstance(receipt, dict):
            continue
        current_fingerprint = acceptance_fingerprint(check)
        receipt_fingerprint = str(receipt.get("fingerprint") or "")
        receipt_public = {
            "accepted_at": int(receipt.get("accepted_at") or 0),
            "note": str(receipt.get("note") or ""),
            "current": receipt_fingerprint == current_fingerprint,
        }
        evidence = check.get("evidence") if isinstance(check.get("evidence"), dict) else {}
        check["evidence"] = {**evidence, "manual_acceptance": receipt_public}
        if check.get("status") == "manual" and receipt_public["current"]:
            check["status"] = "ready"
            check["detail"] = f"{check.get('detail')}; manually accepted at {receipt_public['accepted_at']}"
            accepted.append(key)
        elif not receipt_public["current"]:
            stale.append(key)
    return {
        "path": str(path),
        "accepted": sorted(accepted),
        "stale": sorted(stale),
        "receipt_count": len(receipts),
    }


def record_manual_acceptance(
    checks: list[dict[str, Any]],
    path: Path,
    check_key: str,
    note: str,
) -> dict[str, Any]:
    key = str(check_key or "").strip()
    if key not in RECORDABLE_CHECKS:
        raise ValueError(f"manual acceptance is not supported for: {key}")
    check = next((item for item in checks if str(item.get("key") or "") == key), None)
    if not check:
        raise ValueError(f"acceptance check not found: {key}")
    if check.get("status") != "manual":
        raise ValueError(
            f"{key} is {check.get('status')}; automated prerequisites must reach MANUAL before acceptance can be recorded"
        )
    clean_note = str(note or "").strip()
    if len(clean_note) < 4:
        raise ValueError("record a short note describing the real test that was completed")
    if len(clean_note) > 1000:
        raise ValueError("acceptance note is too long")

    ledger = load_manual_acceptance(path)
    receipts = ledger.setdefault("receipts", {})
    receipt = {
        "check": key,
        "fingerprint": acceptance_fingerprint(check),
        "accepted_at": int(time.time()),
        "note": clean_note,
    }
    receipts[key] = receipt
    ledger["schema_version"] = SCHEMA_VERSION
    ledger["updated_at"] = receipt["accepted_at"]
    _write_ledger(path, ledger)
    return dict(receipt)


def revoke_manual_acceptance(path: Path, check_key: str) -> bool:
    key = str(check_key or "").strip()
    ledger = load_manual_acceptance(path)
    receipts = ledger.get("receipts") if isinstance(ledger.get("receipts"), dict) else {}
    if key not in receipts:
        return False
    del receipts[key]
    ledger["receipts"] = receipts
    ledger["updated_at"] = int(time.time())
    _write_ledger(path, ledger)
    return True


def load_manual_acceptance(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "updated_at": 0, "receipts": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": SCHEMA_VERSION, "updated_at": 0, "receipts": {}}
    if not isinstance(value, dict) or not isinstance(value.get("receipts"), dict):
        return {"schema_version": SCHEMA_VERSION, "updated_at": 0, "receipts": {}}
    return value


def acceptance_fingerprint(check: dict[str, Any]) -> str:
    evidence = check.get("evidence") if isinstance(check.get("evidence"), dict) else {}
    stable_evidence = {key: value for key, value in evidence.items() if key != "manual_acceptance"}
    payload = {
        "key": str(check.get("key") or ""),
        "required": bool(check.get("required")),
        "evidence": stable_evidence,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
