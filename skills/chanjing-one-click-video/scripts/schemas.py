"""
Data schemas and validation for chanjing-one-click-video skill.
All intermediate objects are defined here to keep the rest of the codebase clean.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Optional
import json


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

@dataclass
class VideoRequest:
    """Normalised user request. All downstream modules consume this."""
    topic: str
    industry: str = ""
    platform: str = "douyin"           # douyin / shipinhao / xiaohongshu
    style: str = "观点型口播"            # 干货 / 观点 / 种草 / 口播
    duration_sec: int = 60             # 30 / 60 / 90
    use_avatar: bool = True
    avatar_id: str = ""                # empty = use platform default
    voice_id: str = ""                 # empty = use platform default
    subtitle_required: bool = True
    cover_required: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "VideoRequest":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in allowed})


# ---------------------------------------------------------------------------
# Video Plan
# ---------------------------------------------------------------------------

@dataclass
class VideoPlan:
    """High-level creative plan for the video."""
    topic: str
    industry: str
    platform: str
    style: str
    duration_sec: int
    audience: str
    core_angle: str
    video_type: str          # avatar_talking_head / b_roll_mix
    scene_count: int
    tone: str
    cta: str
    use_avatar: bool
    subtitle_required: bool
    cover_required: bool
    avatar_id: str = ""
    voice_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "VideoPlan":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})


# ---------------------------------------------------------------------------
# Script Result
# ---------------------------------------------------------------------------

@dataclass
class ScriptResult:
    """Generated copy / voiceover script."""
    title: str
    hook: str
    full_script: str
    cta: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ScriptResult":
        return cls(**d)


# ---------------------------------------------------------------------------
# Storyboard
# ---------------------------------------------------------------------------

@dataclass
class Scene:
    scene_id: int
    duration_sec: int
    voiceover: str
    subtitle: str
    visual_prompt: str
    use_avatar: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StoryboardResult:
    scenes: List[Scene]

    def to_dict(self) -> dict:
        return {"scenes": [s.to_dict() for s in self.scenes]}

    @classmethod
    def from_dict(cls, d: dict) -> "StoryboardResult":
        scenes = [Scene(**s) for s in d.get("scenes", [])]
        return cls(scenes=scenes)


# ---------------------------------------------------------------------------
# Render Result
# ---------------------------------------------------------------------------

@dataclass
class RenderResult:
    video_url: str = ""
    video_file: str = ""
    cover_url: str = ""
    tts_urls: List[str] = field(default_factory=list)
    scene_video_urls: List[str] = field(default_factory=list)
    render_path: str = ""              # avatar_direct_render / tts_compose / stub

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Final Output
# ---------------------------------------------------------------------------

@dataclass
class WorkflowResult:
    status: str                        # success / partial / failed
    video_plan: Optional[dict] = None
    script_result: Optional[dict] = None
    storyboard_result: Optional[dict] = None
    render_result: Optional[dict] = None
    error: Optional[str] = None
    debug: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "video_plan": self.video_plan,
            "script_result": self.script_result,
            "storyboard_result": self.storyboard_result,
            "render_result": self.render_result,
            "error": self.error,
            "debug": self.debug,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
