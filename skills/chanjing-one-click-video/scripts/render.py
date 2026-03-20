"""
Module E: Render Orchestrator — Mixed Digital Human + AI Video Pipeline

渲染流程（新架构）：
  1. 用整篇文案一次性生成完整 TTS 音频（保证语流连贯、语气自然）
  2. 按各镜头口播文字比例，将完整音频切割为 N 段 WAV
  3. 所有镜头并行渲染：
     use_avatar=True  → 上传对应 WAV → chanjing-video-compose 音频驱动（准确唇型）
     use_avatar=False → chanjing-ai-creation（AI 视频）+ 本地 WAV 合成（不走唇型驱动）
  4. ffmpeg concat 所有片段 → result.mp4（本地文件）

这样 B-roll 不会被 avatar 驱动，A-roll 的唇型与实际播出音频完全一致，
整篇语调自然连贯，CDN 下载只在 DH 视频和 AI 视频下载时发生（均串行）。

配置环境变量：
  CHAN_SKILLS_DIR         chan-skills/skills 目录路径（可选，默认从本文件位置自动推导）
  CHANJING_VOICE_ID       TTS audio_man ID（留空自动取数字人默认音色）
  CHANJING_AVATAR_GENDER  公共数字人性别偏好 Male/Female（默认 Female）
  AI_VIDEO_MODEL          AI 视频生成模型（默认 Doubao-Seedance-1.0-pro）
  STUB_MODE               =1 跳过真实调用
"""

from __future__ import annotations
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from schemas import VideoPlan, ScriptResult, StoryboardResult, RenderResult, Scene
from utils import get_logger, timed

logger = get_logger("render")

AVATAR_GENDER       = os.environ.get("CHANJING_AVATAR_GENDER", "Female").lower()
AI_VIDEO_MODEL      = os.environ.get("AI_VIDEO_MODEL", "Doubao-Seedance-1.0-pro")
OUTPUT_W            = 1080
OUTPUT_H            = 1920
FFMPEG_TIMEOUT      = 1800   # 30 min max per ffmpeg call（CDN 下载慢）
SCENE_MAX_WORKERS   = 5      # 最多并行渲染几个镜头
CDN_MAX_CONCURRENT  = 1      # CDN 串行下载（避免 Chanjing CDN 限流）

# 全局信号量：限制同时进行 CDN 下载（ffmpeg 读取远程 URL）的数量
_cdn_semaphore = threading.Semaphore(CDN_MAX_CONCURRENT)


# ---------------------------------------------------------------------------
# GPU 编码器探测（模块加载时执行一次）
# ---------------------------------------------------------------------------

def _probe_video_encoder() -> tuple[str, list[str]]:
    """
    按优先级探测可用的硬件视频编码器，返回 (codec, quality_args)。
    结果在模块加载时缓存，整个进程内复用。

    优先级：
      1. h264_videotoolbox — macOS VideoToolbox（Apple Silicon / Intel Mac）
      2. h264_nvenc        — NVIDIA GPU
      3. h264_qsv          — Intel Quick Sync
      4. h264_amf          — AMD GPU
      5. libx264           — CPU 软件编码（兜底）
    """
    candidates = [
        ("h264_videotoolbox", ["-q:v", "65"]),
        ("h264_nvenc",        ["-preset", "p4", "-cq", "23"]),
        ("h264_qsv",          ["-preset", "medium"]),
        ("h264_amf",          ["-quality", "balanced"]),
    ]
    test_input = ["-f", "lavfi", "-i", "color=c=black:s=128x128:d=0.1:r=30"]
    for codec, quality_args in candidates:
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error",
                 *test_input,
                 "-c:v", codec, *quality_args,
                 "-f", "null", "-"],
                capture_output=True, timeout=10,
            )
            if r.returncode == 0:
                logger.info("视频编码器: %s（硬件加速）", codec)
                return codec, quality_args
        except Exception:
            continue
    logger.info("视频编码器: libx264（CPU 软件编码）")
    return "libx264", ["-preset", "fast", "-crf", "23"]


