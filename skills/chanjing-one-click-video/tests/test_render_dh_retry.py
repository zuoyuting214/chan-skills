"""
数字人渲染：公共列表解析 + 多候选依次重试（不调用真实蝉镜 API）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from render import (  # noqa: E402
    ResolvedFigureCandidates,
    _parse_figure_rows,
    _render_dh_scene,
)
from schemas import Scene  # noqa: E402


class TestParseFigureRowsCommon(unittest.TestCase):
    def test_common_one_person_two_figures(self):
        payload = {
            "data": {
                "list": [
                    {
                        "id": "person-1",
                        "gender": "Female",
                        "name": "主播A",
                        "audio_man_id": "am-1",
                        "figures": [
                            {"type": "sit_body", "width": 1080, "height": 1920},
                            {"type": "stand_body", "width": 1080, "height": 1920},
                        ],
                    }
                ]
            }
        }
        rows = _parse_figure_rows(payload, "common")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["person_id"], "person-1")
        self.assertEqual(rows[0]["figure_type"], "sit_body")
        self.assertEqual(rows[1]["figure_type"], "stand_body")

    def test_customised_flat_list(self):
        payload = {
            "data": {
                "list": [
                    {
                        "id": "cust-1",
                        "figure_type": "whole_body",
                        "audio_man_id": "am-x",
                        "gender": "male",
                        "name": "我的定制",
                    }
                ]
            }
        }
        rows = _parse_figure_rows(payload, "customised")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["person_id"], "cust-1")
        self.assertEqual(rows[0]["figure_type"], "whole_body")


class TestRenderDhSceneCandidateRetry(unittest.TestCase):
    def _scene(self) -> Scene:
        return Scene(
            scene_id=1,
            duration_sec=5,
            voiceover="测试口播",
            subtitle="测试",
            visual_prompt="数字人",
            use_avatar=True,
        )

    def test_second_candidate_succeeds(self):
        resolved = ResolvedFigureCandidates(
            candidates=[
                ("bad-person", "sit_body", "v1"),
                ("good-person", "sit_body", "v1"),
            ],
            source="common",
        )
        calls: list[tuple[str, str]] = []

        def fake_once(person_id, figure_type, audio_man_id, scene, wav_path=None):
            calls.append((person_id, figure_type))
            if person_id == "bad-person":
                raise RuntimeError("mock: person unavailable")
            return Path("/tmp/mock-dh-clip.mp4")

        with patch("render._render_dh_scene_once", side_effect=fake_once):
            out = _render_dh_scene(resolved, self._scene(), None)

        self.assertEqual(out, Path("/tmp/mock-dh-clip.mp4"))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "bad-person")
        self.assertEqual(calls[1][0], "good-person")

    def test_all_candidates_fail_message(self):
        resolved = ResolvedFigureCandidates(
            candidates=[("a", "t1", "v"), ("b", "t2", "v")],
            source="common",
        )

        def fake_once(*_args, **_kwargs):
            raise RuntimeError("always fail")

        with patch("render._render_dh_scene_once", side_effect=fake_once):
            with self.assertRaises(RuntimeError) as ctx:
                _render_dh_scene(resolved, self._scene(), None)
        msg = str(ctx.exception)
        self.assertIn("2 个形象", msg)
        self.assertIn("Scene 1", msg)


if __name__ == "__main__":
    unittest.main()
