"""分镜生成（本地规则，含 DH/AI 镜头分配）。"""

from __future__ import annotations
import json
import os

from schemas import VideoPlan, ScriptResult, Scene, StoryboardResult
from utils import get_logger

logger = get_logger("storyboard")

BROLL_VOICEOVER_MAX_CHARS = int(os.environ.get("BROLL_VOICEOVER_MAX_CHARS", "22"))

# B-roll 文生图/图生视频：出现人物时的默认族裔与场景（写入每条提示，避免模型默认欧美脸）
_BROLL_IF_PEOPLE_ZH = (
    "若画面中出现人物，须为中国人形象（东亚面孔），着装与场景符合国内日常，避免欧美模特脸。"
)
_BROLL_IF_PEOPLE_EN = (
    "If any people appear: Chinese ethnicity, natural East Asian faces, everyday Chinese context; "
    "avoid Western model aesthetics."
)


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
                "image_prompt": "",
                "i2v_prompt": "",
            },
            {
                "scene_id": 2,
                "duration_sec": 12,
                "voiceover": "AI agent 能做的，是真正承担工作流——比如自动跟进销售线索、自动生成报告、自动处理客服对话。",
                "subtitle": "AI agent 能真正承担工作流。",
                "visual_prompt": "Slow pan, office workflow screens, documentary, vertical 9:16, no text",
                "use_avatar": False,
                "image_prompt": "现代办公室，数据屏幕，商务氛围，竖构图，无文字，若有职员为中国人日常形象",
                "i2v_prompt": "Slow pan across modern office displays, subtle motion, warm light, vertical 9:16, no text, Chinese staff if any people",
            },
            {
                "scene_id": 3,
                "duration_sec": 12,
                "voiceover": "它不需要你手把手指挥，它能判断、能决策、能行动。",
                "subtitle": "它能判断、决策、行动。",
                "visual_prompt": "数字人口播，强调关键词动效",
                "use_avatar": True,
                "image_prompt": "",
                "i2v_prompt": "",
            },
            {
                "scene_id": 4,
                "duration_sec": 14,
                "voiceover": "这就是为什么越来越多的老板开始认真对待 AI agent——不是因为潮流，而是因为它真的能替你的团队干活。",
                "subtitle": "它真的能替你的团队干活。",
                "visual_prompt": "Gentle push-in, teamwork silhouette, cinematic, vertical 9:16, no text",
                "use_avatar": False,
                "image_prompt": "团队协作剪影，科技感环境，竖构图，无文字，避免正脸，人物轮廓默认中国人身形着装",
                "i2v_prompt": "Gentle dolly-in, Chinese team silhouettes collaborating, cool tech accents, vertical 9:16, no text, no faces to camera",
            },
            {
                "scene_id": 5,
                "duration_sec": 10,
                "voiceover": "你真正该思考的，不是用不用 AI，而是怎么让 AI 真的去公司里干活。",
                "subtitle": "怎么让 AI 真的去公司里干活？",
                "visual_prompt": "数字人口播，结尾 CTA 强调",
                "use_avatar": True,
                "image_prompt": "",
                "i2v_prompt": "",
            },
        ]
    }, ensure_ascii=False)


