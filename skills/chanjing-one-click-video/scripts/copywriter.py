"""
Module C: Script / Copywriting Generator
Produces title, hook, full voiceover script, and CTA from the video plan.
"""

from __future__ import annotations
import json
import os
from pathlib import Path

from schemas import VideoPlan, ScriptResult
from utils import get_logger, timed
import _llm

logger = get_logger("copywriter")

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def _load_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def _stub_script_response() -> str:
    return json.dumps({
        "title": "为什么现在很多老板，开始重新看 AI agent？",
        "hook": "很多老板到现在，还把 AI 当聊天工具，但真正厉害的地方，根本不在聊天。",
        "full_script": (
            "很多老板到现在，还把 AI 当聊天工具，但真正厉害的地方，根本不在聊天。"
            "AI agent 能做的，是真正承担工作流——比如自动跟进销售线索、自动生成报告、自动处理客服对话。"
            "它不需要你手把手指挥，它能判断、能决策、能行动。"
            "这就是为什么越来越多的老板开始认真对待 AI agent——不是因为潮流，"
            "而是因为它真的能替你的团队干活。"
            "你真正该思考的，不是用不用 AI，而是怎么让 AI 真的去公司里干活。"
        ),
        "cta": "你真正该思考的，不是用不用 AI，而是怎么让 AI 真的去公司里干活。",
    }, ensure_ascii=False)


_extract_json = _llm.extract_json


def generate_script(plan: VideoPlan) -> ScriptResult:
    """Generate a complete voiceover script from the video plan."""
    if os.environ.get("STUB_MODE") == "1":
        raw = _stub_script_response()
    else:
        template = _load_template("script_prompt.md")
        prompt = template.format(
            topic=plan.topic,
            industry=plan.industry or "通用",
            platform=plan.platform,
            style=plan.style,
            duration_sec=plan.duration_sec,
            audience=plan.audience,
            core_angle=plan.core_angle,
            tone=plan.tone,
            cta=plan.cta,
            scene_count=plan.scene_count,
        )
        with timed("generate_script (LLM)", logger):
            raw = _llm.chat(prompt, max_tokens=2048)

    logger.debug("LLM script raw output: %s", raw[:300])
    data = _extract_json(raw)

    result = ScriptResult(
        title=data.get("title", ""),
        hook=data.get("hook", ""),
        full_script=data.get("full_script", ""),
        cta=data.get("cta", ""),
    )
    logger.info("Script generated: title=%r, length=%d chars", result.title, len(result.full_script))
    return result
