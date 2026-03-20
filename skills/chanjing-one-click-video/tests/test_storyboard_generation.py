"""Unit tests for storyboard generation (Module D)."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
os.environ["STUB_MODE"] = "1"

from schemas import VideoPlan, ScriptResult, StoryboardResult
from storyboard import generate_storyboard


def _make_plan(scene_count: int = 5, duration_sec: int = 60) -> VideoPlan:
    return VideoPlan(
        topic="为什么现在很多老板开始重视 AI agent",
        industry="AI/企业服务",
        platform="douyin",
        style="观点型口播",
        duration_sec=duration_sec,
        audience="中小企业老板、管理者",
        core_angle="AI 不只是聊天工具",
        video_type="avatar_talking_head",
        scene_count=scene_count,
        tone="清晰直接",
        cta="思考如何把 AI 接入业务",
        use_avatar=True,
        subtitle_required=True,
        cover_required=True,
    )


def _make_script() -> ScriptResult:
    return ScriptResult(
        title="为什么老板开始重视 AI agent？",
        hook="很多老板到现在，还把 AI 当聊天工具。",
        full_script=(
            "很多老板到现在，还把 AI 当聊天工具，但真正厉害的地方，根本不在聊天。"
            "AI agent 能做的，是真正承担工作流。"
            "你真正该思考的，不是用不用 AI，而是怎么让 AI 真的去公司里干活。"
        ),
        cta="你真正该思考的，不是用不用 AI，而是怎么让 AI 真的去公司里干活。",
    )


class TestStoryboardGeneration(unittest.TestCase):

    def test_returns_storyboard_result(self):
        plan = _make_plan()
        script = _make_script()
        result = generate_storyboard(plan, script)
        self.assertIsInstance(result, StoryboardResult)

    def test_has_scenes(self):
        plan = _make_plan()
        script = _make_script()
        result = generate_storyboard(plan, script)
        self.assertGreater(len(result.scenes), 0)

    def test_each_scene_has_required_fields(self):
        plan = _make_plan()
        script = _make_script()
        result = generate_storyboard(plan, script)
        for scene in result.scenes:
            self.assertIsNotNone(scene.scene_id)
            self.assertGreater(scene.duration_sec, 0)
            self.assertTrue(scene.voiceover)
            self.assertTrue(scene.subtitle)
            self.assertTrue(scene.visual_prompt)

    def test_scene_ids_are_sequential(self):
        plan = _make_plan()
        script = _make_script()
        result = generate_storyboard(plan, script)
        ids = [s.scene_id for s in result.scenes]
        self.assertEqual(ids, list(range(1, len(ids) + 1)))

    def test_to_dict_is_serialisable(self):
        import json
        plan = _make_plan()
        script = _make_script()
        result = generate_storyboard(plan, script)
        json.dumps(result.to_dict(), ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
