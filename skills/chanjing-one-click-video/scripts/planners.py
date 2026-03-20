"""video_plan 生成（本地规则）。"""

from __future__ import annotations
import json
import os
from schemas import VideoRequest, VideoPlan
from utils import get_logger

logger = get_logger("planners")


def _stub_plan_response() -> str:
    return json.dumps({
        "audience": "中小企业老板、管理者",
        "core_angle": "AI 不只是聊天工具，而是可以直接承担企业工作流",
        "video_type": "avatar_talking_head",
        "scene_count": 5,
        "tone": "清晰、直接、像创始人随口分享",
        "cta": "引导用户思考如何把 AI 真正接入业务流程",
    }, ensure_ascii=False)


def _local_plan_response(request: VideoRequest) -> str:
    scene_count = 5 if request.duration_sec >= 50 else 4
    angle = f"{request.topic}的落地价值与可执行路径"
    return json.dumps({
        "audience": f"{request.industry or '通用行业'}从业者、业务负责人",
        "core_angle": angle,
        "video_type": "avatar_talking_head" if request.use_avatar else "mixed_dh_ai",
        "scene_count": scene_count,
        "tone": "清晰、专业、可执行",
        "cta": "给出一个可立刻落地的小步骤，推动用户行动",
    }, ensure_ascii=False)


def generate_video_plan(request: VideoRequest) -> VideoPlan:
    """由规范化请求生成 VideoPlan（本地）。"""
    if os.environ.get("STUB_MODE") == "1":
        raw = _stub_plan_response()
    else:
        raw = _local_plan_response(request)

    logger.debug("Local plan raw output: %s", raw[:500])
    enrichment = json.loads(raw)

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
