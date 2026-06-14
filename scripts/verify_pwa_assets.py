from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"


def main() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    sw_js = (WEB_ROOT / "sw.js").read_text(encoding="utf-8")
    icon = (WEB_ROOT / "icon.svg").read_text(encoding="utf-8")
    manifest = json.loads((WEB_ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))

    assert '<link rel="manifest" href="manifest.webmanifest"' in html
    assert '<meta name="theme-color"' in html
    assert 'navigator.serviceWorker.register("/sw.js")' in app_js

    assert manifest["name"] == "LING"
    assert manifest["short_name"] == "LING"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#f5f6f8"
    assert any(item["src"] == "/icon.svg" for item in manifest["icons"])

    assert "CACHE_NAME" in sw_js
    assert 'url.pathname.startsWith("/api/")' in sw_js
    assert 'url.pathname.startsWith("/uploads/")' in sw_js
    assert 'url.pathname.startsWith("/admin")' in sw_js
    assert 'request.mode === "navigate"' in sw_js
    assert "<svg" in icon and "viewBox=\"0 0 512 512\"" in icon

    print("PWA asset verification passed")


if __name__ == "__main__":
    main()
