from __future__ import annotations

import sys
import sqlite3
from contextlib import closing
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db_chat import _ling_final_lock, _ling_runtime_prompt, ling_rendering_rules_prompt
from app.persona_forge import build_ling_prompt
from app.persona_loader import fallback_persona
from app.sculptor import _applied_prompt


def main() -> None:
    blank = {
        "name": "澪",
        "summary": "",
        "relationship": "",
        "speaking_style": "",
        "appearance_description": "",
        "desired_image": "",
    }
    prompt = build_ling_prompt(blank)
    assert "唯一、持续存在的 AI companion" in prompt
    assert "不是人格列表中的可替换角色" in prompt
    assert "不是群聊成员" in prompt
    assert "坦诚自己是 AI companion" in prompt
    assert "未填写表示尚未确定" in prompt
    assert "用户创建的长期对话对象" not in prompt
    assert "恋人" not in prompt

    rules = ling_rendering_rules_prompt()
    assert "唯一 companion" in rules
    assert "不要伪装真人" in rules
    assert "Live2D/程序层" in rules
    assert "切换或生成其他人格成员" in rules

    runtime = _ling_runtime_prompt(blank)
    lock = _ling_final_lock(blank)
    assert "relationship: not specified" in runtime
    assert "single persistent companion named 澪" in lock
    assert "multi-persona framing" in lock

    fallback = fallback_persona()
    assert fallback.display_name == "澪"
    assert "LING 本地工作区中唯一、持续存在的 AI companion" in fallback.prompt
    assert "Project Mnemosyne" not in fallback.prompt

    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("CREATE TABLE self_use_companion_bindings (user_id INTEGER, persona_id INTEGER)")
        db.execute("INSERT INTO self_use_companion_bindings VALUES (1, 7)")
        applied = _applied_prompt(db, 1, 7, blank)
        legacy = _applied_prompt(db, 2, 8, blank)
    assert "唯一、持续存在的 AI companion" in applied
    assert "用户创建的长期对话对象" not in applied
    assert "用户创建的长期对话对象" in legacy

    print("LING single-companion prompt verification passed")


if __name__ == "__main__":
    main()