_VIDEO_CODEC, _VIDEO_QUALITY_ARGS = _probe_video_encoder()


# ---------------------------------------------------------------------------
# chan-skills 路径解析
# ---------------------------------------------------------------------------

def _skills_root() -> Path:
    # 优先使用环境变量（向后兼容）；否则从本文件位置自动推导：
    # scripts/ → chanjing-one-click-video/ → skills/
    d = os.environ.get("CHAN_SKILLS_DIR", "")
    if d:
        p = Path(d)
        if not p.is_dir():
            raise RuntimeError(f"CHAN_SKILLS_DIR 路径不存在: {p}")
        return p
    inferred = Path(__file__).resolve().parent.parent.parent
    if not inferred.is_dir():
        raise RuntimeError(
            "无法自动推导 chan-skills 路径，请手动设置：\n"
            "  export CHAN_SKILLS_DIR=/path/to/chan-skills/skills"
        )
    return inferred


def _script(skill: str, name: str) -> Path:
    root = _skills_root()
    for candidate in [
        root / "skills" / skill / "scripts" / name,
        root / skill / "scripts" / name,
    ]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"找不到脚本 {skill}/scripts/{name}")


# ---------------------------------------------------------------------------
# 子进程调用
# ---------------------------------------------------------------------------

def _run(script: Path, args: list[str], label: str = "") -> str:
    """运行脚本，返回 stdout（strip）。失败时抛出 RuntimeError。"""
    cmd = [sys.executable, str(script)] + args
    logger.debug("▷ %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(
            f"{label or script.name} 失败 (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    out = result.stdout.strip()
    logger.debug("◁ %s → %s", label or script.name, out[:120])
    return out


# ---------------------------------------------------------------------------
# ffmpeg / ffprobe 工具
# ---------------------------------------------------------------------------

def _ffmpeg(*args: str, label: str = "") -> None:
    """运行 ffmpeg，失败时抛出 RuntimeError。超时 30 分钟（覆盖大文件 CDN 下载场景）。"""
    cmd = ["ffmpeg", "-y", *args]
    logger.debug("ffmpeg %s", " ".join(args[:8]))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg {label} 失败: {result.stderr[-500:]}"
        )


def _get_audio_duration(path: Path) -> float:
    """用 ffprobe 获取音频时长（秒）。"""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


class _noop_ctx:
    """空上下文管理器，用于本地文件跳过信号量。"""
    def __enter__(self): return self
    def __exit__(self, *_): pass


def _normalize(src: str | Path) -> Path:
    """
    将片段统一编码为 1080x1920 h264+aac，返回新临时文件。
    src 可以是本地路径或 HTTP URL。
    远程 URL 使用 CDN 并发信号量，避免 Chanjing CDN 限流。
    """
    out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    out.close()
    src_str = str(src)
    is_remote = src_str.startswith("http")
    ctx = _cdn_semaphore if is_remote else _noop_ctx()
    with ctx:
        _ffmpeg(
            "-i", src_str,
            "-vf", (
                f"scale={OUTPUT_W}:{OUTPUT_H}:force_original_aspect_ratio=decrease,"
                f"pad={OUTPUT_W}:{OUTPUT_H}:(ow-iw)/2:(oh-ih)/2:color=black"
            ),
            "-c:v", _VIDEO_CODEC, *_VIDEO_QUALITY_ARGS,
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            out.name,
            label="normalize",
        )
    return Path(out.name)


