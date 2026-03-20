#!/usr/bin/env python3
"""选题 → plan → script → storyboard → render。用法见 SKILL.md 或 --help。"""

from __future__ import annotations
import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

# Make scripts importable when run from any directory
sys.path.insert(0, str(Path(__file__).parent))

from schemas import VideoRequest, WorkflowResult
from planners import generate_video_plan
from copywriter import generate_script
from storyboard import generate_storyboard
from render import render_video
from utils import get_logger, timed, is_topic_too_vague, ensure_output_dir

logger = get_logger("workflow")


def normalise_request(raw: dict) -> VideoRequest:
    """Fill in defaults for any missing optional fields."""
    defaults = {
        "industry": "",
        "platform": os.environ.get("DEFAULT_PLATFORM", "douyin"),
        "style": os.environ.get("DEFAULT_STYLE", "观点型口播"),
        "duration_sec": int(os.environ.get("DEFAULT_DURATION", "60")),
        "use_avatar": os.environ.get("DEFAULT_USE_AVATAR", "true").lower() == "true",
        "avatar_id": os.environ.get("CHANJING_AVATAR_ID", ""),
        "voice_id": os.environ.get("CHANJING_VOICE_ID", ""),
        "subtitle_required": True,
        "cover_required": True,
        "strict_validation": True,
        "allow_auto_expand_topic": False,
        "max_retry_per_step": 1,
    }
    merged = {**defaults, **{k: v for k, v in raw.items() if v is not None}}
    # Coerce types
    merged["duration_sec"] = int(merged["duration_sec"])
    merged["use_avatar"] = bool(merged["use_avatar"])
    merged["strict_validation"] = bool(merged["strict_validation"])
    merged["allow_auto_expand_topic"] = bool(merged["allow_auto_expand_topic"])
    merged["max_retry_per_step"] = max(0, int(merged["max_retry_per_step"]))
    return VideoRequest.from_dict(merged)


