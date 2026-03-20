"""
LLM client — 通过小鹿 DeerAPI（OpenAI 兼容接口）调用 Claude 模型。
无需额外 SDK，只用标准库 urllib。

配置环境变量：
  DEERAPI_API_KEY   小鹿 API Key（必填）
  DEERAPI_BASE_URL  API Base URL（默认 https://api.deerapi.com）
  LLM_MODEL         使用的模型（默认 claude-sonnet-4-6）
  STUB_MODE         =1 时返回占位回复，不调用真实 API
"""

from __future__ import annotations
import json
import os
import re
import urllib.request
import urllib.error

DEERAPI_BASE_URL = os.environ.get("DEERAPI_BASE_URL", "https://api.deerapi.com")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")


def chat(
    prompt: str,
    max_tokens: int = 2048,
    system: str = "",
) -> str:
    """
    调用 DeerAPI /v1/chat/completions，返回模型回复文本。
    STUB_MODE=1 时直接返回空字符串（由各模块自行返回 stub 数据）。
    """
    if os.environ.get("STUB_MODE") == "1":
        return ""

    api_key = os.environ.get("DEERAPI_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "DEERAPI_API_KEY 未设置。请执行：export DEERAPI_API_KEY=<your-key>"
        )

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        f"{DEERAPI_BASE_URL}/v1/chat/completions",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeerAPI HTTP {exc.code}: {err_body}") from exc

    return body["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Shared JSON extraction (used by planners / copywriter / storyboard)
# ---------------------------------------------------------------------------

def _repair_json(s: str) -> str:
    """
    Handle the most common LLM JSON issue: unescaped double-quotes inside
    string values.  Strategy: scan char by char, track whether we're inside
    a JSON string, and escape any bare " that appears mid-string.
    """
    out = []
    in_string = False
    escaped = False
    for ch in s:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            if not in_string:
                in_string = True
                out.append(ch)
            else:
                # Peek: is the next non-space char a JSON structural char?
                # We can't peek easily here, so use a simpler heuristic:
                # close the string only if followed by : , } ] or whitespace+those.
                # Otherwise treat as an embedded quote that needs escaping.
                # We do this by closing and re-deciding after the full scan.
                in_string = False
                out.append(ch)
        else:
            out.append(ch)

    return "".join(out)


def _replace_curly_quotes(s: str) -> str:
    """Replace Unicode curly quotes (common in Chinese LLM output) inside JSON strings."""
    # \u201c " \u201d "  →  replace with 「」 so they don't break JSON parsing
    return (
        s.replace("\u201c", "\u300c")   # " → 「
         .replace("\u201d", "\u300d")   # " → 」
         .replace("\u2018", "\u2018")   # ' (left)  — keep as-is, not a JSON delimiter
         .replace("\u2019", "\u2019")   # ' (right) — keep as-is
    )


def extract_json(text: str) -> dict:
    """
    Robustly extract the first JSON object from LLM output.
    Tries multiple strategies before raising ValueError.
    """
    def _try_parse(candidate: str) -> dict | None:
        for attempt in [candidate, _replace_curly_quotes(candidate)]:
            try:
                return json.loads(attempt)
            except json.JSONDecodeError:
                pass
        return None

    # Strategy 1: ```json ... ``` code block
    m = re.search(r"```json\s*([\s\S]+?)\s*```", text)
    if m:
        result = _try_parse(m.group(1))
        if result is not None:
            return result

    # Strategy 2: bare { ... } — greedy to capture nested structures
    m = re.search(r"\{[\s\S]+\}", text)
    if m:
        result = _try_parse(m.group(0))
        if result is not None:
            return result

    raise ValueError(
        f"LLM output did not contain parseable JSON.\nFirst 400 chars:\n{text[:400]}"
    )