def _composite_video_audio(video: str | Path, audio: str | Path) -> Path:
    """将音频叠加到视频上（循环视频以匹配音频长度）。
    video 可以是 URL；audio 通常为本地 WAV 文件。
    仅在 video 为远程 URL 时使用 CDN 信号量。
    """
    out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    out.close()
    is_remote = str(video).startswith("http")
    ctx = _cdn_semaphore if is_remote else _noop_ctx()
    with ctx:
        _ffmpeg(
            "-stream_loop", "-1", "-i", str(video),
            "-i", str(audio),
            "-map", "0:v", "-map", "1:a",
            "-vf", (
                f"scale={OUTPUT_W}:{OUTPUT_H}:force_original_aspect_ratio=decrease,"
                f"pad={OUTPUT_W}:{OUTPUT_H}:(ow-iw)/2:(oh-ih)/2:color=black"
            ),
            "-c:v", _VIDEO_CODEC, *_VIDEO_QUALITY_ARGS,
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-shortest",
            out.name,
            label="composite",
        )
    return Path(out.name)


def _concat_clips(clips: list[Path]) -> Path:
    """用 ffmpeg filter_complex concat 合并所有片段。"""
    if len(clips) == 1:
        return clips[0]

    out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    out.close()

    inputs: list[str] = []
    for clip in clips:
        inputs += ["-i", str(clip)]

    n = len(clips)
    filter_str = "".join(f"[{i}:v][{i}:a]" for i in range(n))
    filter_str += f"concat=n={n}:v=1:a=1[v][a]"

    _ffmpeg(
        *inputs,
        "-filter_complex", filter_str,
        "-map", "[v]", "-map", "[a]",
        "-c:v", _VIDEO_CODEC, *_VIDEO_QUALITY_ARGS,
        "-c:a", "aac",
        out.name,
        label="concat",
    )
    return Path(out.name)


# ---------------------------------------------------------------------------
# Stub
# ---------------------------------------------------------------------------

def _stub_render(plan: VideoPlan, storyboard: StoryboardResult) -> RenderResult:
    logger.info("[STUB] 跳过真实渲染，返回占位结果")
    return RenderResult(
        video_url="https://example.com/stub-video.mp4",
        cover_url="https://example.com/stub-cover.jpg",
        tts_urls=[f"https://example.com/stub-tts-{s.scene_id}.mp3" for s in storyboard.scenes],
        scene_video_urls=[f"https://example.com/stub-scene-{s.scene_id}.mp4" for s in storyboard.scenes],
        render_path="stub",
    )


# ---------------------------------------------------------------------------
# 数字人参数解析
# ---------------------------------------------------------------------------

def _resolve_figure() -> tuple[str, str, str]:
    """
    返回 (person_id, figure_type, audio_man_id)。
    按 CHANJING_AVATAR_GENDER 偏好选择性别，否则取第一个。
    若设置了 CHANJING_VOICE_ID，audio_man_id 用该值覆盖。
    """
    raw = _run(
        _script("chanjing-video-compose", "list_figures"),
        ["--source", "common", "--json"],
        label="list_figures",
    )
    data = json.loads(raw)
    items = data.get("data", {}).get("list", [])
    if not items:
        raise RuntimeError("没有可用的公共数字人形象")

    rows: list[dict] = []
    for item in items:
        for figure in item.get("figures", []):
            rows.append({
                "person_id":    item.get("id", ""),
                "figure_type":  figure.get("type", ""),
                "audio_man_id": item.get("audio_man_id", ""),
                "gender":       item.get("gender", "").lower(),
            })

    if not rows:
        raise RuntimeError("公共数字人列表为空（figures 字段缺失）")

    preferred = [r for r in rows if AVATAR_GENDER in r["gender"]]
    chosen = preferred[0] if preferred else rows[0]

    audio_man_id = os.environ.get("CHANJING_VOICE_ID", "").strip() or chosen["audio_man_id"]
    logger.info(
        "选择公共数字人: person_id=%s, figure_type=%s, audio_man_id=%s",
        chosen["person_id"], chosen["figure_type"], audio_man_id,
    )
    return chosen["person_id"], chosen["figure_type"], audio_man_id


# ---------------------------------------------------------------------------
# 整篇一次性 TTS
# ---------------------------------------------------------------------------

