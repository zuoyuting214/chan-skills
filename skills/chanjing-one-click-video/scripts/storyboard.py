"""
Module D: Storyboard Generator
Splits the script into scenes with timing, visual prompts, and avatar flags.
"""

from __future__ import annotations
import json
import os
from pathlib import Path

from schemas import VideoPlan, ScriptResult, Scene, StoryboardResult
from utils import get_logger, timed
import _llm

logger = get_logger("storyboard")

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def _load_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def _stub_storyboard_response() -> str:
    return json.dumps({
        "scenes": [
            {
                "scene_id": 1,
                "duration_sec": 8,
                "voiceover": "很多老板到现在，还把 AI 当聊天工具，但真正厉害的地方，根本不在聊天。",
                "subtitle": "很多老板到现在，还把 AI 当聊天工具。",
                "visual_prompt": "数字人正面口播，简洁商务背景，字幕清晰",
                "use_avatar": True,
            },
            {
                "scene_id": 2,
                "duration_sec": 12,
                "voiceover": "AI agent 能做的，是真正承担工作流——比如自动跟进销售线索、自动生成报告、自动处理客服对话。",
                "subtitle": "AI agent 能真正承担工作流。",
                "visual_prompt": "数字人口播，配合文字动效展示工作流",
                "use_avatar": True,
            },
            {
                "scene_id": 3,
                "duration_sec": 12,
                "voiceover": "它不需要你手把手指挥，它能判断、能决策、能行动。",
                "subtitle": "它能判断、决策、行动。",
                "visual_prompt": "数字人口播，强调关键词动效",
                "use_avatar": True,
            },
            {
                "scene_id": 4,
                "duration_sec": 14,
                "voiceover": "这就是为什么越来越多的老板开始认真对待 AI agent——不是因为潮流，而是因为它真的能替你的团队干活。",
                "subtitle": "它真的能替你的团队干活。",
                "visual_prompt": "数字人口播，商务风格背景",
                "use_avatar": True,
            },
            {
                "scene_id": 5,
                "duration_sec": 10,
                "voiceover": "你真正该思考的，不是用不用 AI，而是怎么让 AI 真的去公司里干活。",
                "subtitle": "怎么让 AI 真的去公司里干活？",
                "visual_prompt": "数字人口播，结尾 CTA 强调",
                "use_avatar": True,
            },
        ]
    }, ensure_ascii=False)


_extract_json = _llm.extract_json


def generate_storyboard(plan: VideoPlan, script: ScriptResult) -> StoryboardResult:
    """Divide the script into N scenes, each with timing and visual guidance."""
    if os.environ.get("STUB_MODE") == "1":
        raw = _stub_storyboard_response()
    else:
        template = _load_template("storyboard_prompt.md")
        prompt = template.format(
            topic=plan.topic,
            platform=plan.platform,
            duration_sec=plan.duration_sec,
            scene_count=plan.scene_count,
            scene_count_minus_1=max(plan.scene_count - 1, 2),
            style=plan.style,
            tone=plan.tone,
            title=script.title,
            hook=script.hook,
            full_script=script.full_script,
            cta=script.cta,
        )
        with timed("generate_storyboard (LLM)", logger):
            raw = _llm.chat(prompt, max_tokens=2048)

    logger.debug("LLM storyboard raw output: %s", raw[:400])
    data = _extract_json(raw)

    scenes = []
    for s in data.get("scenes", []):
        scenes.append(Scene(
            scene_id=s["scene_id"],
            duration_sec=s["duration_sec"],
            voiceover=s["voiceover"],
            subtitle=s["subtitle"],
            visual_prompt=s["visual_prompt"],
            use_avatar=s.get("use_avatar", plan.use_avatar),
        ))

    result = StoryboardResult(scenes=scenes)
    total_duration = sum(s.duration_sec for s in scenes)
    logger.info("Storyboard generated: %d scenes, total=%ds", len(scenes), total_duration)
    return result
