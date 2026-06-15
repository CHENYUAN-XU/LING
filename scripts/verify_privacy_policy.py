from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    from app.privacy_policy import get_privacy_policy
    import app.server as server

    policy = get_privacy_policy()
    assert policy["version"] == "2026-06-14"
    assert "LING" in policy["summary"]
    assert "Project Mnemosyne" not in policy["summary"]
    assert any("游客" in item for item in policy["retention"])
    assert any("E:\\视觉\\video-companion" in item for item in policy["user_controls"])
    assert any("不保存连续摄像头视频帧" in item for item in policy["external_boundaries"])

    response = server.privacy_policy()
    assert response["policy"]["title"] == "数据与隐私"

    doc = (PROJECT_ROOT / "docs" / "PRIVACY_AND_DATA.md").read_text(encoding="utf-8")
    assert "LING" in doc
    assert "E:\\视觉\\video-companion" in doc
    assert "后续转到其他聊天时，也应跳过重做这个外部项目" in doc

    print("Privacy policy verification passed")


if __name__ == "__main__":
    main()