def _generate_full_tts(full_script: str, audio_man_id: str) -> Path:
    """
    用整篇文案生成一条完整 TTS 音频，下载到本地 WAV 文件。
    一次调用覆盖全片，保证语气连贯、不在镜头切换处重置语调。
    """
    logger.info("[TTS] 生成整篇完整音频（一次性）…")
    task_id = _run(
        _script("chanjing-tts", "create_task"),
        ["--audio-man", audio_man_id, "--text", full_script],
        label="full tts create",
    )
    audio_url = _run(
        _script("chanjing-tts", "poll_task"),
        ["--task-id", task_id],
        label="full tts poll",
    )
    out = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    out.close()
    with _cdn_semaphore:
        _ffmpeg(
            "-i", audio_url,
            "-c:a", "copy",
            out.name,
            label="download full tts",
        )
    logger.info("[TTS] 完整音频已下载: %s (url=%s)", out.name, audio_url[:60])
    return Path(out.name)


# ---------------------------------------------------------------------------
# 按镜头比例切割音频
# ---------------------------------------------------------------------------

def _split_audio_by_scenes(wav_path: Path, scenes: list[Scene]) -> list[Path]:
    """
    按各镜头口播文字的字符数比例，将完整 WAV 切割为 N 段。
    返回与 scenes 等长的本地 WAV 路径列表。
    """
    total_duration = _get_audio_duration(wav_path)
    total_chars = sum(len(s.voiceover) for s in scenes) or 1

    logger.info(
        "[Split] 总音频时长 %.2fs，共 %d 镜头，总字符数 %d",
        total_duration, len(scenes), total_chars,
    )

    segments: list[Path] = []
    offset = 0.0
    for i, scene in enumerate(scenes):
        ratio = len(scene.voiceover) / total_chars
        seg_duration = total_duration * ratio
        # 最后一段延伸到结尾，避免浮点累积误差截断
        if i == len(scenes) - 1:
            seg_duration = total_duration - offset

        out = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        out.close()
        _ffmpeg(
            "-i", str(wav_path),
            "-ss", f"{offset:.3f}",
            "-t", f"{seg_duration:.3f}",
            "-c:a", "copy",
            out.name,
            label=f"split scene{scene.scene_id}",
        )
        segments.append(Path(out.name))
        logger.debug(
            "  Scene %d: offset=%.2fs duration=%.2fs (%d chars)",
            scene.scene_id, offset, seg_duration, len(scene.voiceover),
        )
        offset += seg_duration

    return segments


# ---------------------------------------------------------------------------
# 镜头渲染：数字人（音频驱动）
# ---------------------------------------------------------------------------

def _upload_scene_audio(wav_path: Path) -> str:
    """上传 WAV 文件到蝉镜文件存储，返回 file_id。"""
    file_id = _run(
        _script("chanjing-video-compose", "upload_file"),
        ["--service", "make_video_audio", "--file", str(wav_path)],
        label="upload scene audio",
    )
    return file_id.strip()


def _render_dh_scene(person_id: str, figure_type: str, audio_man_id: str,
                     scene: Scene, wav_path: Path | None = None) -> Path:
    """
    生成数字人口播片段。
    wav_path 不为 None 时：上传 WAV → 音频驱动（唇型与实际播出音频一致）。
    wav_path 为 None 时（降级）：文本驱动模式。
    最后 ffmpeg normalize → 本地 mp4。
    """
    if wav_path is not None:
        logger.info("  [DH] Scene %d: 上传音频 → 音频驱动…", scene.scene_id)
        file_id = _upload_scene_audio(wav_path)
        video_id = _run(
            _script("chanjing-video-compose", "create_task"),
            [
                "--person-id", person_id,
                "--figure-type", figure_type,
                "--audio-file-id", file_id,
                "--subtitle", "show",
            ],
            label=f"create_task scene{scene.scene_id}",
        )
    else:
        logger.info("  [DH] Scene %d: 文本驱动（降级）…", scene.scene_id)
        video_id = _run(
            _script("chanjing-video-compose", "create_task"),
            [
                "--person-id", person_id,
                "--figure-type", figure_type,
                "--text", scene.voiceover,
                "--audio-man", audio_man_id,
                "--subtitle", "show",
            ],
            label=f"create_task scene{scene.scene_id}",
        )

    video_url = _run(
        _script("chanjing-video-compose", "poll_task"),
        ["--id", video_id],
        label=f"poll_task scene{scene.scene_id}",
    )
    logger.info("  [DH] Scene %d URL 就绪: %s", scene.scene_id, video_url[:60])
    return _normalize(video_url)


