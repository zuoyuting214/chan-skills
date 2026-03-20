"""
End-to-end integration tests using STUB_MODE=1.
No real API calls are made. Tests verify full workflow wiring.
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
os.environ["STUB_MODE"] = "1"

from run_workflow import run, normalise_request
from schemas import VideoRequest, WorkflowResult


class TestInputNormalisation(unittest.TestCase):

    def test_defaults_applied_when_fields_missing(self):
        req = normalise_request({"topic": "AI agent 入门"})
        self.assertEqual(req.platform, "douyin")
        self.assertEqual(req.duration_sec, 60)
        self.assertTrue(req.use_avatar)
        self.assertTrue(req.subtitle_required)

    def test_explicit_values_override_defaults(self):
        req = normalise_request({"topic": "test", "platform": "shipinhao", "duration_sec": 30})
        self.assertEqual(req.platform, "shipinhao")
        self.assertEqual(req.duration_sec, 30)

    def test_duration_coerced_to_int(self):
        req = normalise_request({"topic": "test", "duration_sec": "90"})
        self.assertIsInstance(req.duration_sec, int)
        self.assertEqual(req.duration_sec, 90)


class TestVagueInputRejection(unittest.TestCase):

    def test_empty_topic_rejected(self):
        result = run({"topic": ""})
        self.assertEqual(result.status, "failed")
        self.assertIn("模糊", result.error)

    def test_very_short_topic_rejected(self):
        result = run({"topic": "AI"})
        self.assertEqual(result.status, "failed")

    def test_hello_rejected(self):
        result = run({"topic": "你好"})
        self.assertEqual(result.status, "failed")

    def test_vague_phrase_rejected(self):
        result = run({"topic": "随便来一个"})
        self.assertEqual(result.status, "failed")


class TestFullWorkflowStub(unittest.TestCase):

    def _run_example(self, topic: str, **kwargs) -> WorkflowResult:
        payload = {"topic": topic, **kwargs}
        return run(payload)

    def test_ai_topic_succeeds(self):
        result = self._run_example("为什么现在很多老板开始重视 AI agent", industry="AI/企业服务")
        self.assertEqual(result.status, "success")

    def test_home_decor_topic_succeeds(self):
        result = self._run_example("家装公司怎么用短视频获客", industry="家装")
        self.assertEqual(result.status, "success")

    def test_family_education_topic_succeeds(self):
        result = self._run_example(
            "家庭教育里，为什么陪伴比说教更重要",
            industry="家庭教育",
            platform="shipinhao",
            duration_sec=90,
        )
        self.assertEqual(result.status, "success")

    def test_result_has_video_plan(self):
        result = self._run_example("为什么现在很多老板开始重视 AI agent")
        self.assertIsNotNone(result.video_plan)
        self.assertIn("topic", result.video_plan)
        self.assertIn("scene_count", result.video_plan)

    def test_result_has_script(self):
        result = self._run_example("为什么现在很多老板开始重视 AI agent")
        self.assertIsNotNone(result.script_result)
        self.assertIn("title", result.script_result)
        self.assertIn("full_script", result.script_result)
        self.assertIn("hook", result.script_result)
        self.assertIn("cta", result.script_result)

    def test_result_has_storyboard(self):
        result = self._run_example("为什么现在很多老板开始重视 AI agent")
        self.assertIsNotNone(result.storyboard_result)
        scenes = result.storyboard_result.get("scenes", [])
        self.assertGreater(len(scenes), 0)

    def test_result_has_render_result(self):
        result = self._run_example("为什么现在很多老板开始重视 AI agent")
        self.assertIsNotNone(result.render_result)
        self.assertIn("render_path", result.render_result)
        self.assertEqual(result.render_result["render_path"], "stub")

    def test_result_has_debug_info(self):
        result = self._run_example("为什么现在很多老板开始重视 AI agent")
        self.assertIn("steps", result.debug)
        self.assertIn("total_sec", result.debug)
        self.assertIn("scene_count", result.debug)

    def test_result_is_json_serialisable(self):
        result = self._run_example("为什么现在很多老板开始重视 AI agent")
        # Should not raise
        json_str = result.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["status"], "success")

    def test_render_path_is_stub(self):
        result = self._run_example("为什么现在很多老板开始重视 AI agent")
        self.assertEqual(result.render_result["render_path"], "stub")

    def test_stub_video_url_is_present(self):
        result = self._run_example("为什么现在很多老板开始重视 AI agent")
        self.assertTrue(result.render_result.get("video_url"))


if __name__ == "__main__":
    unittest.main()