def run(raw_input: dict) -> WorkflowResult:
    start_time = time.perf_counter()
    debug: dict = {"steps": {}}

    ri = dict(raw_input or {})
    topic = str(ri.get("topic", "")).strip()
    ri["topic"] = topic
    strict_val = bool(ri.get("strict_validation", True))
    allow_expand = bool(ri.get("allow_auto_expand_topic", False))

    if not topic:
        return WorkflowResult(
            status="failed",
            error="选题不能为空。",
            debug={"reason": "topic_empty", "input": raw_input},
        )

    if allow_expand and is_topic_too_vague(topic):
        topic = f"{topic}（可落地的具体场景与行动建议）"
        ri["topic"] = topic

    if strict_val and is_topic_too_vague(topic):
        return WorkflowResult(
            status="failed",
            error="输入过于模糊，请至少提供一个明确选题，例如「AI agent 如何帮助家装公司获客」。",
            debug={"reason": "topic_too_vague", "input": raw_input},
        )

    logger.info("=== chanjing-one-click-video workflow start ===")
    logger.info("Input: topic=%r, platform=%s", topic, ri.get("platform", "douyin"))

    # --- Normalise ---
    request = normalise_request(ri)
    logger.info("Normalised request: %s", json.dumps(request.to_dict(), ensure_ascii=False))
    debug["normalised_request"] = request.to_dict()

    video_plan = None
    script_result = None
    storyboard_result = None
    render_result = None

    # --- Step 1: Video Plan ---
    try:
        t0 = time.perf_counter()
        video_plan = generate_video_plan(request)
        debug["steps"]["plan_sec"] = round(time.perf_counter() - t0, 2)
        logger.info("Step 1 done: video_plan scenes=%d", video_plan.scene_count)
    except Exception as exc:
        logger.error("Step 1 (plan) failed: %s\n%s", exc, traceback.format_exc())
        return WorkflowResult(
            status="failed",
            error=f"视频规划生成失败: {exc}",
            debug={**debug, "failed_step": "plan", "traceback": traceback.format_exc()},
        )

    # --- Step 2: Script ---
    try:
        t0 = time.perf_counter()
        script_result = generate_script(video_plan)
        debug["steps"]["script_sec"] = round(time.perf_counter() - t0, 2)
        logger.info("Step 2 done: script title=%r", script_result.title)
    except Exception as exc:
        logger.error("Step 2 (script) failed: %s\n%s", exc, traceback.format_exc())
        return WorkflowResult(
            status="partial",
            video_plan=video_plan.to_dict(),
            error=f"文案生成失败: {exc}",
            debug={**debug, "failed_step": "script", "traceback": traceback.format_exc()},
        )

    # --- Step 3: Storyboard ---
    try:
        t0 = time.perf_counter()
        storyboard_result = generate_storyboard(video_plan, script_result)
        debug["steps"]["storyboard_sec"] = round(time.perf_counter() - t0, 2)
        logger.info("Step 3 done: storyboard scenes=%d", len(storyboard_result.scenes))
    except Exception as exc:
        logger.error("Step 3 (storyboard) failed: %s\n%s", exc, traceback.format_exc())
        return WorkflowResult(
            status="partial",
            video_plan=video_plan.to_dict(),
            script_result=script_result.to_dict(),
            error=f"分镜生成失败: {exc}",
            debug={**debug, "failed_step": "storyboard", "traceback": traceback.format_exc()},
        )

    # Step 4: render（max_retry_per_step 仅作用于本步）
    render_result = None
    max_r = max(0, int(request.max_retry_per_step))
    for attempt in range(max_r + 1):
        try:
            t0 = time.perf_counter()
            render_result = render_video(video_plan, script_result, storyboard_result)
            debug["steps"]["render_sec"] = round(time.perf_counter() - t0, 2)
            debug["render_path"] = render_result.render_path
            if attempt:
                debug["render_attempts"] = attempt + 1
            logger.info("Step 4 done: video_url=%s", render_result.video_url)
            break
        except Exception as exc:
            logger.warning(
                "Step 4 (render) attempt %d/%d failed: %s",
                attempt + 1, max_r + 1, exc,
            )
            if attempt >= max_r:
                logger.error("Step 4 (render) failed: %s\n%s", exc, traceback.format_exc())
                return WorkflowResult(
                    status="partial",
                    video_plan=video_plan.to_dict(),
                    script_result=script_result.to_dict(),
                    storyboard_result=storyboard_result.to_dict(),
                    error=f"视频渲染失败: {exc}（文案和分镜已保留）",
                    debug={
                        **debug,
                        "failed_step": "render",
                        "traceback": traceback.format_exc(),
                    },
                )

    debug["total_sec"] = round(time.perf_counter() - start_time, 2)
    debug["scene_count"] = len(storyboard_result.scenes)

    logger.info("=== workflow complete in %.2fs ===", debug["total_sec"])

    return WorkflowResult(
        status="success",
        video_plan=video_plan.to_dict(),
        script_result=script_result.to_dict(),
        storyboard_result=storyboard_result.to_dict(),
        render_result=render_result.to_dict(),
        debug=debug,
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="chanjing-one-click-video: generate a short video from a topic",
    )
    p.add_argument("--topic", help="Video topic (选题)")
    p.add_argument("--input", help="Path to JSON input file")
    p.add_argument("--industry", default="", help="Industry vertical")
    p.add_argument("--platform", default="", help="Target platform: douyin / shipinhao / xiaohongshu")
    p.add_argument("--style", default="", help="Video style: 干货 / 观点 / 种草 / 口播")
    p.add_argument("--duration", type=int, default=0, help="Duration in seconds: 30 / 60 / 90")
    p.add_argument("--no-avatar", action="store_true", help="Disable digital avatar")
    p.add_argument(
        "--no-strict-validation",
        action="store_true",
        help="关闭选题严格校验（仍拒绝空选题）",
    )
    p.add_argument(
        "--allow-expand-topic",
        action="store_true",
        help="模糊选题时自动扩写后再校验",
    )
    p.add_argument(
        "--max-retry",
        type=int,
        default=None,
        help="渲染步骤最大重试次数（默认 1，即最多尝试 2 次）",
    )
    p.add_argument("--output", help="Write result JSON to this file path")
    p.add_argument("--pretty", action="store_true", default=True, help="Pretty-print JSON output")
    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Build raw input dict
    if args.input:
        raw_input = json.loads(Path(args.input).read_text(encoding="utf-8"))
    elif args.topic:
        raw_input = {"topic": args.topic}
    else:
        parser.print_help()
        sys.exit(1)

    # Override with CLI flags
    if args.industry:
        raw_input["industry"] = args.industry
    if args.platform:
        raw_input["platform"] = args.platform
    if args.style:
        raw_input["style"] = args.style
    if args.duration:
        raw_input["duration_sec"] = args.duration
    if args.no_avatar:
        raw_input["use_avatar"] = False
    if args.no_strict_validation:
        raw_input["strict_validation"] = False
    if args.allow_expand_topic:
        raw_input["allow_auto_expand_topic"] = True
    if args.max_retry is not None:
        raw_input["max_retry_per_step"] = max(0, args.max_retry)

    result = run(raw_input)

    indent = 2 if args.pretty else None
    output_json = result.to_json(indent=indent) if indent else json.dumps(result.to_dict(), ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        logger.info("Result written to %s", args.output)
    else:
        print(output_json)

    # Exit with non-zero if workflow failed completely
    if result.status == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
