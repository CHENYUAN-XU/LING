from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .config import BASE_DIR, load_config


PERSONAS_DIR = BASE_DIR / "personas"

FALLBACK_PERSONA_PROMPT = """你是澪，LING 本地工作区中唯一、持续存在的 AI companion。

当前资料尚未加载时保持中性，不补写人格模板、关系标签或虚构经历。
可以坦诚自己是 AI companion，不伪装真人，也不声称拥有现实身体或未授权权限。
等待工作区恢复后，再依据真实对话、明确反馈和长期记忆继续回应。"""


@dataclass(frozen=True)
class Persona:
    name: str
    prompt: str
    profile: dict[str, Any]

    @property
    def display_name(self) -> str:
        return str(self.profile.get("name") or self.name)


def load_persona(persona_name: str) -> Persona:
    persona_dir = PERSONAS_DIR / persona_name
    if not persona_dir.exists():
        raise FileNotFoundError(f"Persona '{persona_name}' not found in {PERSONAS_DIR}")

    prompt_path = persona_dir / "persona.txt"
    profile_path = persona_dir / "profile.json"

    if not prompt_path.exists():
        raise FileNotFoundError(f"Missing persona prompt: {prompt_path}")

    prompt = prompt_path.read_text(encoding="utf-8").strip()
    profile: dict[str, Any] = {}

    if profile_path.exists():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if not isinstance(profile, dict):
            raise ValueError(f"{profile_path} must contain a JSON object")

    return Persona(name=persona_name, prompt=prompt, profile=profile)


def load_active_persona() -> Persona:
    config = load_config()
    persona_name = str(config.get("active_persona") or "").strip()
    if not persona_name:
        return fallback_persona()
    try:
        return load_persona(persona_name)
    except FileNotFoundError:
        return fallback_persona()


def list_personas() -> list[dict[str, str]]:
    personas: list[dict[str, str]] = []
    if not PERSONAS_DIR.exists():
        return personas

    for persona_dir in sorted(path for path in PERSONAS_DIR.iterdir() if path.is_dir()):
        try:
            persona = load_persona(persona_dir.name)
            personas.append({"id": persona.name, "name": persona.display_name})
        except Exception:
            personas.append({"id": persona_dir.name, "name": persona_dir.name})

    return personas


def fallback_persona() -> Persona:
    return Persona(
        name="ling",
        prompt=FALLBACK_PERSONA_PROMPT,
        profile={"name": "澪", "source": "fallback"},
    )
