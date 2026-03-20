"""
Module B: Video Plan Generator
Calls LLM (via DeerAPI) to produce a structured video_plan from the user request.
"""

from __future__ import annotations
import json
import os
from pathlib import Path

from schemas import VideoRequest, VideoPlan
from utils import get_logger, timed
import _llm

logger = get_logger("planners")

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def _load_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def _stub_plan_response() -> str:
    return json.dumps({
        "audience": "中小企业老板、管理者",
        "core_angle": "AI 不只是聊天工具，而是可以直接承担企业工作流",
        "video_type": "avatar_talking_head",
        "scene_count": 5,
        "tone": "清晰、直接、像创始人随口分享",
        "cta": "引导用户思考如何把 AI 真正接入业务流程",
    }, ensure_ascii=False)


_extract_json = _llm.extract_json


def generate_video_plan(request: VideoRequest) -> VideoPlan:
    """Given a normalised VideoRequest, produce a VideoPlan using LLM."""
    if os.environ.get("STUB_MODE") == "1":
        raw = _stub_plan_response()
    else:
        template = _load_template("plan_prompt.md")
        prompt = template.format(
            topic=request.topic,
            industry=request.industry or "通用",
            platform=request.platform,
            style=request.style,
            duration_sec=request.duration_sec,
            use_avatar=request.use_avatar,
        )
        with timed("generate_video_plan (LLM)", logger):
            raw = _llm.chat(prompt, max_tokens=1024)

    logger.debug("LLM plan raw output: %s", raw[:500])
    enrichment = _extract_json(raw)

    plan = VideoPlan(
        topic=request.topic,
        industry=request.industry,
        platform=request.platform,
        style=request.style,
        duration_sec=request.duration_sec,
        audience=enrichment.get("audience", ""),
        core_angle=enrichment.get("core_angle", ""),
        video_type=enrichment.get("video_type", "avatar_talking_head"),
        scene_count=enrichment.get("scene_count", 5),
        tone=enrichment.get("tone", ""),
        cta=enrichment.get("cta", ""),
        use_avatar=request.use_avatar,
        subtitle_required=request.subtitle_required,
        cover_required=request.cover_required,
        avatar_id=request.avatar_id,
        voice_id=request.voice_id,
    )
    logger.info("Video plan generated: %d scenes, type=%s", plan.scene_count, plan.video_type)
    return plan
