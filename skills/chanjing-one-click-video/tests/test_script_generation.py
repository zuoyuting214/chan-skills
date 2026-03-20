"""Unit tests for script / copywriting generation (Module C)."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
os.environ["STUB_MODE"] = "1"

from schemas import VideoPlan, ScriptResult
from copywriter import generate_script


def _make_plan(**kwargs) -> VideoPlan:
    defaults = dict(
        topic="为什么现在很多老板开始重视 AI agent",
        industry="AI/企业服务",
        platform="douyin",
        style="观点型口播",
        duration_sec=60,
        audience="中小企业老板、管理者",
        core_angle="AI 不只是聊天工具，而是可以直接承担企业工作流",
        video_type="avatar_talking_head",
        scene_count=5,
        tone="清晰、直接、像创始人随口分享",
        cta="引导用户思考如何把 AI 真正接入业务流程",
        use_avatar=True,
        subtitle_required=True,
        cover_required=True,
    )
    defaults.update(kwargs)
    return VideoPlan(**defaults)


class TestScriptGeneration(unittest.TestCase):

    def test_returns_script_result(self):
        plan = _make_plan()
        result = generate_script(plan)
        self.assertIsInstance(result, ScriptResult)

    def test_script_has_all_fields(self):
        plan = _make_plan()
        result = generate_script(plan)
        self.assertTrue(result.title)
        self.assertTrue(result.hook)
        self.assertTrue(result.full_script)
        self.assertTrue(result.cta)

    def test_full_script_not_empty(self):
        plan = _make_plan()
        result = generate_script(plan)
        self.assertGreater(len(result.full_script), 20)

    def test_to_dict_is_serialisable(self):
        import json
        plan = _make_plan()
        result = generate_script(plan)
        json.dumps(result.to_dict(), ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