def _split_text_evenly(text: str, parts: int) -> list[str]:
    cleaned = text.replace("\n", "").strip()
    if not cleaned:
        return [""] * parts
    n = max(parts, 1)
    step = max(len(cleaned) // n, 1)
    chunks = []
    start = 0
    for i in range(n - 1):
        end = min(start + step, len(cleaned))
        chunks.append(cleaned[start:end])
        start = end
    chunks.append(cleaned[start:])
    return chunks


def _is_dh_scene(scene_id: int, scene_count: int, use_avatar: bool) -> bool:
    if not use_avatar:
        return False
    return scene_id == 1 or scene_id == scene_count or scene_id % 2 == 1


def _rebalance_broll_voiceover(
    chunks: list[str],
    scene_count: int,
    use_avatar: bool,
    max_broll_chars: int,
) -> None:
    """把 B-roll 段口播压在 max_broll_chars 内，溢出并入下一段（或上一段）。"""
    if not use_avatar or max_broll_chars < 8:
        return
    safety = 0
    while safety < 500:
        safety += 1
        changed = False
        for i in range(scene_count):
            sid = i + 1
            if _is_dh_scene(sid, scene_count, use_avatar):
                continue
            if len(chunks[i]) <= max_broll_chars:
                continue
            excess = chunks[i][max_broll_chars:]
            chunks[i] = chunks[i][:max_broll_chars]
            changed = True
            if i + 1 < scene_count:
                chunks[i + 1] = excess + chunks[i + 1]
            elif i > 0:
                chunks[i - 1] = chunks[i - 1] + excess
        if not changed:
            break


def _broll_slot_index(scene_id: int) -> int:
    """第 2、4、6…镜依次为 0、1、2…"""
    return max(0, scene_id // 2 - 1)


def _build_broll_prompts(
    plan: VideoPlan,
    voiceover: str,
    scene_id: int,
) -> tuple[str, str, str]:
    """返回 (image_prompt, i2v_prompt, visual_prompt 摘要)."""
    slot = _broll_slot_index(scene_id)
    snippet = (voiceover or "")[:28]
    image_prompt = (
        f"主题：{plan.topic}。配合口播画面：{snippet}。"
        f"竖屏9:16，{plan.style}气质，纪实感，无角标无字幕；非必要避免人物正脸特写。"
        f"{_BROLL_IF_PEOPLE_ZH}"
    )
    motions = [
        (
            "Slow cinematic pan, natural ambient motion, soft documentary lighting, "
            "vertical 9:16, no text, no readable logos"
        ),
        (
            "Gentle handheld drift, shallow depth of field, calm professional mood, "
            "vertical 9:16, no text, avoid faces toward camera"
        ),
        (
            "Subtle parallax from foreground object, background softly moving, "
            "vertical 9:16, no text, environmental storytelling"
        ),
    ]
    i2v_prompt = f"{motions[slot % len(motions)]} {_BROLL_IF_PEOPLE_EN}"
    visual_prompt = f"B-roll English motion: {i2v_prompt}"
    return image_prompt, i2v_prompt, visual_prompt


def _local_storyboard_response(plan: VideoPlan, script: ScriptResult) -> str:
    scene_count = max(4, min(6, int(plan.scene_count or 5)))
    chunks = _split_text_evenly(script.full_script, scene_count)
    _rebalance_broll_voiceover(
        chunks, scene_count, plan.use_avatar, BROLL_VOICEOVER_MAX_CHARS,
    )

    durations = [plan.duration_sec // scene_count] * scene_count
    durations[-1] += plan.duration_sec - sum(durations)

    scenes = []
    for i in range(scene_count):
        scene_id = i + 1
        use_avatar = _is_dh_scene(scene_id, scene_count, plan.use_avatar)
        vo = chunks[i]
        subtitle = vo[:24] + ("..." if len(vo) > 24 else "")
        if use_avatar:
            image_prompt = ""
            i2v_prompt = ""
            visual_prompt = (
                f"数字人口播，围绕{plan.topic}，{plan.style}风格，信息清晰、字幕可读"
            )
        else:
            image_prompt, i2v_prompt, visual_prompt = _build_broll_prompts(
                plan, vo, scene_id,
            )
        scenes.append({
            "scene_id": scene_id,
            "duration_sec": max(5, durations[i]),
            "voiceover": vo,
            "subtitle": subtitle,
            "visual_prompt": visual_prompt,
            "image_prompt": image_prompt,
            "i2v_prompt": i2v_prompt,
            "use_avatar": use_avatar,
        })
    return json.dumps({"scenes": scenes}, ensure_ascii=False)


def generate_storyboard(plan: VideoPlan, script: ScriptResult) -> StoryboardResult:
    """Divide the script into N scenes, each with timing and visual guidance."""
    if os.environ.get("STUB_MODE") == "1":
        raw = _stub_storyboard_response()
    else:
        raw = _local_storyboard_response(plan, script)

    logger.debug("Local storyboard raw output: %s", raw[:400])
    data = json.loads(raw)

    scenes = []
    for s in data.get("scenes", []):
        scenes.append(Scene(
            scene_id=s["scene_id"],
            duration_sec=s["duration_sec"],
            voiceover=s["voiceover"],
            subtitle=s["subtitle"],
            visual_prompt=s["visual_prompt"],
            use_avatar=s.get("use_avatar", plan.use_avatar),
            image_prompt=s.get("image_prompt", ""),
            i2v_prompt=s.get("i2v_prompt", ""),
        ))

    result = StoryboardResult(scenes=scenes)
    total_duration = sum(s.duration_sec for s in scenes)
    logger.info("Storyboard generated: %d scenes, total=%ds", len(scenes), total_duration)
    return result
