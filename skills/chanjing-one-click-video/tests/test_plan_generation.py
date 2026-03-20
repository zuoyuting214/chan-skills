"""Unit tests for video plan generation (Module B)."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
os.environ["STUB_MODE"] = "1"

from schemas import VideoRequest, VideoPlan
from planners import generate_video_plan


class TestVideoPlanGeneration(unittest.TestCase):

    def _make_request(self, **kwargs) -> VideoRequest:
        defaults = dict(
            topic="为什么现在很多老板开始重视 AI agent",
            industry="AI/企业服务",
            platform="douyin",
            style="观点型口播",
            duration_sec=60,
            use_avatar=True,
        )
        defaults.update(kwargs)
        return VideoRequest(**defaults)

    def test_returns_video_plan_type(self):
        req = self._make_request()
        plan = generate_video_plan(req)
        self.assertIsInstance(plan, VideoPlan)

    def test_plan_preserves_topic(self):
        req = self._make_request(topic="家装公司怎么用短视频获客")
        plan = generate_video_plan(req)
        self.assertEqual(plan.topic, "家装公司怎么用短视频获客")

    def test_plan_preserves_platform(self):
        req = self._make_request(platform="shipinhao")
        plan = generate_video_plan(req)
        self.assertEqual(plan.platform, "shipinhao")

    def test_scene_count_is_positive(self):
        req = self._make_request(duration_sec=60)
        plan = generate_video_plan(req)
        self.assertGreater(plan.scene_count, 0)
        self.assertLessEqual(plan.scene_count, 10)

    def test_plan_has_all_required_fields(self):
        req = self._make_request()
        plan = generate_video_plan(req)
        self.assertTrue(plan.audience)
        self.assertTrue(plan.core_angle)
        self.assertTrue(plan.video_type)
        self.assertTrue(plan.tone)
        self.assertTrue(plan.cta)

    def test_plan_to_dict_is_serialisable(self):
        import json
        req = self._make_request()
        plan = generate_video_plan(req)
        d = plan.to_dict()
        # Should not raise
        json.dumps(d, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