# ---------------------------------------------------------------------------
# 镜头渲染：AI 生成画面 + 预切割音频
# ---------------------------------------------------------------------------

def _render_ai_scene(scene: Scene, wav_path: Path) -> Path:
    """
    生成 AI 画面片段：
    1. 提交 AI 视频任务并等待
    2. ffmpeg composite（AI 视频 URL + 本地 WAV）→ 本地 mp4
    不调用独立 TTS，直接使用从整篇音频切割出的本地 WAV。
    """
    logger.info("  [AI] Scene %d: 提交 AI 视频任务…", scene.scene_id)
    # 模型要求 video_duration ∈ [5, 10]；较长镜头由 ffmpeg loop 补足
    ai_duration = max(5, min(10, scene.duration_sec))
    ai_unique_id = _run(
        _script("chanjing-ai-creation", "submit_task"),
        [
            "--creation-type", "4",
            "--model-code", AI_VIDEO_MODEL,
            "--prompt", scene.visual_prompt,
            "--aspect-ratio", "9:16",
            "--video-duration", str(ai_duration),
        ],
        label=f"ai-creation submit scene{scene.scene_id}",
    )

    ai_video_url = _run(
        _script("chanjing-ai-creation", "poll_task"),
        ["--unique-id", ai_unique_id],
        label=f"ai-creation poll scene{scene.scene_id}",
    )
    logger.info("  [AI] Scene %d 视频就绪: %s", scene.scene_id, ai_video_url[:60])

    # ffmpeg composite：AI 视频（CDN URL）+ 本地 WAV（无需 CDN 信号量处理音频）
    return _composite_video_audio(ai_video_url, wav_path)


# ---------------------------------------------------------------------------
# 主渲染路径：整篇 TTS → 切割 → 并行渲染 → concat
# ---------------------------------------------------------------------------

