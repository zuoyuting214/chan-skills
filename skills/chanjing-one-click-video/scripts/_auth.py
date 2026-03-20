"""
Auth helper — follows the exact same pattern used by other chan-skills.
Reads credentials from ~/.chanjing/credentials.json (or CHANJING_CONFIG_DIR).
Auto-refreshes access_token when it is within 5 minutes of expiry.
"""

from __future__ import annotations
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path


CONFIG_DIR = Path(os.environ.get("CHANJING_CONFIG_DIR", Path.home() / ".chanjing"))
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
API_BASE = os.environ.get("CHANJING_API_BASE", "https://open-api.chanjing.cc")
TOKEN_BUFFER_SECS = 300   # refresh 5 min before expiry


def _load_credentials() -> dict:
    if not CREDENTIALS_FILE.exists():
        return {}
    try:
        return json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_credentials(creds: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(
        json.dumps(creds, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _fetch_token(app_id: str, secret_key: str) -> tuple[str, int]:
    """Call /open/v1/access_token and return (token, expire_in_unix)."""
    url = f"{API_BASE}/open/v1/access_token"
    payload = json.dumps({"app_id": app_id, "secret_key": secret_key}).encode()
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode())
    if body.get("code") != 0:
        raise RuntimeError(f"Token fetch failed: {body.get('msg')}")
    d = body["data"]
    return d["access_token"], int(d["expire_in"])


def get_token() -> tuple[str | None, str | None]:
    """
    Returns (token, None) on success, or (None, error_message) on failure.
    Caller should always check the second element.
    """
    creds = _load_credentials()
    app_id = creds.get("app_id", "")
    secret_key = creds.get("secret_key", "")

    if not app_id or not secret_key:
        return None, (
            "蝉镜凭证未配置。请先运行 chanjing-credentials-guard 或执行：\n"
            "  chanjing-config --ak <ACCESS_KEY> --sk <SECRET_KEY>"
        )

    expire_in = creds.get("expire_in", 0)
    token = creds.get("access_token", "")

    if token and time.time() < expire_in - TOKEN_BUFFER_SECS:
        return token, None

    # Need to refresh
    try:
        token, expire_in = _fetch_token(app_id, secret_key)
    except Exception as exc:
        return None, f"Token 刷新失败: {exc}"

    creds["access_token"] = token
    creds["expire_in"] = expire_in
    _save_credentials(creds)
    return token, None


def api_post(path: str, payload: dict, token: str) -> dict:
    """POST to Chanjing API and return parsed response dict."""
    url = f"{API_BASE}{path}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "access_token": token,
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_get(path: str, params: dict, token: str) -> dict:
    """GET from Chanjing API and return parsed response dict."""
    from urllib.parse import urlencode
    url = f"{API_BASE}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = urllib.request.Request(
        url, method="GET",
        headers={"access_token": token},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))