def _render_mixed(plan: VideoPlan, script: ScriptResult,
                  storyboard: StoryboardResult) -> RenderResult:
    logger.info("[Mixed] 开始混合渲染（整篇 TTS → 切割 → 数字人+AI 并行）…")
    person_id, figure_type, audio_man_id = _resolve_figure()

    # Step 1: 整篇一次性 TTS → 本地 WAV
    with timed("full TTS", logger):
        full_wav = _generate_full_tts(script.full_script, audio_man_id)

    # Step 2: 按文字比例切割为各镜头 WAV
    with timed("split audio", logger):
        scene_wavs = _split_audio_by_scenes(full_wav, storyboard.scenes)

    # Step 3: 并行渲染所有镜头
    def _render_scene(args: tuple[Scene, Path]) -> tuple[int, Path | None]:
        scene, wav_path = args
        try:
            if scene.use_avatar:
                clip = _render_dh_scene(person_id, figure_type, audio_man_id, scene, wav_path)
            else:
                clip = _render_ai_scene(scene, wav_path)
            logger.info("  Scene %d 完成 (%s)", scene.scene_id,
                        "DH" if scene.use_avatar else "AI")
            return scene.scene_id, clip
        except Exception as exc:
            logger.warning("  Scene %d 失败，降级为数字人文本驱动: %s", scene.scene_id, exc)
            try:
                clip = _render_dh_scene(person_id, figure_type, audio_man_id, scene)
                logger.info("  Scene %d 降级成功 (DH text)", scene.scene_id)
                return scene.scene_id, clip
            except Exception as exc2:
                logger.error("  Scene %d 完全失败: %s", scene.scene_id, exc2)
                return scene.scene_id, None

    clips_by_id: dict[int, Path | None] = {}
    scene_args = list(zip(storyboard.scenes, scene_wavs))
    with concurrent.futures.ThreadPoolExecutor(max_workers=SCENE_MAX_WORKERS) as pool:
        futures = {pool.submit(_render_scene, args): args[0] for args in scene_args}
        for future in concurrent.futures.as_completed(futures):
            scene_id, clip = future.result()
            clips_by_id[scene_id] = clip

    # 按镜头顺序整理（跳过失败的）
    ordered_clips: list[Path] = []
    scene_video_paths: list[str] = []
    for scene in storyboard.scenes:
        clip = clips_by_id.get(scene.scene_id)
        if clip:
            ordered_clips.append(clip)
            scene_video_paths.append(str(clip))
        else:
            scene_video_paths.append("")

    if not ordered_clips:
        raise RuntimeError("所有镜头渲染均失败")

    logger.info("[Mixed] 合并 %d 个片段…", len(ordered_clips))
    with timed("ffmpeg concat", logger):
        final_path = _concat_clips(ordered_clips)

    # 清理临时文件
    full_wav.unlink(missing_ok=True)
    for wav in scene_wavs:
        wav.unlink(missing_ok=True)
    for clip in ordered_clips:
        if clip != final_path:
            clip.unlink(missing_ok=True)

    logger.info("[Mixed] 完成: %s", final_path)
    return RenderResult(
        video_file=str(final_path),
        scene_video_urls=scene_video_paths,
        render_path="mixed_dh_ai",
    )


# ---------------------------------------------------------------------------
# 降级路径：全数字人文本驱动（当混合渲染整体失败时）
# ---------------------------------------------------------------------------

def _render_all_dh(plan: VideoPlan, script: ScriptResult,
                   storyboard: StoryboardResult) -> RenderResult:
    logger.info("[AllDH] 全数字人并行渲染（降级模式，文本驱动）…")
    person_id, figure_type, audio_man_id = _resolve_figure()

    def _render_one(scene: Scene) -> tuple[int, Path | None]:
        try:
            clip = _render_dh_scene(person_id, figure_type, audio_man_id, scene)
            return scene.scene_id, clip
        except Exception as exc:
            logger.warning("  Scene %d 失败（跳过）: %s", scene.scene_id, exc)
            return scene.scene_id, None

    clips_by_id: dict[int, Path | None] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=SCENE_MAX_WORKERS) as pool:
        for scene_id, clip in pool.map(_render_one, storyboard.scenes):
            clips_by_id[scene_id] = clip

    ordered_clips = [clips_by_id[s.scene_id] for s in storyboard.scenes
                     if clips_by_id.get(s.scene_id)]
    scene_video_paths = [str(clips_by_id.get(s.scene_id) or "") for s in storyboard.scenes]

    if not ordered_clips:
        raise RuntimeError("所有镜头渲染均失败")

    with timed("ffmpeg concat (all-DH)", logger):
        final_path = _concat_clips(ordered_clips)

    for clip in ordered_clips:
        if clip != final_path:
            clip.unlink(missing_ok=True)

    return RenderResult(
        video_file=str(final_path),
        scene_video_urls=scene_video_paths,
        render_path="all_dh",
    )


# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------

def render_video(plan: VideoPlan, script: ScriptResult,
                 storyboard: StoryboardResult) -> RenderResult:
    if os.environ.get("STUB_MODE") == "1":
        return _stub_render(plan, storyboard)

    try:
        with timed("mixed render", logger):
            return _render_mixed(plan, script, storyboard)
    except Exception as exc:
        logger.warning("混合渲染失败，降级为全数字人: %s", exc)
        with timed("all-DH fallback", logger):
            return _render_all_dh(plan, script, storyboard)
